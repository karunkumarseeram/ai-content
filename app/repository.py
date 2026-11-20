from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.database import get_session_factory
from app.db.models import JobRecord


def create_job(database_url: str, job: dict) -> None:
    now = datetime.now(timezone.utc)
    with get_session_factory(database_url)() as session:
        session.add(
            JobRecord(
                id=job["id"],
                created_at=now,
                updated_at=now,
                status=job["status"],
                platforms={},
            )
        )
        session.commit()


def save_job(database_url: str, job: dict) -> None:
    with get_session_factory(database_url)() as session:
        record = session.get(JobRecord, job["id"])
        if record is None:
            raise RuntimeError(f"News job {job['id']} was not found in the database.")
        record.updated_at = datetime.now(timezone.utc)
        record.status = job["status"]
        record.article_count = job.get("article_count", 0)
        record.script = job.get("script")
        record.script_word_count = job.get("script_word_count")
        record.opening = job.get("opening")
        record.closing = job.get("closing")
        record.beats = job.get("beats")
        record.articles = job.get("articles")
        record.video_filename = job.get("video_filename")
        record.platforms = job.get("platforms", {})
        record.error = job.get("error")
        published_at = job.get("published_at")
        record.published_at = (
            datetime.fromisoformat(published_at) if published_at else None
        )
        session.commit()


def get_job(database_url: str, job_id: str) -> JobRecord | None:
    with get_session_factory(database_url)() as session:
        return session.get(JobRecord, job_id)


def get_latest_job(database_url: str) -> JobRecord | None:
    with get_session_factory(database_url)() as session:
        return session.scalar(
            select(JobRecord).order_by(JobRecord.created_at.desc()).limit(1)
        )


def get_latest_prepared_job(database_url: str, max_age: timedelta) -> JobRecord | None:
    cutoff = datetime.now(timezone.utc) - max_age
    with get_session_factory(database_url)() as session:
        return session.scalar(
            select(JobRecord)
            .where(JobRecord.status == "ready", JobRecord.created_at >= cutoff)
            .order_by(JobRecord.created_at.desc())
            .limit(1)
        )


def delete_expired_jobs(database_url: str, created_before: datetime) -> list[str]:
    with get_session_factory(database_url)() as session:
        expired = list(
            session.scalars(
                select(JobRecord).where(JobRecord.created_at < created_before)
            ).all()
        )
        filenames = [
            record.video_filename
            for record in expired
            if record.video_filename
        ]
        for record in expired:
            session.delete(record)
        session.commit()
        return filenames
