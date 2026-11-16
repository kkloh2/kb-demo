"""Audit: its own package (app.audit), a registry of event kinds, and more about each event.

- audit_action: the kinds of event each area registers (code, source system, category, label).
- audit_event: + actor_lan_id, source_system, category, node_path, request_id, client_ip; action now
  references audit_action; indexes for per-area, per-node, per-actor and per-target views.

Existing events are relabelled where the name changed (GROUP_UPDATED -> GROUP_RENAMED, NODE_RENAMED ->
NODE_UPDATED, MEMBER_ROLES_SET -> PLATFORM_ADMIN_GRANTED / _REVOKED, ROOT_GROUP_ROLES_SET or
MEMBER_GROUPS_SET), and given their source system (the node's, else the action's), category, node
path and actor's LAN ID. An action this list doesn't know is kept, registered as itself.

Revision ID: 0013
Revises: 0012
Created: 2026-11-17 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = '0013'
down_revision: str | None = '0012'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIONS = [  # (code, source system, category, label, description): a copy, the code's list may change later
    ('APPROVAL_CANCELLED', 'APPROVALS', 'approval', 'Approval cancelled', 'Withdrawn, e.g. the document or repository was deleted.'),
    ('APPROVAL_COMPLETED', 'APPROVALS', 'approval', 'Approval completed', 'The request ended approved or rejected.'),
    ('APPROVAL_DECIDED', 'APPROVALS', 'approval', 'Decision recorded', 'A reviewer approved, rejected or requested changes.'),
    ('APPROVAL_REFUSED', 'APPROVALS', 'approval', 'Submission refused', 'The workflow refused it, e.g. not a maker in its group.'),
    ('APPROVAL_SUBMITTED', 'APPROVALS', 'approval', 'Sent for approval', 'Submitted, or resubmitted after changes (a new round).'),
    ('DEFAULT_GRANT_ADDED', 'PLATFORM', 'access', 'Team given default access', ''),
    ('DEFAULT_GRANT_REMOVED', 'PLATFORM', 'access', "Team's default access removed", ''),
    ('DOCUMENTS_DELETED', 'DOC_HUB', 'content', 'Documents deleted', ''),
    ('DOCUMENTS_UPLOADED', 'DOC_HUB', 'content', 'Documents uploaded', ''),
    ('DOCUMENT_DOWNLOADED', 'DOC_HUB', 'content', 'Document downloaded', ''),
    ('DOCUMENT_METADATA_SET', 'DOC_HUB', 'content', 'Document metadata changed', ''),
    ('GROUP_CREATED', 'PLATFORM', 'access', 'User group created', ''),
    ('GROUP_DELETED', 'PLATFORM', 'access', 'User group deleted', ''),
    ('GROUP_RENAMED', 'PLATFORM', 'access', 'User group renamed', ''),
    ('HIERARCHY_CREATED', 'PLATFORM', 'configuration', 'Hierarchy created', ''),
    ('MEMBER_GROUPS_SET', 'PLATFORM', 'access', "Someone's user groups and roles changed", ''),
    ('NODE_CREATED', 'PLATFORM', 'configuration', 'Created', ''),
    ('NODE_DELETED', 'PLATFORM', 'configuration', 'Deleted', ''),
    ('NODE_RESTORED', 'PLATFORM', 'configuration', 'Restored', ''),
    ('NODE_UPDATED', 'PLATFORM', 'configuration', 'Renamed or edited', ''),
    ('OWNERSHIP_TRANSFERRED', 'PLATFORM', 'access', 'Ownership handed over', ''),
    ('OWNER_REASSIGNED', 'PLATFORM', 'access', 'Owner reassigned by a platform admin', ''),
    ('PLATFORM_ADMIN_GRANTED', 'PLATFORM', 'access', 'Made a platform admin', ''),
    ('PLATFORM_ADMIN_REVOKED', 'PLATFORM', 'access', 'No longer a platform admin', ''),
    ('REPOSITORY_METADATA_SET', 'DOC_HUB', 'configuration', 'Default metadata changed', ''),
    ('REPO_WORKFLOW_SET', 'WORKFLOWS', 'configuration', 'Workflow changed', 'A node (e.g. a repository) switched workflow.'),
    ('ROOT_GROUP_ROLES_SET', 'PLATFORM', 'access', "Roles in a source system's admins or users changed", ''),
    ('SESSIONS_ENDED', 'PLATFORM', 'security', 'Sessions ended', "Someone's sessions were ended, e.g. their access changed."),
    ('SIGN_IN', 'PLATFORM', 'security', 'Signed in', ''),
    ('SIGN_IN_FAILED', 'PLATFORM', 'security', 'Sign-in failed', 'Wrong password, unknown LAN ID, or refused by the directory.'),
    ('SIGN_IN_REFUSED', 'PLATFORM', 'security', 'Sign-in refused', 'The password was right but Data Hub refused it (e.g. access switched off).'),
    ('SOURCE_SYSTEM_CREATED', 'PLATFORM', 'configuration', 'Source system created', ''),
    ('TEAM_MEMBERS_SET', 'PLATFORM', 'access', 'Team members changed', ''),
    ('USER_ACTIVATED', 'PLATFORM', 'access', 'Access switched on', ''),
    ('USER_ADDED', 'PLATFORM', 'access', 'User added', 'A platform admin added someone by LAN ID.'),
    ('USER_DEACTIVATED', 'PLATFORM', 'access', 'Access switched off', ''),
    ('USER_UPDATED', 'PLATFORM', 'access', 'User details changed', 'Name, email, title or department changed.'),
    ('WORKFLOW_CREATED', 'WORKFLOWS', 'configuration', 'Workflow created', ''),
    ('WORKFLOW_DEFAULT_CREATED', 'WORKFLOWS', 'configuration', 'Default workflow set up', "A feature's shipped workflow was created automatically."),
    ('WORKFLOW_PUBLISHED', 'WORKFLOWS', 'configuration', 'Workflow version published', ''),
]

RENAMED = {"GROUP_UPDATED": "GROUP_RENAMED", "NODE_RENAMED": "NODE_UPDATED"}
U, S = sa.Uuid(), sa.String()
action_t = sa.table("audit_action", sa.column("code", S), sa.column("source_system", S), sa.column("category", S),
                    sa.column("label", S), sa.column("description", S))
event = sa.table("audit_event", sa.column("id", U), sa.column("actor_id", U), sa.column("action", S),
                 sa.column("hierarchy_node_id", U), sa.column("details", sa.JSON()), sa.column("actor_lan_id", S),
                 sa.column("source_system", S), sa.column("category", S), sa.column("node_path", S))
node = sa.table("hierarchy_node", sa.column("id", U), sa.column("hierarchy_id", U), sa.column("path", S),
                sa.column("parent_id", U))
hierarchy = sa.table("hierarchy", sa.column("id", U), sa.column("source_system_id", U))
system = sa.table("source_system", sa.column("id", U), sa.column("code", S))
user = sa.table("app_user", sa.column("id", U), sa.column("lan_id", S))


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
    op.create_table(
        'audit_action',
        sa.Column('code', sa.String(length=64), nullable=False),
        sa.Column('source_system', sa.String(length=32), nullable=False),
        sa.Column('category', sa.String(length=16), nullable=False),
        sa.Column('label', sa.String(length=128), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint('code', name='pk_audit_action'),
    )
    bind = op.get_bind()
    known = {}
    for code, source, category, label, description in ACTIONS:
        bind.execute(action_t.insert().values(code=code, source_system=source, category=category, label=label,
                                              description=description))
        known[code] = (source, category)

    _sqlite_foreign_keys(False)
    with op.batch_alter_table('audit_event', schema=None) as batch_op:
        for name, length in (("actor_lan_id", 64), ("source_system", 32), ("category", 16), ("node_path", 1024),
                             ("request_id", 36), ("client_ip", 45)):
            batch_op.add_column(sa.Column(name, sa.String(length=length), nullable=True))

    platform_root = bind.execute(sa.select(node.c.id).join(hierarchy, hierarchy.c.id == node.c.hierarchy_id)
                                 .join(system, system.c.id == hierarchy.c.source_system_id)
                                 .where(system.c.code == "PLATFORM", node.c.parent_id.is_(None))).scalar()
    rows = bind.execute(sa.select(event.c.id, event.c.actor_id, event.c.action, event.c.hierarchy_node_id,
                                  event.c.details)).all()
    for event_id, actor_id, action, node_id, details in rows:
        details = details or {}
        found = None
        if node_id is not None:
            found = bind.execute(sa.select(node.c.path, node.c.parent_id, system.c.code)
                                 .join(hierarchy, hierarchy.c.id == node.c.hierarchy_id)
                                 .join(system, system.c.id == hierarchy.c.source_system_id)
                                 .where(node.c.id == node_id)).first()
        code = RENAMED.get(action, action)
        if action == "MEMBER_ROLES_SET":
            before, after = details.get("before") or [], details.get("after") or []
            if node_id == platform_root and ("ADMIN" in before) != ("ADMIN" in after):
                code = "PLATFORM_ADMIN_GRANTED" if "ADMIN" in after else "PLATFORM_ADMIN_REVOKED"
            elif found is not None and found.parent_id is None:
                code = "ROOT_GROUP_ROLES_SET"
            else:
                code = "MEMBER_GROUPS_SET"
        if code not in known:  # kept as it is
            bind.execute(action_t.insert().values(code=code, source_system="PLATFORM", category="configuration",
                                                  label=code.replace("_", " ").capitalize(), description=""))
            known[code] = ("PLATFORM", "configuration")
        source, category = known[code]
        lan = bind.execute(sa.select(user.c.lan_id).where(user.c.id == actor_id)).scalar() if actor_id else None
        bind.execute(event.update().where(event.c.id == event_id).values(
            action=code, source_system=found.code if found else source, category=category,
            node_path=found.path if found else None, actor_lan_id=lan))

    with op.batch_alter_table('audit_event', schema=None) as batch_op:
        batch_op.alter_column('source_system', existing_type=sa.String(length=32), nullable=False)
        batch_op.alter_column('category', existing_type=sa.String(length=16), nullable=False)
        batch_op.alter_column('details', existing_type=sa.JSON(), type_=sa.JSON().with_variant(JSONB(), "postgresql"),
                              existing_nullable=False)
        batch_op.create_foreign_key('fk_audit_event_action_audit_action', 'audit_action', ['action'], ['code'])
        batch_op.create_index('ix_audit_event_source_system_created_at', ['source_system', 'created_at'], unique=False)
        batch_op.create_index('ix_audit_event_node_created_at', ['hierarchy_node_id', 'created_at'], unique=False)
        batch_op.create_index('ix_audit_event_actor_created_at', ['actor_id', 'created_at'], unique=False)
        batch_op.create_index('ix_audit_event_target', ['target_type', 'target_id'], unique=False)
    _sqlite_foreign_keys(True)


def downgrade() -> None:
    _sqlite_foreign_keys(False)
    with op.batch_alter_table('audit_event', schema=None) as batch_op:
        batch_op.drop_index('ix_audit_event_target')
        batch_op.drop_index('ix_audit_event_actor_created_at')
        batch_op.drop_index('ix_audit_event_node_created_at')
        batch_op.drop_index('ix_audit_event_source_system_created_at')
        batch_op.drop_constraint('fk_audit_event_action_audit_action', type_='foreignkey')
        for name in ("client_ip", "request_id", "node_path", "category", "source_system", "actor_lan_id"):
            batch_op.drop_column(name)
    bind = op.get_bind()
    for new, old in (("GROUP_RENAMED", "GROUP_UPDATED"), ("NODE_UPDATED", "NODE_RENAMED"),
                     ("PLATFORM_ADMIN_GRANTED", "MEMBER_ROLES_SET"), ("PLATFORM_ADMIN_REVOKED", "MEMBER_ROLES_SET"),
                     ("ROOT_GROUP_ROLES_SET", "MEMBER_ROLES_SET")):
        bind.execute(event.update().where(event.c.action == new).values(action=old))
    op.drop_table('audit_action')
    _sqlite_foreign_keys(True)
