from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.models import Base, Department
from app.workflow import models as _workflow_models  # noqa: F401  (registers workflow tables)


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


def _add_missing_columns(engine: Engine) -> None:
    """Add new nullable columns to existing tables (stop-gap until Alembic migrations)."""
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in existing and col.nullable:
                    col_type = col.type.compile(dialect=engine.dialect)
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col_type}'))


def init_db() -> None:
    """Create tables if missing and seed demo data into an empty database."""
    from app.db.seed import seed, sync_roles_and_permissions  # local import: avoids a cycle

    Base.metadata.create_all(get_engine())
    _add_missing_columns(get_engine())
    with new_session() as db:
        if get_settings().seed_demo_data and db.scalar(select(Department.id).limit(1)) is None:
            seed(db)
        else:
            from app.services import document_approval
            from app.workflow.service import ensure_builtin_definitions

            sync_roles_and_permissions(db)
            ensure_builtin_definitions(db)
            document_approval.backfill(db)  # pending documents from before the workflow module
            db.commit()


def reset_database() -> None:
    """Drop everything and re-seed. Used by tests and `python -m app.db.reset`."""
    import shutil

    from app.db.seed import seed

    shutil.rmtree(get_settings().upload_dir, ignore_errors=True)
    Base.metadata.drop_all(get_engine())
    Base.metadata.create_all(get_engine())
    with new_session() as db:
        seed(db)
