import logging

from fastapi import FastAPI

from app.api import health, jobs, media
from app.settings import Settings


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger().setLevel(logging.INFO)

app = FastAPI(title="104Dairies Daily News")


@app.on_event("startup")
def startup_event() -> None:
    settings = Settings.from_env()
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    (settings.output_dir / "videos").mkdir(parents=True, exist_ok=True)


app.include_router(health.router)
app.include_router(jobs.router)
app.include_router(media.router)
