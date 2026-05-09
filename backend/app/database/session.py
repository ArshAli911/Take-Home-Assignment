"""SQLAlchemy engine, session factory, and FastAPI dependency."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import DB_URL

# `check_same_thread=False` is the standard SQLite escape hatch when the
# same connection may be touched by FastAPI's threadpool workers.
engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    """FastAPI dependency that yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables. Called once on application startup."""
    # Imported here so model classes are registered against Base.metadata
    # before create_all runs.
    from app.models.video import Base

    Base.metadata.create_all(bind=engine)
