import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI

from app.api import health, jobs, media
from app.db.init_db import init_db
from app.pipeline import prepare_daily_job, publish_prepared_job
from app.settings import Settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


app = FastAPI(title="104Dairies Daily News")


@app.on_event("startup")
def startup_event() -> None:
    settings = Settings.from_env()
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    (settings.output_dir / "videos").mkdir(parents=True, exist_ok=True)

    # Tables have already been created; uncomment to create missing tables at startup.
    # init_db(settings)

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


@app.on_event("shutdown")
def shutdown_event() -> None:
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler is not None and scheduler.running:
        scheduler.shutdown(wait=False)


app.include_router(health.router)
app.include_router(jobs.router)
app.include_router(media.router)
