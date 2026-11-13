"""The Alembic migrations (backend/migrations) and the models must describe the same schema."""

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, event, inspect

from app.db.base import Base
from app.db.migrations import (
    DatabaseNotMigrated,
    alembic_config,
    current_revision,
    head_revision,
    require_head,
    upgrade_to_head,
)
from app.db.session import register_models


@pytest.fixture
def engine(tmp_path):
    """A separate, empty SQLite database (foreign keys on, like the app's)."""
    e = create_engine(f"sqlite:///{tmp_path / 'migrations.db'}")
    event.listen(e, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    yield e
    e.dispose()


def _downgrade(engine, target: str) -> None:
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, target)


def test_migrations_build_exactly_the_models_schema(engine):
    upgrade_to_head(engine)
    register_models()
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)
    assert differences == [], (
        "The models and the migrations disagree. Add a migration: "
        "`alembic revision --autogenerate -m '...' --rev-id NNNN`, then review it."
    )
    assert current_revision(engine) == head_revision()


def test_migrations_go_down_and_up_again(engine):
    upgrade_to_head(engine)
    _downgrade(engine, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    upgrade_to_head(engine)
    assert current_revision(engine) == head_revision()


def test_start_up_refuses_a_database_that_is_not_up_to_date(engine):
    with pytest.raises(DatabaseNotMigrated, match="alembic upgrade head"):
        require_head(engine)  # empty: no migration applied
    upgrade_to_head(engine)
    require_head(engine)  # up to date: fine
