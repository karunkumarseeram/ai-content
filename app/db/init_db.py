from sqlalchemy import text

from app.db.base import Base
from app.db.database import get_engine
from app.db import models  # noqa: F401
from app.settings import Settings


def init_db(settings: Settings | None = None) -> None:
    settings = settings or Settings.from_env()
    if settings.require_postgres and not settings.database_url.startswith(
        ("postgres://", "postgresql://", "postgresql+psycopg://")
    ):
        raise RuntimeError(
            "This deployment requires Neon PostgreSQL; set DATABASE_URL in Render."
        )
    engine = get_engine(settings.database_url)
    Base.metadata.create_all(bind=engine)
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
