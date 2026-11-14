import asyncio
import hmac
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text

from app.pipeline import prepare_daily_job, publish_prepared_job, run_daily_job
from app.repository import get_engine, get_job, get_latest_job, initialize_database
from app.settings import Settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
bearer_scheme = HTTPBearer(auto_error=False)


def _load_job(settings: Settings) -> dict:
    record = get_latest_job(settings.database_url)
    if record is None:
        raise HTTPException(status_code=404, detail="No news job has run yet.")
    return record.as_dict(settings.output_dir)


def _require_control_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> None:
    token = Settings.from_env().control_token
    if not token:
        raise HTTPException(
            status_code=503,
            detail="Set CONTROL_TOKEN to enable protected job and status endpoints.",
        )
    if credentials is None or not hmac.compare_digest(credentials.credentials, token):
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    if settings.require_postgres and not settings.database_url.startswith(
        ("postgres://", "postgresql://", "postgresql+psycopg://")
    ):
        raise RuntimeError(
            "This deployment requires Neon PostgreSQL; set DATABASE_URL in Render."
        )
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    (settings.output_dir / "videos").mkdir(parents=True, exist_ok=True)
    initialize_database(settings.database_url)
    try:
        ZoneInfo(settings.timezone)
        hour_text, minute_text = settings.posting_time.split(":", maxsplit=1)
        hour, minute = int(hour_text), int(minute_text)
        if not 0 <= hour < 24 or not 0 <= minute < 60:
            raise ValueError
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise RuntimeError(
            "TIMEZONE or POSTING_TIME is invalid; use an IANA timezone and HH:MM."
        ) from exc

    preparation_time = (hour * 60 + minute - 60) % (24 * 60)
    preparation_hour, preparation_minute = divmod(preparation_time, 60)
    scheduler = BackgroundScheduler(timezone=settings.timezone)

    def scheduled_prepare() -> None:
        result = prepare_daily_job(settings)
        if result.get("status") != "ready":
            logger.error("Scheduled news preparation failed: %s", result)

    def scheduled_publish() -> None:
        result = publish_prepared_job(settings)
        if result.get("status") != "published":
            logger.error("Scheduled news publishing failed: %s", result)

    scheduler.add_job(
        scheduled_prepare,
        CronTrigger(
            hour=preparation_hour,
            minute=preparation_minute,
            timezone=settings.timezone,
        ),
        id="prepare-daily-news",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        scheduled_publish,
        CronTrigger(hour=hour, minute=minute, timezone=settings.timezone),
        id="publish-daily-news",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info(
        "Daily news scheduler started for %s at %s.",
        settings.timezone,
        settings.posting_time,
    )
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="104Dairies Daily News", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    try:
        with get_engine(Settings.from_env().database_url).connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        logger.exception("Health check could not reach the database.")
        raise HTTPException(status_code=503, detail="Database is unavailable.") from exc
    return {"status": "ok", "database": "connected"}


@app.post("/jobs/run", dependencies=[Depends(_require_control_token)])
async def run_job() -> dict:
    return await asyncio.to_thread(run_daily_job, Settings.from_env())


@app.get("/jobs/latest", dependencies=[Depends(_require_control_token)])
def latest_job() -> dict:
    return _load_job(Settings.from_env())


@app.get("/media/{filename}")
def media(filename: str) -> FileResponse:
    if not re.fullmatch(r"[a-f0-9]{32}\.mp4", filename):
        raise HTTPException(status_code=404, detail="Media file not found.")
    settings = Settings.from_env()
    record = get_job(settings.database_url, filename[:-4])
    video_path = Path(settings.output_dir) / "videos" / filename
    if record is None or record.video_filename != filename or not video_path.is_file():
        raise HTTPException(status_code=404, detail="Media file not found.")
    return FileResponse(video_path, media_type="video/mp4", filename=filename)
