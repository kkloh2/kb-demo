"""Drop approval_task.title: metadata.title has it.

approval_task keeps two JSON columns: subject_snapshot (exactly what the round reviews, evidence,
never changed) and metadata (additional information, e.g. for lists).

Revision ID: 0008
Revises: 0007
Created: 2026-11-16 18:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = '0008'
down_revision: str | None = '0007'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

METADATA = sa.JSON().with_variant(JSONB(), "postgresql")
task = sa.table("approval_task", sa.column("id", sa.Uuid()), sa.column("approval_request_id", sa.Uuid()),
                sa.column("title", sa.String()), sa.column("metadata", METADATA))
request = sa.table("approval_request", sa.column("id", sa.Uuid()), sa.column("title", sa.String()))


def _sqlite_foreign_keys(on: bool) -> None:
    """Off while approval_task is rebuilt (other tables reference it); checked when back on."""
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    bind.exec_driver_sql(f"PRAGMA foreign_keys={'ON' if on else 'OFF'}")
    if on:
        problems = bind.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        if problems:
            raise RuntimeError(f"Foreign key problems after the rebuild: {problems[:5]}")


def upgrade() -> None:
    bind = op.get_bind()
    # Make sure every task's metadata has its title before the column goes.
    for task_id, title, meta in bind.execute(sa.select(task.c.id, task.c.title, task.c.metadata)).all():
        meta = dict(meta or {})
        if not meta.get("title"):
            meta["title"] = title
            bind.execute(task.update().where(task.c.id == task_id).values(metadata=meta))
    _sqlite_foreign_keys(False)
    with op.batch_alter_table('approval_task', schema=None) as batch_op:
        batch_op.drop_column('title')
    _sqlite_foreign_keys(True)


def downgrade() -> None:
    _sqlite_foreign_keys(False)
    with op.batch_alter_table('approval_task', schema=None) as batch_op:
        batch_op.add_column(sa.Column('title', sa.String(length=255), nullable=True))
    bind = op.get_bind()
    for task_id, request_id, meta in bind.execute(sa.select(task.c.id, task.c.approval_request_id,
                                                            task.c.metadata)).all():
        title = (meta or {}).get("title") or bind.execute(
            sa.select(request.c.title).where(request.c.id == request_id)).scalar() or ""
        bind.execute(task.update().where(task.c.id == task_id).values(title=title))
    with op.batch_alter_table('approval_task', schema=None) as batch_op:
        batch_op.alter_column('title', existing_type=sa.String(length=255), nullable=False)
    _sqlite_foreign_keys(True)
