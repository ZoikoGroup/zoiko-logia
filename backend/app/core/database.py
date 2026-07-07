# SQLAlchemy engine/session setup for PostgreSQL (pgvector extension enabled)
# Falls back to SQLite for local development when DATABASE_URL is absent.
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator

from app.core.config import get_settings

_settings = get_settings()

# For SQLite we need check_same_thread=False; PostgreSQL ignores it.
_connect_args = {"check_same_thread": False} if _settings.is_sqlite else {}

engine = create_engine(
    _settings.DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
