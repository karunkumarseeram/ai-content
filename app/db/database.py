import threading
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_database_url: str | None = None
_engine_lock = threading.Lock()


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return "postgresql+psycopg://" + database_url.removeprefix("postgres://")
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_url.removeprefix("postgresql://")
    return database_url


def get_engine(database_url: str) -> Engine:
    global _engine, _session_factory, _database_url
    normalized_url = normalize_database_url(database_url)
    with _engine_lock:
        if _engine is None or _database_url != normalized_url:
            if normalized_url.startswith("sqlite:///"):
                database_path = Path(normalized_url.removeprefix("sqlite:///"))
                if database_path != Path(":memory:"):
                    database_path.parent.mkdir(parents=True, exist_ok=True)
                engine = create_engine(
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
                engine = create_engine(
                    normalized_url,
                    pool_pre_ping=True,
                    pool_size=5,
                    max_overflow=5,
                    pool_recycle=300,
                )
            _engine = engine
            _session_factory = sessionmaker(bind=engine, expire_on_commit=False)
            _database_url = normalized_url
        return _engine


def get_session_factory(database_url: str) -> sessionmaker[Session]:
    get_engine(database_url)
    if _session_factory is None:
        raise RuntimeError("The database session factory was not initialized.")
    return _session_factory
