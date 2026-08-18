from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    echo=settings.DEBUG,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy 2.0 ORM models.
    """
    pass


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency yielding a database session per request context.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
