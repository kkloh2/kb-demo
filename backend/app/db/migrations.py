"""Run the Alembic migrations (backend/migrations) from the app.

At start-up the app either brings the database up to date (DATAHUB_AUTO_MIGRATE=true, the default)
or, in production with DATAHUB_AUTO_MIGRATE=false, refuses to start until someone has run
`alembic upgrade head` as a deployment step.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

BACKEND_DIR = Path(__file__).resolve().parents[2]


def alembic_config() -> Config:
    """alembic.ini, wherever the app was started from."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.attributes["embedded"] = True  # keep the app's logging
    return config


def head_revision() -> str | None:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def upgrade_to_head(engine: Engine) -> None:
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


class DatabaseNotMigrated(RuntimeError):
    pass


def require_head(engine: Engine) -> None:
    """Fail start-up clearly when the database isn't at the latest migration."""
    current, head = current_revision(engine), head_revision()
    if current != head:
        raise DatabaseNotMigrated(
            f"The database is at migration {current or '(none)'}, but this version of Data Hub needs {head}. "
            "Run `alembic upgrade head` from backend/ (back up the database first), "
            "or set DATAHUB_AUTO_MIGRATE=true."
        )
