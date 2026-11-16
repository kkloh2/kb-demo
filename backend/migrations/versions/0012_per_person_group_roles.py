"""User groups are names; each member holds their own roles in a group. user_group_role goes.

Every active member of a group that gave roles is given those roles as their own in that group
(user_group_member_role), so nobody gains or loses access. Then user_group_role is dropped.
Downgrading brings the table back empty: members keep their own roles, which still count.

Revision ID: 0012
Revises: 0011
Created: 2026-11-16 23:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db.base
from app.db.base import utcnow, uuid7

revision: str = '0012'
down_revision: str | None = '0011'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

U, S, TS = sa.Uuid(), sa.String(), app.db.base.UTCDateTime()
group_role = sa.table("user_group_role", sa.column("group_id", U), sa.column("role_id", U), sa.column("status", S),
                      sa.column("granted_by_id", U))
member = sa.table("user_group_member", sa.column("id", U), sa.column("group_id", U), sa.column("status", S))
member_role = sa.table("user_group_member_role", sa.column("id", U), sa.column("group_member_id", U),
                       sa.column("role_id", U), sa.column("status", S), sa.column("granted_by_id", U),
                       sa.column("granted_at", TS), sa.column("updated_at", TS))


def upgrade() -> None:
    bind = op.get_bind()
    now = utcnow()
    for group_id, role_id, granted_by in bind.execute(sa.select(group_role.c.group_id, group_role.c.role_id,
                                                                group_role.c.granted_by_id)
                                                      .where(group_role.c.status == "ACTIVE")).all():
        for member_id, in bind.execute(sa.select(member.c.id).where(member.c.group_id == group_id,
                                                                    member.c.status == "ACTIVE")).all():
            row = bind.execute(sa.select(member_role.c.id, member_role.c.status).where(
                member_role.c.group_member_id == member_id, member_role.c.role_id == role_id)).first()
            if row is None:
                bind.execute(member_role.insert().values(id=uuid7(), group_member_id=member_id, role_id=role_id,
                                                         status="ACTIVE", granted_by_id=granted_by, granted_at=now,
                                                         updated_at=now))
            elif row.status != "ACTIVE":
                bind.execute(member_role.update().where(member_role.c.id == row.id)
                             .values(status="ACTIVE", granted_at=now, updated_at=now))
    with op.batch_alter_table('user_group_role', schema=None) as batch_op:
        batch_op.drop_index('ix_user_group_role_group_id')
    op.drop_table('user_group_role')


def downgrade() -> None:
    op.create_table(
        'user_group_role',
        sa.Column('id', U, nullable=False), sa.Column('group_id', U, nullable=False), sa.Column('role_id', U, nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False), sa.Column('granted_by_id', U, nullable=True),
        sa.Column('granted_at', TS, nullable=False), sa.Column('updated_at', TS, nullable=False),
        sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name='ck_user_group_role_status'),
        sa.ForeignKeyConstraint(['granted_by_id'], ['app_user.id'], name='fk_user_group_role_granted_by_id_app_user',
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['group_id'], ['user_group.id'], name='fk_user_group_role_group_id_user_group'),
        sa.ForeignKeyConstraint(['role_id'], ['role.id'], name='fk_user_group_role_role_id_role'),
        sa.PrimaryKeyConstraint('id', name='pk_user_group_role'),
        sa.UniqueConstraint('group_id', 'role_id', name='uq_user_group_role_group_id_role_id'),
    )
    with op.batch_alter_table('user_group_role', schema=None) as batch_op:
        batch_op.create_index('ix_user_group_role_group_id', ['group_id'], unique=False)
