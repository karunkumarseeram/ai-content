import asyncio

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import require_control_token
from app.pipeline import prepare_offline_news_job, run_daily_job
from app.repository import get_latest_job
from app.settings import Settings

router = APIRouter(
    prefix="/jobs",
    dependencies=[Depends(require_control_token)],
)


@router.post("/run")
async def run_job() -> dict:
    return await asyncio.to_thread(run_daily_job, Settings.from_env())


@router.post("/generate")
async def generate_job() -> dict:
    return await asyncio.to_thread(prepare_offline_news_job, Settings.from_env())


@router.get("/latest")
def latest_job() -> dict:
    settings = Settings.from_env()
    record = get_latest_job(settings.database_url)
    if record is None:
        raise HTTPException(status_code=404, detail="No news job has run yet.")
    return record.as_dict(settings.output_dir)
