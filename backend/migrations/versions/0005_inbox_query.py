"""The approvals inbox as one query, starting from the person.

- approval_task_assignment.status: ACTIVE while its task waits, CLOSED once decided or cancelled.
  The inbox index is (hierarchy_node_id, required_role_id) over ACTIVE ones only, so it never
  reads history. It replaces the (group_id, required_role_id) index: tasks are matched by node
  and role, through any of the node's groups.
- approval_request.maker_id: who made the subject (a document's uploader). They never decide it.
  Filled in for existing document requests.

Revision ID: 0005
Revises: 0004
Created: 2026-11-16 16:00:00
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0005'
down_revision: str | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

task = sa.table("approval_task", sa.column("id", sa.Uuid()), sa.column("status", sa.String()))
assignment = sa.table("approval_task_assignment", sa.column("approval_task_id", sa.Uuid()),
                      sa.column("status", sa.String()))
request = sa.table("approval_request", sa.column("id", sa.Uuid()), sa.column("subject_type", sa.String()),
                   sa.column("subject_id", sa.String()), sa.column("maker_id", sa.Uuid()))
document = sa.table("document", sa.column("id", sa.Uuid()), sa.column("maker_id", sa.Uuid()))

OPEN = "status = 'ACTIVE'"


def _sqlite_foreign_keys(on: bool) -> None:
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
    bind = op.get_bind()
    with op.batch_alter_table('approval_task_assignment', schema=None) as batch_op:
        batch_op.add_column(sa.Column('status', sa.String(length=16), nullable=True))
    pending = sa.select(task.c.id).where(task.c.status == "PENDING")
    bind.execute(assignment.update().values(status=sa.case((assignment.c.approval_task_id.in_(pending), "ACTIVE"),
                                                           else_="CLOSED")))
    with op.batch_alter_table('approval_task_assignment', schema=None) as batch_op:
        batch_op.alter_column('status', existing_type=sa.String(length=16), nullable=False)
        batch_op.create_check_constraint('ck_approval_task_assignment_status', "status IN ('ACTIVE', 'CLOSED')")
        batch_op.drop_index('ix_approval_task_assignment_inbox')
        batch_op.create_index('ix_approval_task_assignment_open', ['hierarchy_node_id', 'required_role_id'],
                              unique=False, sqlite_where=sa.text(OPEN), postgresql_where=sa.text(OPEN))

    op.add_column('approval_request', sa.Column('maker_id', sa.Uuid(), nullable=True))
    for request_id, subject_id in bind.execute(sa.select(request.c.id, request.c.subject_id)
                                               .where(request.c.subject_type == "DOCUMENT")).all():
        try:
            doc_id = uuid.UUID(subject_id)
        except ValueError:
            continue
        maker = bind.execute(sa.select(document.c.maker_id).where(document.c.id == doc_id)).scalar()
        if maker is not None:
            bind.execute(request.update().where(request.c.id == request_id).values(maker_id=maker))
    _sqlite_foreign_keys(True)


def downgrade() -> None:
    _sqlite_foreign_keys(False)
    with op.batch_alter_table('approval_request', schema=None) as batch_op:
        batch_op.drop_column('maker_id')
    with op.batch_alter_table('approval_task_assignment', schema=None) as batch_op:
        batch_op.drop_index('ix_approval_task_assignment_open', sqlite_where=sa.text(OPEN),
                            postgresql_where=sa.text(OPEN))
        batch_op.drop_constraint('ck_approval_task_assignment_status', type_='check')
        batch_op.drop_column('status')
        batch_op.create_index('ix_approval_task_assignment_inbox', ['group_id', 'required_role_id'], unique=False)
    _sqlite_foreign_keys(True)
