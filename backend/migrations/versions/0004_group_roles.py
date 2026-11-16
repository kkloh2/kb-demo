"""Repository user groups with roles.

- user_group_role: roles a group gives every active member.
- user_group.group_type may also be CUSTOM: a repository's own groups (any number per node).
- Each repository's MEMBERS group is renamed "Members" and gives VIEWER. Its members' own ADMIN,
  MAKER and CHECKER roles move to new groups ("Admins", "Makers", "Checkers") that give them;
  their own VIEWER roles are dropped (Members gives it). Owners keep OWNER as their own role.

Revision ID: 0004
Revises: 0003
Created: 2026-11-16 15:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db.base
from app.db.base import utcnow, uuid7

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

node = sa.table("hierarchy_node", sa.column("id", sa.Uuid()), sa.column("parent_id", sa.Uuid()),
                sa.column("name", sa.String()))
role = sa.table("role", sa.column("id", sa.Uuid()), sa.column("code", sa.String()))
group = sa.table("user_group", sa.column("id", sa.Uuid()), sa.column("hierarchy_node_id", sa.Uuid()),
                 sa.column("code", sa.String()), sa.column("name", sa.String()), sa.column("group_type", sa.String()),
                 sa.column("status", sa.String()),
                 sa.column("created_at", app.db.base.UTCDateTime()), sa.column("updated_at", app.db.base.UTCDateTime()))
member = sa.table("user_group_member", sa.column("id", sa.Uuid()), sa.column("group_id", sa.Uuid()),
                  sa.column("user_id", sa.Uuid()), sa.column("status", sa.String()), sa.column("added_by_id", sa.Uuid()),
                  sa.column("added_at", app.db.base.UTCDateTime()), sa.column("updated_at", app.db.base.UTCDateTime()))
member_role = sa.table("user_group_member_role", sa.column("id", sa.Uuid()), sa.column("group_member_id", sa.Uuid()),
                       sa.column("role_id", sa.Uuid()), sa.column("status", sa.String()),
                       sa.column("granted_by_id", sa.Uuid()), sa.column("granted_at", app.db.base.UTCDateTime()),
                       sa.column("updated_at", app.db.base.UTCDateTime()))
group_role = sa.table("user_group_role", sa.column("id", sa.Uuid()), sa.column("group_id", sa.Uuid()),
                      sa.column("role_id", sa.Uuid()), sa.column("status", sa.String()),
                      sa.column("granted_by_id", sa.Uuid()), sa.column("granted_at", app.db.base.UTCDateTime()),
                      sa.column("updated_at", app.db.base.UTCDateTime()))

TYPES_BEFORE = "group_type IN ('ADMINS', 'USERS', 'MEMBERS', 'TEAM')"
TYPES_AFTER = "group_type IN ('ADMINS', 'USERS', 'MEMBERS', 'CUSTOM', 'TEAM')"
ONE_BEFORE = "group_type <> 'TEAM' AND status = 'ACTIVE'"
ONE_AFTER = "group_type NOT IN ('TEAM', 'CUSTOM') AND status = 'ACTIVE'"
MOVED = {"ADMIN": "Admins", "MAKER": "Makers", "CHECKER": "Checkers"}  # own role -> the group that gives it


def _sqlite_foreign_keys(on: bool) -> None:
    """Off for the user_group rebuild (other tables reference it); checked when back on."""
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    bind.exec_driver_sql(f"PRAGMA foreign_keys={'ON' if on else 'OFF'}")
    if on:
        problems = bind.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        if problems:
            raise RuntimeError(f"Foreign key problems after the rebuild: {problems[:5]}")


def _group_types(types: str, one: str, old_one: str) -> None:
    with op.batch_alter_table('user_group', schema=None) as batch_op:
        batch_op.drop_index('uq_user_group_one_per_type', sqlite_where=sa.text(old_one),
                            postgresql_where=sa.text(old_one))
        batch_op.drop_constraint('ck_user_group_group_type', type_='check')
        batch_op.create_check_constraint('ck_user_group_group_type', types)
        batch_op.create_index('uq_user_group_one_per_type', ['hierarchy_node_id', 'group_type'], unique=True,
                              sqlite_where=sa.text(one), postgresql_where=sa.text(one))


def upgrade() -> None:
    op.create_table(
        'user_group_role',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('group_id', sa.Uuid(), nullable=False),
        sa.Column('role_id', sa.Uuid(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('granted_by_id', sa.Uuid(), nullable=True),
        sa.Column('granted_at', app.db.base.UTCDateTime(), nullable=False),
        sa.Column('updated_at', app.db.base.UTCDateTime(), nullable=False),
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

    _sqlite_foreign_keys(False)  # before any data change, or SQLite ignores it inside the transaction
    _group_types(TYPES_AFTER, ONE_AFTER, ONE_BEFORE)

    bind = op.get_bind()
    roles = dict(bind.execute(sa.select(role.c.code, role.c.id)).all())
    codes = {v: k for k, v in roles.items()}
    now = utcnow()
    repo_groups = bind.execute(
        sa.select(group.c.id, group.c.hierarchy_node_id, group.c.code)
        .join(node, node.c.id == group.c.hierarchy_node_id)
        .where(group.c.group_type == "MEMBERS", group.c.status == "ACTIVE", node.c.parent_id.is_not(None))).all()
    for g_id, node_id, g_code in repo_groups:
        bind.execute(group.update().where(group.c.id == g_id).values(name="Members", updated_at=now))
        bind.execute(group_role.insert().values(id=uuid7(), group_id=g_id, role_id=roles["VIEWER"], status="ACTIVE",
                                                granted_at=now, updated_at=now))
        made: dict[str, object] = {}
        for m_id, user_id, added_by, added_at in bind.execute(
                sa.select(member.c.id, member.c.user_id, member.c.added_by_id, member.c.added_at)
                .where(member.c.group_id == g_id, member.c.status == "ACTIVE")).all():
            for r_id, role_id in bind.execute(sa.select(member_role.c.id, member_role.c.role_id).where(
                    member_role.c.group_member_id == m_id, member_role.c.status == "ACTIVE")).all():
                code = codes.get(role_id)
                if code == "OWNER":
                    continue
                if code in MOVED:
                    if code not in made:
                        made[code] = uuid7()
                        prefix = g_code.removesuffix("MEMBERS")
                        bind.execute(group.insert().values(
                            id=made[code], hierarchy_node_id=node_id, code=f"{prefix}{made[code]}", name=MOVED[code],
                            group_type="CUSTOM", status="ACTIVE", created_at=now, updated_at=now))
                        bind.execute(group_role.insert().values(id=uuid7(), group_id=made[code], role_id=role_id,
                                                                status="ACTIVE", granted_at=now, updated_at=now))
                    bind.execute(member.insert().values(id=uuid7(), group_id=made[code], user_id=user_id,
                                                        status="ACTIVE", added_by_id=added_by, added_at=added_at,
                                                        updated_at=now))
                bind.execute(member_role.update().where(member_role.c.id == r_id)
                             .values(status="INACTIVE", updated_at=now))
    _sqlite_foreign_keys(True)


def downgrade() -> None:
    """Back to own roles: every member of a repository's groups holds the group's roles as their
    own in its MEMBERS group; the other groups are removed."""
    _sqlite_foreign_keys(False)
    bind = op.get_bind()
    now = utcnow()
    repo_nodes = bind.execute(sa.select(node.c.id, node.c.name).where(node.c.parent_id.is_not(None))).all()
    for node_id, name in repo_nodes:
        home = bind.execute(sa.select(group.c.id).where(group.c.hierarchy_node_id == node_id,
                                                        group.c.group_type == "MEMBERS",
                                                        group.c.status == "ACTIVE")).scalar()
        if home is None:
            continue
        groups = bind.execute(sa.select(group.c.id).where(group.c.hierarchy_node_id == node_id,
                                                          group.c.group_type.in_(["MEMBERS", "CUSTOM"]))).scalars().all()
        for g_id in groups:
            given = bind.execute(sa.select(group_role.c.role_id).where(group_role.c.group_id == g_id,
                                                                       group_role.c.status == "ACTIVE")).scalars().all()
            for user_id, in bind.execute(sa.select(member.c.user_id).where(member.c.group_id == g_id,
                                                                           member.c.status == "ACTIVE")).all():
                target = bind.execute(sa.select(member.c.id).where(member.c.group_id == home,
                                                                   member.c.user_id == user_id)).scalar()
                if target is None:
                    target = uuid7()
                    bind.execute(member.insert().values(id=target, group_id=home, user_id=user_id, status="ACTIVE",
                                                        added_at=now, updated_at=now))
                else:
                    bind.execute(member.update().where(member.c.id == target).values(status="ACTIVE", updated_at=now))
                for role_id in given:
                    row = bind.execute(sa.select(member_role.c.id).where(member_role.c.group_member_id == target,
                                                                         member_role.c.role_id == role_id)).scalar()
                    if row is None:
                        bind.execute(member_role.insert().values(id=uuid7(), group_member_id=target, role_id=role_id,
                                                                 status="ACTIVE", granted_at=now, updated_at=now))
                    else:
                        bind.execute(member_role.update().where(member_role.c.id == row)
                                     .values(status="ACTIVE", updated_at=now))
        custom = bind.execute(sa.select(group.c.id).where(group.c.hierarchy_node_id == node_id,
                                                          group.c.group_type == "CUSTOM")).scalars().all()
        if custom:
            ids = bind.execute(sa.select(member.c.id).where(member.c.group_id.in_(custom))).scalars().all()
            if ids:
                bind.execute(member_role.delete().where(member_role.c.group_member_id.in_(ids)))
            bind.execute(member.delete().where(member.c.group_id.in_(custom)))
            bind.execute(group.delete().where(group.c.id.in_(custom)))
        bind.execute(group.update().where(group.c.id == home).values(name=f"{name} members", updated_at=now))
    op.drop_table('user_group_role')
    _group_types(TYPES_BEFORE, ONE_BEFORE, ONE_AFTER)
    _sqlite_foreign_keys(True)
