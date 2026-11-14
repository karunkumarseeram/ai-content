import logging
import re
import tempfile
import threading
import uuid
from datetime import datetime, timedelta, timezone as utc_timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app.editor import NewsEditor
from app.news import fetch_articles
from app.publishers import publish_instagram, publish_youtube
from app.repository import (
    create_job,
    delete_expired_jobs,
    get_latest_prepared_job,
    initialize_database,
    save_job,
)
from app.schemas import NewsDraft
from app.settings import Settings
from app.video import VideoGenerator

logger = logging.getLogger(__name__)
_job_lock = threading.Lock()


def _publish_result(job: dict, platform: str, action) -> None:
    try:
        url = action()
        job["platforms"][platform] = {"status": "published", "url": url}
    except Exception as exc:
        logger.exception("Publishing to %s failed.", platform)
        job["platforms"][platform] = {
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }


def _validate_settings(settings: Settings) -> None:
    missing = [
        name
        for name, value in (
            ("OPENAI_API_KEY", settings.openai_api_key),
            ("GEMINI_API_KEY", settings.gemini_api_key),
            ("INSTAGRAM_ACCOUNT_ID", settings.instagram_account_id),
            ("INSTAGRAM_ACCESS_TOKEN", settings.instagram_access_token),
        )
        if not value
    ]
    if not settings.google_oauth_token_json and not settings.google_oauth_token_file.is_file():
        missing.append("YouTube OAuth token (run python -m app.oauth_setup)")
    if not settings.public_base_url.startswith("https://"):
        missing.append("PUBLIC_BASE_URL (public HTTPS origin for Instagram)")
    if missing:
        raise RuntimeError(
            "Daily publishing is not configured. Set up: " + ", ".join(missing)
        )


def prepare_daily_job(settings: Settings | None = None) -> dict:
    settings = settings or Settings.from_env()
    if not _job_lock.acquire(blocking=False):
        return {"status": "skipped", "reason": "A news job is already running."}

    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "created_at": datetime.now(ZoneInfo(settings.timezone)).isoformat(),
        "status": "running",
        "platforms": {},
    }
    job_created = False
    try:
        initialize_database(settings.database_url)
        video_dir = settings.output_dir / "videos"
        video_dir.mkdir(parents=True, exist_ok=True)
        local_today = datetime.now(ZoneInfo(settings.timezone)).date()
        expire_before = datetime.combine(
            local_today, datetime.min.time(), tzinfo=ZoneInfo(settings.timezone)
        ).astimezone(utc_timezone.utc)
        expired_videos = delete_expired_jobs(
            settings.database_url, expire_before
        )
        for filename in expired_videos:
            if re.fullmatch(r"[a-f0-9]{32}\.mp4", filename):
                try:
                    (video_dir / filename).unlink(missing_ok=True)
                except OSError:
                    logger.exception("Could not remove expired generated video %s.", filename)

        create_job(settings.database_url, job)
        job_created = True
        _validate_settings(settings)

        articles = fetch_articles(settings.news_feeds)
        draft = NewsEditor(settings.openai_api_key, settings.openai_model).create_draft(
            articles
        )
        job["article_count"] = len(articles)
        job["script"] = draft.script
        job["script_word_count"] = draft.word_count
        job["opening"] = draft.opening
        job["closing"] = draft.closing
        job["beats"] = [beat.model_dump(mode="json") for beat in draft.beats]
        save_job(settings.database_url, job)

        video_path = video_dir / f"{job_id}.mp4"
        with tempfile.TemporaryDirectory(
            prefix=f"{job_id}-", dir=settings.output_dir
        ) as working_directory:
            VideoGenerator(
                gemini_api_key=settings.gemini_api_key,
                gemini_model=settings.gemini_video_model,
                openai_api_key=settings.openai_api_key,
                tts_model=settings.openai_tts_model,
                ffmpeg_bin=settings.ffmpeg_bin,
            ).create(draft, video_path, Path(working_directory))

        article_map = {
            article.article_id: {
                "source": article.source,
                "url": article.url,
            }
            for article in articles
        }
        job["video_filename"] = video_path.name
        job["video_path"] = str(video_path)
        job["articles"] = article_map
        job["status"] = "ready"
        save_job(settings.database_url, job)
        return job
    except Exception as exc:
        logger.exception("News job %s failed.", job_id)
        job["status"] = "failed"
        job["error"] = f"{type(exc).__name__}: {exc}"
        if job_created:
            save_job(settings.database_url, job)
        return job
    finally:
        _job_lock.release()


def publish_prepared_job(settings: Settings | None = None) -> dict:
    settings = settings or Settings.from_env()
    if not _job_lock.acquire(blocking=False):
        return {"status": "skipped", "reason": "A news job is already running."}

    try:
        initialize_database(settings.database_url)
        record = get_latest_prepared_job(settings.database_url, timedelta(hours=2))
        if record is None:
            return {"status": "failed", "error": "No prepared news video is waiting."}
        job = record.as_dict(settings.output_dir)
        timezone = ZoneInfo(settings.timezone)
        now = datetime.now(timezone)
        prepared_at = datetime.fromisoformat(job["created_at"])
        if prepared_at.tzinfo is None:
            prepared_at = prepared_at.replace(tzinfo=utc_timezone.utc).astimezone(
                timezone
            )
        age = now - prepared_at
        if age < timedelta(0) or age > timedelta(hours=2):
            raise RuntimeError("Prepared news video is more than two hours old.")

        draft = NewsDraft.model_validate(
            {
                "opening": job["opening"],
                "closing": job["closing"],
                "beats": job["beats"],
            }
        )
        article_map = job["articles"]
        video_path = Path(job["video_path"])
        if not video_path.is_file():
            raise RuntimeError("Prepared news video file was not found.")

        _validate_settings(settings)
        _publish_result(
            job,
            "youtube",
            lambda: publish_youtube(settings, video_path, draft, article_map),
        )
        video_url = f"{settings.public_base_url}/media/{video_path.name}"
        _publish_result(
            job,
            "instagram",
            lambda: publish_instagram(settings, video_url, draft, article_map),
        )

        published_count = sum(
            result["status"] == "published" for result in job["platforms"].values()
        )
        job["published_at"] = now.isoformat()
        job["status"] = (
            "published"
            if published_count == len(job["platforms"]) and published_count > 0
            else "partial_failure"
            if published_count > 0
            else "failed"
        )
        save_job(settings.database_url, job)
        return job
    except Exception as exc:
        logger.exception("Could not publish the prepared news job.")
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    finally:
        _job_lock.release()


def run_daily_job(settings: Settings | None = None) -> dict:
    settings = settings or Settings.from_env()
    prepared = prepare_daily_job(settings)
    if prepared.get("status") != "ready":
        return prepared
    return publish_prepared_job(settings)
