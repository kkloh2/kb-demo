"""Alembic environment: the app's settings give the database, the app's models give the schema."""

from logging.config import fileConfig

from alembic import context

from app.db.base import Base
from app.db.session import get_engine, register_models

config = context.config
# From the command line, use alembic.ini's logging. When the app runs migrations at start-up
# (app.db.migrations) it leaves logging alone, so uvicorn's stays as it is.
if config.config_file_name and not config.attributes.get("embedded"):
    fileConfig(config.config_file_name)

register_models()
target_metadata = Base.metadata

OPTIONS = {
    "target_metadata": target_metadata,
    "render_as_batch": True,  # SQLite can't ALTER most things; batch mode rebuilds the table instead
    "compare_type": True,
}


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql`: print the SQL instead of running it."""
    context.configure(url=str(get_engine().url), literal_binds=True, **OPTIONS)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:  # handed over by app.db.migrations
        context.configure(connection=connection, **OPTIONS)
        with context.begin_transaction():
            context.run_migrations()
        return
    with get_engine().connect() as connection:
        context.configure(connection=connection, **OPTIONS)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
