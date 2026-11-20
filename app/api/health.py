import logging

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.db.database import get_engine
from app.settings import Settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    try:
        with get_engine(Settings.from_env().database_url).connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        logger.exception("Health check could not reach the database.")
        raise HTTPException(status_code=503, detail="Database is unavailable.") from exc
    return {"status": "ok", "database": "connected"}
