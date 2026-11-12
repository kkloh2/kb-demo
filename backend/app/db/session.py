from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.base import Base


@lru_cache
def get_engine() -> Engine:
    url = get_settings().database_url
    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False  # FastAPI runs sync endpoints in a threadpool
        if url.startswith("sqlite:///"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args=connect_args)

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record) -> None:  # SQLite has them off by default
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def new_session() -> Session:
    return _session_factory()()


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    db = new_session()
    try:
        yield db
    finally:
        db.close()


Db = Annotated[Session, Depends(get_db)]


def _register_models() -> None:
    """Import every feature's models so Base.metadata knows their tables."""
    import app.auth.models  # noqa: F401
    import app.users.models  # noqa: F401
    import app.documents.models  # noqa: F401


def _reference_data(db: Session) -> None:
    """Data every database needs, kept in sync with the code at every start-up."""
    from app.users.seed import seed_system_admins
    from app.users.service import sync_roles

    sync_roles(db)
    db.flush()
    seed_system_admins(db)


def _seed(db: Session) -> None:
    """Demo data, added only to an empty database. Users need none: they come from the directory."""
    from app.users.seed import seed_departments

    seed_departments(db)


def init_db() -> None:
    """Create tables if missing, sync reference data, and add demo data."""
    _register_models()
    Base.metadata.create_all(get_engine())
    with new_session() as db:
        _reference_data(db)
        if get_settings().seed_demo_data:
            _seed(db)
        db.commit()


def reset_database() -> None:
    """Drop everything and re-seed. Used by tests and `python -m app.db.reset`."""
    _register_models()
    Base.metadata.drop_all(get_engine())
    Base.metadata.create_all(get_engine())
    with new_session() as db:
        _reference_data(db)
        _seed(db)
        db.commit()
