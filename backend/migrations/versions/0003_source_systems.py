"""Source systems: hierarchy levels; roots get admins and users groups.

- hierarchy.levels: the node type at each level, root first (DOC_HUB: ROOT -> DOC_REPO).
- user_group.group_type may be ADMINS, USERS, MEMBERS or TEAM; a node has at most one active
  group of each type (teams aside).
- Each root's MEMBERS group is split: its members' ADMIN roles move to a new admins group, their
  VIEWER roles to a new users group (everyone joins it, as VIEWER). The old group is kept, inactive.

Revision ID: 0003
Revises: 0002
Created: 2026-11-16 10:27:18.476491
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db.base
from app.db.base import utcnow, uuid7

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

source_system = sa.table("source_system", sa.column("id", sa.Uuid()), sa.column("code", sa.String()))
hierarchy = sa.table("hierarchy", sa.column("id", sa.Uuid()), sa.column("source_system_id", sa.Uuid()),
                     sa.column("levels", sa.JSON()))
node = sa.table("hierarchy_node", sa.column("id", sa.Uuid()), sa.column("hierarchy_id", sa.Uuid()),
                sa.column("parent_id", sa.Uuid()), sa.column("code", sa.String()), sa.column("name", sa.String()))
role = sa.table("role", sa.column("id", sa.Uuid()), sa.column("code", sa.String()))
group = sa.table("user_group", sa.column("id", sa.Uuid()), sa.column("hierarchy_node_id", sa.Uuid()),
                 sa.column("code", sa.String()), sa.column("name", sa.String()), sa.column("group_type", sa.String()),
                 sa.column("auto_join_role_id", sa.Uuid()), sa.column("status", sa.String()),
                 sa.column("created_at", app.db.base.UTCDateTime()), sa.column("updated_at", app.db.base.UTCDateTime()))
member = sa.table("user_group_member", sa.column("id", sa.Uuid()), sa.column("group_id", sa.Uuid()),
                  sa.column("user_id", sa.Uuid()), sa.column("status", sa.String()), sa.column("added_by_id", sa.Uuid()),
                  sa.column("added_at", app.db.base.UTCDateTime()), sa.column("updated_at", app.db.base.UTCDateTime()))
member_role = sa.table("user_group_member_role", sa.column("id", sa.Uuid()), sa.column("group_member_id", sa.Uuid()),
                       sa.column("role_id", sa.Uuid()), sa.column("status", sa.String()),
                       sa.column("granted_by_id", sa.Uuid()), sa.column("granted_at", app.db.base.UTCDateTime()),
                       sa.column("updated_at", app.db.base.UTCDateTime()))

GROUP_TYPES_BEFORE = "group_type IN ('MEMBERS', 'TEAM')"
GROUP_TYPES_AFTER = "group_type IN ('ADMINS', 'USERS', 'MEMBERS', 'TEAM')"


def _sqlite_foreign_keys(on: bool) -> None:
    """SQLite rebuilds a table to change a CHECK constraint, and dropping the old copy fails while
    other tables reference it with foreign keys on. Off for the rebuild; checked when back on."""
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    bind.exec_driver_sql(f"PRAGMA foreign_keys={'ON' if on else 'OFF'}")
    if on:
        problems = bind.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        if problems:
            raise RuntimeError(f"Foreign key problems after the rebuild: {problems[:5]}")


def upgrade() -> None:
    # Added in place (no table rebuild): NOT NULL with a default, then set per system below.
    op.add_column('hierarchy', sa.Column('levels', sa.JSON(), nullable=False, server_default=sa.text("'[\"ROOT\"]'")))
    _sqlite_foreign_keys(False)
    with op.batch_alter_table('user_group', schema=None) as batch_op:
        batch_op.drop_index('uq_user_group_one_members_group', sqlite_where=sa.text("group_type = 'MEMBERS'"))
        batch_op.drop_constraint('ck_user_group_group_type', type_='check')
        batch_op.create_check_constraint('ck_user_group_group_type', GROUP_TYPES_AFTER)
    _sqlite_foreign_keys(True)

    bind = op.get_bind()
    for h_id, code in bind.execute(sa.select(hierarchy.c.id, source_system.c.code)
                                   .join(source_system, source_system.c.id == hierarchy.c.source_system_id)).all():
        levels = ["ROOT", "DOC_REPO"] if code == "DOC_HUB" else ["ROOT"]
        bind.execute(hierarchy.update().where(hierarchy.c.id == h_id).values(levels=levels))

    roles = dict(bind.execute(sa.select(role.c.code, role.c.id)).all())
    now = utcnow()
    roots = bind.execute(sa.select(node.c.id, node.c.name, source_system.c.code)
                         .join(hierarchy, hierarchy.c.id == node.c.hierarchy_id)
                         .join(source_system, source_system.c.id == hierarchy.c.source_system_id)
                         .where(node.c.parent_id.is_(None))).all()
    for root_id, root_name, system in roots:
        old = bind.execute(sa.select(group.c.id, group.c.auto_join_role_id).where(
            group.c.hierarchy_node_id == root_id, group.c.group_type == "MEMBERS", group.c.status == "ACTIVE")).first()
        new = {}
        for kind, auto in (("ADMINS", None), ("USERS", roles.get("VIEWER"))):
            new[kind] = uuid7()
            bind.execute(group.insert().values(id=new[kind], hierarchy_node_id=root_id, code=f"{system}:{kind}",
                                               name=f"{root_name} {kind.lower()}", group_type=kind,
                                               auto_join_role_id=auto, status="ACTIVE", created_at=now, updated_at=now))
        if old is None:
            continue
        target = {roles.get("ADMIN"): "ADMINS", roles.get("VIEWER"): "USERS"}
        moved: dict[tuple, object] = {}
        for m_id, user_id, m_status, added_by, added_at in bind.execute(sa.select(
                member.c.id, member.c.user_id, member.c.status, member.c.added_by_id, member.c.added_at)
                .where(member.c.group_id == old.id)).all():
            for role_id, r_status, granted_by, granted_at in bind.execute(sa.select(
                    member_role.c.role_id, member_role.c.status, member_role.c.granted_by_id, member_role.c.granted_at)
                    .where(member_role.c.group_member_id == m_id)).all():
                kind = target.get(role_id)
                if kind is None:
                    continue
                key = (kind, user_id)
                if key not in moved:
                    moved[key] = uuid7()
                    bind.execute(member.insert().values(id=moved[key], group_id=new[kind], user_id=user_id,
                                                        status=m_status, added_by_id=added_by, added_at=added_at,
                                                        updated_at=now))
                bind.execute(member_role.insert().values(id=uuid7(), group_member_id=moved[key], role_id=role_id,
                                                         status=r_status, granted_by_id=granted_by,
                                                         granted_at=granted_at, updated_at=now))
        bind.execute(group.update().where(group.c.id == old.id).values(status="INACTIVE", updated_at=now))

    with op.batch_alter_table('user_group', schema=None) as batch_op:
        batch_op.create_index('uq_user_group_one_per_type', ['hierarchy_node_id', 'group_type'], unique=True,
                              sqlite_where=sa.text("group_type <> 'TEAM' AND status = 'ACTIVE'"),
                              postgresql_where=sa.text("group_type <> 'TEAM' AND status = 'ACTIVE'"))


def downgrade() -> None:
    """Merge each root's admins and users groups back into its MEMBERS group."""
    _sqlite_foreign_keys(False)  # before any data change, or SQLite ignores it inside the transaction
    with op.batch_alter_table('user_group', schema=None) as batch_op:
        batch_op.drop_index('uq_user_group_one_per_type', sqlite_where=sa.text("group_type <> 'TEAM' AND status = 'ACTIVE'"),
                            postgresql_where=sa.text("group_type <> 'TEAM' AND status = 'ACTIVE'"))
    bind = op.get_bind()
    now = utcnow()
    for root_id, in bind.execute(sa.select(node.c.id).where(node.c.parent_id.is_(None))).all():
        split = bind.execute(sa.select(group.c.id).where(group.c.hierarchy_node_id == root_id,
                                                         group.c.group_type.in_(["ADMINS", "USERS"]))).scalars().all()
        old = bind.execute(sa.select(group.c.id).where(group.c.hierarchy_node_id == root_id,
                                                       group.c.group_type == "MEMBERS")).scalar()
        if not split:
            continue
        if old is None:
            old = uuid7()
            code = bind.execute(sa.select(node.c.code).where(node.c.id == root_id)).scalar()
            bind.execute(group.insert().values(id=old, hierarchy_node_id=root_id, code=f"{code}:MEMBERS",
                                               name=f"{code} members", group_type="MEMBERS", status="ACTIVE",
                                               created_at=now, updated_at=now))
        bind.execute(group.update().where(group.c.id == old).values(status="ACTIVE", updated_at=now))
        for m_id, user_id in bind.execute(sa.select(member.c.id, member.c.user_id)
                                          .where(member.c.group_id.in_(split))).all():
            target = bind.execute(sa.select(member.c.id).where(member.c.group_id == old,
                                                               member.c.user_id == user_id)).scalar()
            if target is None:
                target = uuid7()
                bind.execute(member.insert().values(id=target, group_id=old, user_id=user_id, status="ACTIVE",
                                                    added_at=now, updated_at=now))
            for role_id, r_status in bind.execute(sa.select(member_role.c.role_id, member_role.c.status)
                                                  .where(member_role.c.group_member_id == m_id)).all():
                exists = bind.execute(sa.select(member_role.c.id).where(member_role.c.group_member_id == target,
                                                                        member_role.c.role_id == role_id)).scalar()
                if exists is None:
                    bind.execute(member_role.insert().values(id=uuid7(), group_member_id=target, role_id=role_id,
                                                             status=r_status, granted_at=now, updated_at=now))
            bind.execute(member_role.delete().where(member_role.c.group_member_id == m_id))
            bind.execute(member.delete().where(member.c.id == m_id))
        bind.execute(group.delete().where(group.c.id.in_(split)))

    with op.batch_alter_table('user_group', schema=None) as batch_op:
        batch_op.drop_constraint('ck_user_group_group_type', type_='check')
        batch_op.create_check_constraint('ck_user_group_group_type', GROUP_TYPES_BEFORE)
        batch_op.create_index('uq_user_group_one_members_group', ['hierarchy_node_id'], unique=True,
                              sqlite_where=sa.text("group_type = 'MEMBERS'"),
                              postgresql_where=sa.text("group_type = 'MEMBERS'"))
    with op.batch_alter_table('hierarchy', schema=None) as batch_op:
        batch_op.drop_column('levels')
    _sqlite_foreign_keys(True)
