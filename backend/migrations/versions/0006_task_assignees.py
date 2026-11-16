"""One row per person who may decide each waiting task (approval_task_assignee).

The inbox reads a person's ACTIVE rows directly (a partial index on user_id). Rows are written
when a task is created, kept current when roles change, and closed when the task is decided or
cancelled. Filled in here for tasks already waiting: active users holding the required role at the
task's node (their own role or a group's), less the maker, the requester and anyone who submitted.

Revision ID: 0006
Revises: 0005
Created: 2026-11-16 16:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db.base
from app.db.base import utcnow, uuid7

revision: str = '0006'
down_revision: str | None = '0005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OPEN = "status = 'ACTIVE'"

app_user = sa.table("app_user", sa.column("id", sa.Uuid()), sa.column("status", sa.String()))
group = sa.table("user_group", sa.column("id", sa.Uuid()), sa.column("hierarchy_node_id", sa.Uuid()),
                 sa.column("group_type", sa.String()), sa.column("status", sa.String()))
member = sa.table("user_group_member", sa.column("id", sa.Uuid()), sa.column("group_id", sa.Uuid()),
                  sa.column("user_id", sa.Uuid()), sa.column("status", sa.String()))
member_role = sa.table("user_group_member_role", sa.column("group_member_id", sa.Uuid()),
                       sa.column("role_id", sa.Uuid()), sa.column("status", sa.String()))
group_role = sa.table("user_group_role", sa.column("group_id", sa.Uuid()), sa.column("role_id", sa.Uuid()),
                      sa.column("status", sa.String()))
task = sa.table("approval_task", sa.column("id", sa.Uuid()), sa.column("approval_request_id", sa.Uuid()),
                sa.column("status", sa.String()))
assignment = sa.table("approval_task_assignment", sa.column("approval_task_id", sa.Uuid()),
                      sa.column("hierarchy_node_id", sa.Uuid()), sa.column("required_role_id", sa.Uuid()),
                      sa.column("status", sa.String()))
request = sa.table("approval_request", sa.column("id", sa.Uuid()), sa.column("requested_by", sa.Uuid()),
                   sa.column("maker_id", sa.Uuid()))
event = sa.table("approval_event", sa.column("approval_request_id", sa.Uuid()), sa.column("actor_id", sa.Uuid()),
                 sa.column("event_type", sa.String()))
assignee = sa.table("approval_task_assignee", sa.column("id", sa.Uuid()), sa.column("approval_task_id", sa.Uuid()),
                    sa.column("user_id", sa.Uuid()), sa.column("status", sa.String()),
                    sa.column("assigned_at", app.db.base.UTCDateTime()),
                    sa.column("updated_at", app.db.base.UTCDateTime()))


def _holders(bind, node_id, role_id) -> set:
    """Active users holding the role at the node, themselves or through a group."""
    base = (sa.select(member.c.user_id)
            .join(group, group.c.id == member.c.group_id)
            .join(app_user, app_user.c.id == member.c.user_id)
            .where(group.c.hierarchy_node_id == node_id, group.c.status == "ACTIVE", group.c.group_type != "TEAM",
                   member.c.status == "ACTIVE", app_user.c.status == "ACTIVE"))
    own = base.join(member_role, member_role.c.group_member_id == member.c.id).where(
        member_role.c.role_id == role_id, member_role.c.status == "ACTIVE")
    given = base.join(group_role, group_role.c.group_id == group.c.id).where(
        group_role.c.role_id == role_id, group_role.c.status == "ACTIVE")
    return set(bind.execute(own).scalars()) | set(bind.execute(given).scalars())


def upgrade() -> None:
    op.create_table(
        'approval_task_assignee',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('approval_task_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('assigned_at', app.db.base.UTCDateTime(), nullable=False),
        sa.Column('updated_at', app.db.base.UTCDateTime(), nullable=False),
        sa.CheckConstraint("status IN ('ACTIVE', 'CLOSED')", name='ck_approval_task_assignee_status'),
        sa.ForeignKeyConstraint(['approval_task_id'], ['approval_task.id'],
                                name='fk_approval_task_assignee_approval_task_id_approval_task'),
        sa.PrimaryKeyConstraint('id', name='pk_approval_task_assignee'),
        sa.UniqueConstraint('approval_task_id', 'user_id', name='uq_approval_task_assignee_approval_task_id_user_id'),
    )
    with op.batch_alter_table('approval_task_assignee', schema=None) as batch_op:
        batch_op.create_index('ix_approval_task_assignee_inbox', ['user_id'], unique=False,
                              sqlite_where=sa.text(OPEN), postgresql_where=sa.text(OPEN))

    bind = op.get_bind()
    now = utcnow()
    waiting = bind.execute(
        sa.select(task.c.id, assignment.c.hierarchy_node_id, assignment.c.required_role_id, request.c.id,
                  request.c.requested_by, request.c.maker_id)
        .join(assignment, assignment.c.approval_task_id == task.c.id)
        .join(request, request.c.id == task.c.approval_request_id)
        .where(task.c.status == "PENDING", assignment.c.status == "ACTIVE")).all()
    for task_id, node_id, role_id, request_id, requested_by, maker_id in waiting:
        excluded = {requested_by, maker_id} | set(bind.execute(sa.select(event.c.actor_id).where(
            event.c.approval_request_id == request_id,
            event.c.event_type.in_(["REQUEST_SUBMITTED", "REQUEST_RESUBMITTED"]))).scalars())
        for user_id in _holders(bind, node_id, role_id) - excluded:
            bind.execute(assignee.insert().values(id=uuid7(), approval_task_id=task_id, user_id=user_id,
                                                  status="ACTIVE", assigned_at=now, updated_at=now))


def downgrade() -> None:
    with op.batch_alter_table('approval_task_assignee', schema=None) as batch_op:
        batch_op.drop_index('ix_approval_task_assignee_inbox', sqlite_where=sa.text(OPEN),
                            postgresql_where=sa.text(OPEN))
    op.drop_table('approval_task_assignee')
