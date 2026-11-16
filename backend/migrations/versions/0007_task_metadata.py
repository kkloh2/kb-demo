"""approval_task.metadata: what lists show, without looking anything else up (JSONB on PostgreSQL).

Written when a task is created: type, type_label, title, round, submitted_by, submitted_at,
resource, subject, plus what the asking module adds. Filled in here for existing tasks from their
request, approval type, resource and the person who submitted that round.

Revision ID: 0007
Revises: 0006
Created: 2026-11-16 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

import app.db.base

revision: str = '0007'
down_revision: str | None = '0006'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

METADATA = sa.JSON().with_variant(JSONB(), "postgresql")
LABELS = {"DOCUMENT_UPLOAD": "Document"}  # approval kinds registered in code when this was written

task = sa.table("approval_task", sa.column("id", sa.Uuid()), sa.column("approval_request_id", sa.Uuid()),
                sa.column("round", sa.Integer()), sa.column("title", sa.String()),
                sa.column("created_at", app.db.base.UTCDateTime()), sa.column("metadata", METADATA))
request = sa.table("approval_request", sa.column("id", sa.Uuid()), sa.column("approval_type_id", sa.Uuid()),
                   sa.column("resource_pk", sa.Uuid()), sa.column("subject_type", sa.String()),
                   sa.column("subject_id", sa.String()), sa.column("requested_by", sa.Uuid()))
approval_type = sa.table("approval_type", sa.column("id", sa.Uuid()), sa.column("code", sa.String()),
                         sa.column("name", sa.String()))
resource = sa.table("resource", sa.column("id", sa.Uuid()), sa.column("resource_type", sa.String()),
                    sa.column("resource_id", sa.String()), sa.column("name", sa.String()))
event = sa.table("approval_event", sa.column("approval_task_id", sa.Uuid()), sa.column("actor_id", sa.Uuid()),
                 sa.column("event_type", sa.String()))
app_user = sa.table("app_user", sa.column("id", sa.Uuid()), sa.column("lan_id", sa.String()),
                    sa.column("display_name", sa.String()))


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
    _sqlite_foreign_keys(False)
    with op.batch_alter_table('approval_task', schema=None) as batch_op:
        batch_op.add_column(sa.Column('metadata', METADATA, nullable=True))
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(task.c.id, task.c.round, task.c.title, task.c.created_at, approval_type.c.code, approval_type.c.name,
                  resource.c.resource_type, resource.c.resource_id, resource.c.name, request.c.subject_type,
                  request.c.subject_id, request.c.requested_by)
        .join(request, request.c.id == task.c.approval_request_id)
        .join(approval_type, approval_type.c.id == request.c.approval_type_id)
        .join(resource, resource.c.id == request.c.resource_pk)).all()
    for (task_id, rnd, title, created, code, type_name, r_type, r_id, r_name, s_type, s_id, requested_by) in rows:
        submitter = bind.execute(sa.select(event.c.actor_id).where(
            event.c.approval_task_id == task_id, event.c.event_type == "REQUEST_RESUBMITTED")).scalar() or requested_by
        who = bind.execute(sa.select(app_user.c.lan_id, app_user.c.display_name)
                           .where(app_user.c.id == submitter)).first()
        meta = {
            "type": code, "type_label": LABELS.get(code, type_name), "title": title, "round": rnd,
            "submitted_by": {"lan_id": who.lan_id, "display_name": who.display_name} if who else None,
            "submitted_at": created.isoformat() if created else None,
            "resource": {"type": r_type, "id": r_id, "name": r_name},
            "subject": {"type": s_type, "id": s_id},
        }
        bind.execute(task.update().where(task.c.id == task_id).values(metadata=meta))
    bind.execute(task.update().where(task.c.metadata.is_(None)).values(metadata={}))
    with op.batch_alter_table('approval_task', schema=None) as batch_op:
        batch_op.alter_column('metadata', existing_type=METADATA, nullable=False)
    _sqlite_foreign_keys(True)


def downgrade() -> None:
    _sqlite_foreign_keys(False)
    with op.batch_alter_table('approval_task', schema=None) as batch_op:
        batch_op.drop_column('metadata')
    _sqlite_foreign_keys(True)
