import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import DateTime, Integer, JSON, String, Text, create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_database_url: str | None = None
_engine_lock = threading.Lock()


class Base(DeclarativeBase):
    pass


class JobRecord(Base):
    __tablename__ = "news_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    article_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    script: Mapped[str | None] = mapped_column(Text)
    script_word_count: Mapped[int | None] = mapped_column(Integer)
    opening: Mapped[str | None] = mapped_column(Text)
    closing: Mapped[str | None] = mapped_column(Text)
    beats: Mapped[list | None] = mapped_column(JSON)
    articles: Mapped[dict | None] = mapped_column(JSON)
    video_filename: Mapped[str | None] = mapped_column(String(100))
    platforms: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text)

    def as_dict(self, output_dir: Path) -> dict:
        result = {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "status": self.status,
            "article_count": self.article_count,
            "script": self.script,
            "script_word_count": self.script_word_count,
            "opening": self.opening,
            "closing": self.closing,
            "beats": self.beats or [],
            "articles": self.articles or {},
            "platforms": self.platforms or {},
            "error": self.error,
        }
        if self.video_filename:
            result["video_path"] = str(output_dir / "videos" / self.video_filename)
        if self.published_at:
            result["published_at"] = self.published_at.isoformat()
        return result


def _normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return "postgresql+psycopg://" + database_url.removeprefix("postgres://")
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_url.removeprefix("postgresql://")
    return database_url


def get_engine(database_url: str) -> Engine:
    global _engine, _session_factory, _database_url
    normalized_url = _normalize_database_url(database_url)
    with _engine_lock:
        if _engine is None or _database_url != normalized_url:
            if normalized_url.startswith("sqlite:///"):
                database_path = Path(normalized_url.removeprefix("sqlite:///"))
                if database_path != Path(":memory:"):
                    database_path.parent.mkdir(parents=True, exist_ok=True)
                _engine = create_engine(
                    normalized_url,
                    connect_args={"check_same_thread": False},
                    poolclass=(
                        StaticPool
                        if normalized_url in {"sqlite:///:memory:", "sqlite://"}
                        else None
                    ),
                    pool_pre_ping=True,
                )
            else:
                _engine = create_engine(
                    normalized_url,
                    pool_pre_ping=True,
                    pool_size=5,
                    max_overflow=5,
                    pool_recycle=300,
                )
            _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
            _database_url = normalized_url
        return _engine


def initialize_database(database_url: str) -> None:
    get_engine(database_url)
    Base.metadata.create_all(bind=get_engine(database_url))


def _sessions(database_url: str) -> sessionmaker[Session]:
    get_engine(database_url)
    assert _session_factory is not None
    return _session_factory


def create_job(database_url: str, job: dict) -> None:
    now = datetime.now(timezone.utc)
    with _sessions(database_url)() as session:
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
    with _sessions(database_url)() as session:
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
    with _sessions(database_url)() as session:
        return session.get(JobRecord, job_id)


def get_latest_job(database_url: str) -> JobRecord | None:
    with _sessions(database_url)() as session:
        return session.scalar(
            select(JobRecord).order_by(JobRecord.created_at.desc()).limit(1)
        )


def get_latest_prepared_job(database_url: str, max_age: timedelta) -> JobRecord | None:
    cutoff = datetime.now(timezone.utc) - max_age
    with _sessions(database_url)() as session:
        return session.scalar(
            select(JobRecord)
            .where(JobRecord.status == "ready", JobRecord.created_at >= cutoff)
            .order_by(JobRecord.created_at.desc())
            .limit(1)
        )


def delete_expired_jobs(database_url: str, created_before: datetime) -> list[str]:
    with _sessions(database_url)() as session:
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
