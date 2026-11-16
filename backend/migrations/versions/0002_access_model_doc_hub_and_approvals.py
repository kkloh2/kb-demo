"""Access model, Doc Hub and Approvals (CAMS, first version).

Replaces users/departments/roles with source systems, their trees (hierarchy_node), groups,
members' roles and permissions; document repositories become DOC_REPO nodes with doc_repo,
document, metadata_field and metadata_value; approvals get their own tables. Ids are UUIDs.

The old tables' rows are not carried over (decided 2026-11-13: start clean). Back up the database
before upgrading. Downgrading recreates the old tables empty.

Revision ID: 0002
Revises: 0001
Created: 2026-11-13 17:04:22.816529
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db.base

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('app_user',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('lan_id', sa.String(length=64), nullable=False),
    sa.Column('email', sa.String(length=256), nullable=False),
    sa.Column('display_name', sa.String(length=128), nullable=False),
    sa.Column('title', sa.String(length=128), nullable=False),
    sa.Column('directory_department', sa.String(length=128), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('last_login_at', app.db.base.UTCDateTime(), nullable=True),
    sa.Column('created_at', app.db.base.UTCDateTime(), nullable=False),
    sa.Column('updated_at', app.db.base.UTCDateTime(), nullable=False),
    sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name='ck_app_user_status'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_app_user')),
    sa.UniqueConstraint('lan_id', name=op.f('uq_app_user_lan_id'))
    )
    op.create_table('approval_type',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('source_system_id', sa.Uuid(), nullable=False),
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_approval_type')),
    sa.UniqueConstraint('source_system_id', 'code', name='uq_approval_type_source_system_id_code')
    )
    op.create_table('permission',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('description', sa.String(length=256), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_permission')),
    sa.UniqueConstraint('code', name=op.f('uq_permission_code'))
    )
    op.create_table('resource',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('source_system_id', sa.Uuid(), nullable=False),
    sa.Column('resource_type', sa.String(length=64), nullable=False),
    sa.Column('resource_id', sa.String(length=255), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', app.db.base.UTCDateTime(), nullable=False),
    sa.Column('updated_at', app.db.base.UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_resource')),
    sa.UniqueConstraint('source_system_id', 'resource_type', 'resource_id', name='uq_resource_source_system_id_resource_type_resource_id')
    )
    op.create_table('role',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('description', sa.String(length=256), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_role')),
    sa.UniqueConstraint('code', name=op.f('uq_role_code'))
    )
    op.create_table('source_system',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', app.db.base.UTCDateTime(), nullable=False),
    sa.Column('updated_at', app.db.base.UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_source_system')),
    sa.UniqueConstraint('code', name=op.f('uq_source_system_code'))
    )
    op.create_table('approval_request',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('source_system_id', sa.Uuid(), nullable=False),
    sa.Column('approval_type_id', sa.Uuid(), nullable=False),
    sa.Column('resource_pk', sa.Uuid(), nullable=False),
    sa.Column('external_reference_id', sa.String(length=255), nullable=False),
    sa.Column('subject_type', sa.String(length=64), nullable=False),
    sa.Column('subject_id', sa.String(length=64), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('current_round', sa.Integer(), nullable=False),
    sa.Column('last_event_sequence', sa.BigInteger(), nullable=False),
    sa.Column('requested_by', sa.Uuid(), nullable=False),
    sa.Column('submitted_at', app.db.base.UTCDateTime(), nullable=False),
    sa.Column('completed_at', app.db.base.UTCDateTime(), nullable=True),
    sa.Column('updated_at', app.db.base.UTCDateTime(), nullable=False),
    sa.CheckConstraint("status IN ('PENDING', 'CHANGES_REQUESTED', 'APPROVED', 'REJECTED', 'CANCELLED')", name='ck_approval_request_status'),
    sa.ForeignKeyConstraint(['approval_type_id'], ['approval_type.id'], name=op.f('fk_approval_request_approval_type_id_approval_type')),
    sa.ForeignKeyConstraint(['resource_pk'], ['resource.id'], name=op.f('fk_approval_request_resource_pk_resource')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_approval_request')),
    sa.UniqueConstraint('source_system_id', 'external_reference_id', name='uq_approval_request_source_system_id_external_reference_id')
    )
    with op.batch_alter_table('approval_request', schema=None) as batch_op:
        batch_op.create_index('ix_approval_request_resource_status', ['resource_pk', 'status'], unique=False)
        batch_op.create_index('ix_approval_request_subject', ['subject_type', 'subject_id'], unique=False)

    op.create_table('audit_event',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('target_type', sa.String(length=32), nullable=False),
    sa.Column('target_id', sa.String(length=64), nullable=False),
    sa.Column('hierarchy_node_id', sa.Uuid(), nullable=True),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.Column('created_at', app.db.base.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['app_user.id'], name=op.f('fk_audit_event_actor_id_app_user'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_event'))
    )
    with op.batch_alter_table('audit_event', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_event_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_event_hierarchy_node_id'), ['hierarchy_node_id'], unique=False)

    op.create_table('hierarchy',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('source_system_id', sa.Uuid(), nullable=False),
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', app.db.base.UTCDateTime(), nullable=False),
    sa.Column('updated_at', app.db.base.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['source_system_id'], ['source_system.id'], name=op.f('fk_hierarchy_source_system_id_source_system')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_hierarchy')),
    sa.UniqueConstraint('code', name=op.f('uq_hierarchy_code')),
    sa.UniqueConstraint('source_system_id', name=op.f('uq_hierarchy_source_system_id'))
    )
    op.create_table('resource_hierarchy_binding',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('resource_pk', sa.Uuid(), nullable=False),
    sa.Column('hierarchy_node_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', app.db.base.UTCDateTime(), nullable=False),
    sa.Column('updated_at', app.db.base.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['resource_pk'], ['resource.id'], name=op.f('fk_resource_hierarchy_binding_resource_pk_resource')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_resource_hierarchy_binding'))
    )
    with op.batch_alter_table('resource_hierarchy_binding', schema=None) as batch_op:
        batch_op.create_index('uq_resource_hierarchy_binding_one_active', ['resource_pk'], unique=True, sqlite_where=sa.text("status = 'ACTIVE'"), postgresql_where=sa.text("status = 'ACTIVE'"))

    op.create_table('role_permission',
    sa.Column('role_id', sa.Uuid(), nullable=False),
    sa.Column('permission_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['permission_id'], ['permission.id'], name=op.f('fk_role_permission_permission_id_permission'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['role_id'], ['role.id'], name=op.f('fk_role_permission_role_id_role'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('role_id', 'permission_id', name=op.f('pk_role_permission'))
    )
    op.create_table('approval_task',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('approval_request_id', sa.Uuid(), nullable=False),
    sa.Column('round', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('subject_snapshot', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('completion_rule', sa.String(length=8), nullable=False),
    sa.Column('outcome', sa.String(length=24), nullable=True),
    sa.Column('created_at', app.db.base.UTCDateTime(), nullable=False),
    sa.Column('completed_at', app.db.base.UTCDateTime(), nullable=True),
    sa.CheckConstraint("status IN ('PENDING', 'COMPLETED', 'CANCELLED')", name='ck_approval_task_status'),
    sa.ForeignKeyConstraint(['approval_request_id'], ['approval_request.id'], name=op.f('fk_approval_task_approval_request_id_approval_request')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_approval_task')),
    sa.UniqueConstraint('approval_request_id', 'round', name='uq_approval_task_approval_request_id_round')
    )
    op.create_table('hierarchy_node',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('hierarchy_id', sa.Uuid(), nullable=False),
    sa.Column('parent_id', sa.Uuid(), nullable=True),
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('path', sa.String(length=1024), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('node_type', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_by_id', sa.Uuid(), nullable=True),
    sa.Column('deleted_by_id', sa.Uuid(), nullable=True),
    sa.Column('deleted_at', app.db.base.UTCDateTime(), nullable=True),
    sa.Column('created_at', app.db.base.UTCDateTime(), nullable=False),
    sa.Column('updated_at', app.db.base.UTCDateTime(), nullable=False),
    sa.CheckConstraint("status IN ('ACTIVE', 'DELETED')", name='ck_hierarchy_node_status'),
    sa.CheckConstraint('parent_id IS NULL OR parent_id <> id', name='ck_hierarchy_node_not_own_parent'),
    sa.ForeignKeyConstraint(['created_by_id'], ['app_user.id'], name=op.f('fk_hierarchy_node_created_by_id_app_user'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['deleted_by_id'], ['app_user.id'], name=op.f('fk_hierarchy_node_deleted_by_id_app_user'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['hierarchy_id'], ['hierarchy.id'], name=op.f('fk_hierarchy_node_hierarchy_id_hierarchy')),
    sa.ForeignKeyConstraint(['parent_id'], ['hierarchy_node.id'], name=op.f('fk_hierarchy_node_parent_id_hierarchy_node')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_hierarchy_node')),
    sa.UniqueConstraint('hierarchy_id', 'code', name='uq_hierarchy_node_hierarchy_id_code'),
    sa.UniqueConstraint('path', name=op.f('uq_hierarchy_node_path'))
    )
    with op.batch_alter_table('hierarchy_node', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_hierarchy_node_parent_id'), ['parent_id'], unique=False)
        batch_op.create_index('uq_hierarchy_node_one_root', ['hierarchy_id'], unique=True, sqlite_where=sa.text('parent_id IS NULL'), postgresql_where=sa.text('parent_id IS NULL'))

    op.create_table('approval_decision',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('approval_task_id', sa.Uuid(), nullable=False),
    sa.Column('decided_by', sa.Uuid(), nullable=False),
    sa.Column('decision', sa.String(length=24), nullable=False),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('decided_at', app.db.base.UTCDateTime(), nullable=False),
    sa.CheckConstraint("decision = 'APPROVED' OR (comment IS NOT NULL AND trim(comment) <> '')", name='ck_approval_decision_comment_required'),
    sa.CheckConstraint("decision IN ('APPROVED', 'REJECTED', 'CHANGES_REQUESTED')", name='ck_approval_decision_decision'),
    sa.ForeignKeyConstraint(['approval_task_id'], ['approval_task.id'], name=op.f('fk_approval_decision_approval_task_id_approval_task')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_approval_decision')),
    sa.UniqueConstraint('approval_task_id', 'decided_by', name='uq_approval_decision_approval_task_id_decided_by')
    )
    op.create_table('approval_event',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('approval_request_id', sa.Uuid(), nullable=False),
    sa.Column('approval_task_id', sa.Uuid(), nullable=True),
    sa.Column('event_type', sa.String(length=64), nullable=False),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('event_data', sa.JSON(), nullable=False),
    sa.Column('event_sequence', sa.BigInteger(), nullable=False),
    sa.Column('created_at', app.db.base.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['approval_request_id'], ['approval_request.id'], name=op.f('fk_approval_event_approval_request_id_approval_request')),
    sa.ForeignKeyConstraint(['approval_task_id'], ['approval_task.id'], name=op.f('fk_approval_event_approval_task_id_approval_task')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_approval_event')),
    sa.UniqueConstraint('approval_request_id', 'event_sequence', name='uq_approval_event_approval_request_id_event_sequence')
    )
    op.create_table('approval_task_assignment',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('approval_task_id', sa.Uuid(), nullable=False),
    sa.Column('group_id', sa.Uuid(), nullable=False),
    sa.Column('hierarchy_node_id', sa.Uuid(), nullable=False),
    sa.Column('required_role_id', sa.Uuid(), nullable=False),
    sa.Column('assignment_strategy', sa.String(length=32), nullable=False),
    sa.Column('assigned_at', app.db.base.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['approval_task_id'], ['approval_task.id'], name=op.f('fk_approval_task_assignment_approval_task_id_approval_task')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_approval_task_assignment')),
    sa.UniqueConstraint('approval_task_id', name=op.f('uq_approval_task_assignment_approval_task_id'))
    )
    with op.batch_alter_table('approval_task_assignment', schema=None) as batch_op:
        batch_op.create_index('ix_approval_task_assignment_inbox', ['group_id', 'required_role_id'], unique=False)

    op.create_table('doc_repo',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('hierarchy_node_id', sa.Uuid(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('created_by_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', app.db.base.UTCDateTime(), nullable=False),
    sa.Column('updated_at', app.db.base.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by_id'], ['app_user.id'], name=op.f('fk_doc_repo_created_by_id_app_user'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['hierarchy_node_id'], ['hierarchy_node.id'], name=op.f('fk_doc_repo_hierarchy_node_id_hierarchy_node')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_doc_repo')),
    sa.UniqueConstraint('hierarchy_node_id', name=op.f('uq_doc_repo_hierarchy_node_id'))
    )
    op.create_table('user_group',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('hierarchy_node_id', sa.Uuid(), nullable=False),
    sa.Column('code', sa.String(length=128), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('group_type', sa.String(length=16), nullable=False),
    sa.Column('auto_join_role_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', app.db.base.UTCDateTime(), nullable=False),
    sa.Column('updated_at', app.db.base.UTCDateTime(), nullable=False),
    sa.CheckConstraint("group_type IN ('MEMBERS', 'TEAM')", name='ck_user_group_group_type'),
    sa.ForeignKeyConstraint(['auto_join_role_id'], ['role.id'], name=op.f('fk_user_group_auto_join_role_id_role')),
    sa.ForeignKeyConstraint(['hierarchy_node_id'], ['hierarchy_node.id'], name=op.f('fk_user_group_hierarchy_node_id_hierarchy_node')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_group')),
    sa.UniqueConstraint('code', name=op.f('uq_user_group_code'))
    )
    with op.batch_alter_table('user_group', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_group_hierarchy_node_id'), ['hierarchy_node_id'], unique=False)
        batch_op.create_index('uq_user_group_one_members_group', ['hierarchy_node_id'], unique=True, sqlite_where=sa.text("group_type = 'MEMBERS'"), postgresql_where=sa.text("group_type = 'MEMBERS'"))

    op.create_table('default_grant',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('parent_node_id', sa.Uuid(), nullable=False),
    sa.Column('child_node_type', sa.String(length=32), nullable=False),
    sa.Column('team_group_id', sa.Uuid(), nullable=False),
    sa.Column('role_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_by_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', app.db.base.UTCDateTime(), nullable=False),
    sa.Column('updated_at', app.db.base.UTCDateTime(), nullable=False),
    sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name='ck_default_grant_status'),
    sa.ForeignKeyConstraint(['created_by_id'], ['app_user.id'], name=op.f('fk_default_grant_created_by_id_app_user'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['parent_node_id'], ['hierarchy_node.id'], name=op.f('fk_default_grant_parent_node_id_hierarchy_node')),
    sa.ForeignKeyConstraint(['role_id'], ['role.id'], name=op.f('fk_default_grant_role_id_role')),
    sa.ForeignKeyConstraint(['team_group_id'], ['user_group.id'], name=op.f('fk_default_grant_team_group_id_user_group')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_default_grant')),
    sa.UniqueConstraint('parent_node_id', 'child_node_type', 'team_group_id', 'role_id', name='uq_default_grant_parent_node_id_child_node_type_team_group_id_role_id')
    )
    op.create_table('document',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('doc_repo_id', sa.Uuid(), nullable=False),
    sa.Column('folder', sa.String(length=512), nullable=False),
    sa.Column('filename', sa.String(length=256), nullable=False),
    sa.Column('content_type', sa.String(length=128), nullable=True),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('storage_path', sa.String(length=512), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('upload_batch', sa.String(length=36), nullable=True),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('maker_id', sa.Uuid(), nullable=True),
    sa.Column('latest_approval_request_id', sa.Uuid(), nullable=True),
    sa.Column('submitted_at', app.db.base.UTCDateTime(), nullable=True),
    sa.Column('deleted_by_id', sa.Uuid(), nullable=True),
    sa.Column('deleted_at', app.db.base.UTCDateTime(), nullable=True),
    sa.Column('created_at', app.db.base.UTCDateTime(), nullable=False),
    sa.Column('updated_at', app.db.base.UTCDateTime(), nullable=False),
    sa.CheckConstraint("status IN ('draft', 'pending_approval', 'changes_requested', 'approved', 'rejected')", name='ck_document_status'),
    sa.ForeignKeyConstraint(['deleted_by_id'], ['app_user.id'], name=op.f('fk_document_deleted_by_id_app_user'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['doc_repo_id'], ['doc_repo.id'], name=op.f('fk_document_doc_repo_id_doc_repo')),
    sa.ForeignKeyConstraint(['maker_id'], ['app_user.id'], name=op.f('fk_document_maker_id_app_user'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_document'))
    )
    with op.batch_alter_table('document', schema=None) as batch_op:
        batch_op.create_index('ix_document_doc_repo_id_status', ['doc_repo_id', 'status'], unique=False)
        batch_op.create_index(batch_op.f('ix_document_upload_batch'), ['upload_batch'], unique=False)

    op.create_table('user_group_member',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('group_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('added_by_id', sa.Uuid(), nullable=True),
    sa.Column('added_at', app.db.base.UTCDateTime(), nullable=False),
    sa.Column('updated_at', app.db.base.UTCDateTime(), nullable=False),
    sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name='ck_user_group_member_status'),
    sa.ForeignKeyConstraint(['added_by_id'], ['app_user.id'], name=op.f('fk_user_group_member_added_by_id_app_user'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['group_id'], ['user_group.id'], name=op.f('fk_user_group_member_group_id_user_group')),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_user_group_member_user_id_app_user')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_group_member')),
    sa.UniqueConstraint('group_id', 'user_id', name='uq_user_group_member_group_id_user_id')
    )
    with op.batch_alter_table('user_group_member', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_group_member_user_id'), ['user_id'], unique=False)

    op.create_table('metadata_field',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('hierarchy_node_id', sa.Uuid(), nullable=True),
    sa.Column('document_id', sa.Uuid(), nullable=True),
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('label', sa.String(length=64), nullable=False),
    sa.Column('inheritable', sa.Boolean(), nullable=False),
    sa.Column('overridable', sa.Boolean(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('created_by_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', app.db.base.UTCDateTime(), nullable=False),
    sa.Column('updated_at', app.db.base.UTCDateTime(), nullable=False),
    sa.CheckConstraint('(hierarchy_node_id IS NULL) <> (document_id IS NULL)', name='ck_metadata_field_one_target'),
    sa.ForeignKeyConstraint(['created_by_id'], ['app_user.id'], name=op.f('fk_metadata_field_created_by_id_app_user'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['document_id'], ['document.id'], name=op.f('fk_metadata_field_document_id_document')),
    sa.ForeignKeyConstraint(['hierarchy_node_id'], ['hierarchy_node.id'], name=op.f('fk_metadata_field_hierarchy_node_id_hierarchy_node')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_metadata_field')),
    sa.UniqueConstraint('document_id', 'key', name='uq_metadata_field_document_id_key'),
    sa.UniqueConstraint('hierarchy_node_id', 'key', name='uq_metadata_field_hierarchy_node_id_key')
    )
    op.create_table('node_team_grant',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('hierarchy_node_id', sa.Uuid(), nullable=False),
    sa.Column('team_group_id', sa.Uuid(), nullable=False),
    sa.Column('role_id', sa.Uuid(), nullable=False),
    sa.Column('default_grant_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('granted_by_id', sa.Uuid(), nullable=True),
    sa.Column('granted_at', app.db.base.UTCDateTime(), nullable=False),
    sa.Column('updated_at', app.db.base.UTCDateTime(), nullable=False),
    sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name='ck_node_team_grant_status'),
    sa.ForeignKeyConstraint(['default_grant_id'], ['default_grant.id'], name=op.f('fk_node_team_grant_default_grant_id_default_grant'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['granted_by_id'], ['app_user.id'], name=op.f('fk_node_team_grant_granted_by_id_app_user'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['hierarchy_node_id'], ['hierarchy_node.id'], name=op.f('fk_node_team_grant_hierarchy_node_id_hierarchy_node')),
    sa.ForeignKeyConstraint(['role_id'], ['role.id'], name=op.f('fk_node_team_grant_role_id_role')),
    sa.ForeignKeyConstraint(['team_group_id'], ['user_group.id'], name=op.f('fk_node_team_grant_team_group_id_user_group')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_node_team_grant')),
    sa.UniqueConstraint('hierarchy_node_id', 'team_group_id', 'role_id', name='uq_node_team_grant_hierarchy_node_id_team_group_id_role_id')
    )
    with op.batch_alter_table('node_team_grant', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_node_team_grant_hierarchy_node_id'), ['hierarchy_node_id'], unique=False)

    op.create_table('user_group_member_role',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('group_member_id', sa.Uuid(), nullable=False),
    sa.Column('role_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('granted_by_id', sa.Uuid(), nullable=True),
    sa.Column('granted_at', app.db.base.UTCDateTime(), nullable=False),
    sa.Column('updated_at', app.db.base.UTCDateTime(), nullable=False),
    sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name='ck_user_group_member_role_status'),
    sa.ForeignKeyConstraint(['granted_by_id'], ['app_user.id'], name=op.f('fk_user_group_member_role_granted_by_id_app_user'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['group_member_id'], ['user_group_member.id'], name=op.f('fk_user_group_member_role_group_member_id_user_group_member')),
    sa.ForeignKeyConstraint(['role_id'], ['role.id'], name=op.f('fk_user_group_member_role_role_id_role')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_group_member_role')),
    sa.UniqueConstraint('group_member_id', 'role_id', name='uq_user_group_member_role_group_member_id_role_id')
    )
    op.create_table('metadata_value',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('metadata_field_id', sa.Uuid(), nullable=False),
    sa.Column('hierarchy_node_id', sa.Uuid(), nullable=True),
    sa.Column('document_id', sa.Uuid(), nullable=True),
    sa.Column('value', sa.Text(), nullable=True),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('inherited_from_node_id', sa.Uuid(), nullable=True),
    sa.Column('frozen', sa.Boolean(), nullable=False),
    sa.Column('set_by_id', sa.Uuid(), nullable=True),
    sa.Column('set_at', app.db.base.UTCDateTime(), nullable=False),
    sa.CheckConstraint("source IN ('ADMIN', 'MAKER', 'LLM', 'INHERITED')", name='ck_metadata_value_source'),
    sa.CheckConstraint('(hierarchy_node_id IS NULL) <> (document_id IS NULL)', name='ck_metadata_value_one_target'),
    sa.ForeignKeyConstraint(['document_id'], ['document.id'], name=op.f('fk_metadata_value_document_id_document')),
    sa.ForeignKeyConstraint(['hierarchy_node_id'], ['hierarchy_node.id'], name=op.f('fk_metadata_value_hierarchy_node_id_hierarchy_node')),
    sa.ForeignKeyConstraint(['inherited_from_node_id'], ['hierarchy_node.id'], name=op.f('fk_metadata_value_inherited_from_node_id_hierarchy_node')),
    sa.ForeignKeyConstraint(['metadata_field_id'], ['metadata_field.id'], name=op.f('fk_metadata_value_metadata_field_id_metadata_field')),
    sa.ForeignKeyConstraint(['set_by_id'], ['app_user.id'], name=op.f('fk_metadata_value_set_by_id_app_user'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_metadata_value')),
    sa.UniqueConstraint('metadata_field_id', 'document_id', name='uq_metadata_value_metadata_field_id_document_id'),
    sa.UniqueConstraint('metadata_field_id', 'hierarchy_node_id', name='uq_metadata_value_metadata_field_id_hierarchy_node_id')
    )
    with op.batch_alter_table('metadata_value', schema=None) as batch_op:
        batch_op.create_index('ix_metadata_value_document_id', ['document_id'], unique=False)
        batch_op.create_index('ix_metadata_value_field_value', ['metadata_field_id', 'value'], unique=False)

    # The old users/departments/roles and doc-repo tables go, children first. Their rows are not
    # carried over: with this redesign (2026-11-13) Data Hub started again from an empty database.
    op.drop_table('document_values')
    op.drop_table('documents')
    op.drop_table('doc_repo_members')
    op.drop_table('doc_repos')
    op.drop_table('user_org_unit_roles')
    op.drop_table('user_system_roles')
    op.drop_table('departments')
    op.drop_table('users')
    op.drop_table('roles')


def downgrade() -> None:
    op.create_table('departments',
    sa.Column('id', sa.INTEGER(), nullable=False),
    sa.Column('code', sa.VARCHAR(length=32), nullable=False),
    sa.Column('name', sa.VARCHAR(length=128), nullable=False),
    sa.Column('created_by_id', sa.INTEGER(), nullable=True),
    sa.Column('created_at', sa.DATETIME(), nullable=False),
    sa.CheckConstraint('code = upper(code) AND length(code) > 0', name=op.f('ck_departments_code')),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=op.f('fk_departments_created_by_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_departments')),
    sa.UniqueConstraint('code', name=op.f('uq_departments_code'))
    )
    op.create_table('doc_repos',
    sa.Column('id', sa.INTEGER(), nullable=False),
    sa.Column('department_id', sa.INTEGER(), nullable=False),
    sa.Column('name', sa.VARCHAR(length=128), nullable=False),
    sa.Column('description', sa.TEXT(), nullable=False),
    sa.Column('department_metadata', sa.JSON(), nullable=False),
    sa.Column('repository_metadata', sa.JSON(), nullable=False),
    sa.Column('created_by_id', sa.INTEGER(), nullable=True),
    sa.Column('created_at', sa.DATETIME(), nullable=False),
    sa.Column('updated_at', sa.DATETIME(), nullable=False),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=op.f('fk_doc_repos_created_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=op.f('fk_doc_repos_department_id_departments'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_doc_repos')),
    sa.UniqueConstraint('department_id', 'name', name=op.f('uq_doc_repos_department_name'))
    )
    with op.batch_alter_table('doc_repos', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_doc_repos_department_id'), ['department_id'], unique=False)

    op.create_table('user_org_unit_roles',
    sa.Column('user_id', sa.INTEGER(), nullable=False),
    sa.Column('department_id', sa.INTEGER(), nullable=False),
    sa.Column('role_code', sa.VARCHAR(length=32), nullable=False),
    sa.Column('scope', sa.VARCHAR(length=16), nullable=False),
    sa.Column('granted_by_id', sa.INTEGER(), nullable=True),
    sa.Column('granted_at', sa.DATETIME(), nullable=False),
    sa.CheckConstraint("scope = 'org_unit'", name=op.f('ck_user_org_unit_roles_scope')),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=op.f('fk_user_org_unit_roles_department_id_departments'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['granted_by_id'], ['users.id'], name=op.f('fk_user_org_unit_roles_granted_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['role_code', 'scope'], ['roles.code', 'roles.scope'], name=op.f('fk_user_org_unit_roles_role_code_scope_roles')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_org_unit_roles_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'department_id', 'role_code', name=op.f('pk_user_org_unit_roles'))
    )
    with op.batch_alter_table('user_org_unit_roles', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_org_unit_roles_department'), ['department_id', 'role_code'], unique=False)

    op.create_table('documents',
    sa.Column('id', sa.INTEGER(), nullable=False),
    sa.Column('doc_repo_id', sa.INTEGER(), nullable=False),
    sa.Column('folder', sa.VARCHAR(length=512), nullable=False),
    sa.Column('filename', sa.VARCHAR(length=256), nullable=False),
    sa.Column('content_type', sa.VARCHAR(length=128), nullable=True),
    sa.Column('size_bytes', sa.INTEGER(), nullable=False),
    sa.Column('storage_path', sa.VARCHAR(length=512), nullable=False),
    sa.Column('upload_batch', sa.VARCHAR(length=36), nullable=True),
    sa.Column('status', sa.VARCHAR(length=24), nullable=False),
    sa.Column('maker_id', sa.INTEGER(), nullable=True),
    sa.Column('checker_id', sa.INTEGER(), nullable=True),
    sa.Column('submitted_at', sa.DATETIME(), nullable=True),
    sa.Column('decided_at', sa.DATETIME(), nullable=True),
    sa.Column('rejection_reason', sa.TEXT(), nullable=True),
    sa.Column('department_metadata', sa.JSON(), nullable=False),
    sa.Column('department_overrides', sa.JSON(), nullable=False),
    sa.Column('ai_metadata', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DATETIME(), nullable=False),
    sa.Column('updated_at', sa.DATETIME(), nullable=False),
    sa.CheckConstraint("status IN ('draft', 'pending_approval', 'approved', 'rejected')", name=op.f('ck_documents_status')),
    sa.CheckConstraint('checker_id IS NULL OR checker_id <> maker_id', name=op.f('ck_documents_maker_checker')),
    sa.ForeignKeyConstraint(['checker_id'], ['users.id'], name=op.f('fk_documents_checker_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['doc_repo_id'], ['doc_repos.id'], name=op.f('fk_documents_doc_repo_id_doc_repos'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['maker_id'], ['users.id'], name=op.f('fk_documents_maker_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_documents'))
    )
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_documents_upload_batch'), ['upload_batch'], unique=False)
        batch_op.create_index(batch_op.f('ix_documents_doc_repo_status'), ['doc_repo_id', 'status'], unique=False)
        batch_op.create_index(batch_op.f('ix_documents_doc_repo_folder'), ['doc_repo_id', 'folder'], unique=False)

    op.create_table('document_values',
    sa.Column('document_id', sa.INTEGER(), nullable=False),
    sa.Column('source', sa.VARCHAR(length=8), nullable=False),
    sa.Column('key', sa.VARCHAR(length=64), nullable=False),
    sa.Column('value', sa.TEXT(), nullable=False),
    sa.CheckConstraint("source IN ('field', 'extra')", name=op.f('ck_document_values_source')),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_document_values_document_id_documents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('document_id', 'source', 'key', name=op.f('pk_document_values'))
    )
    with op.batch_alter_table('document_values', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_document_values_key_value'), ['key', 'value'], unique=False)

    op.create_table('users',
    sa.Column('id', sa.INTEGER(), nullable=False),
    sa.Column('lan_id', sa.VARCHAR(length=64), nullable=False),
    sa.Column('display_name', sa.VARCHAR(length=128), nullable=False),
    sa.Column('email', sa.VARCHAR(length=256), nullable=False),
    sa.Column('department', sa.VARCHAR(length=128), nullable=False),
    sa.Column('title', sa.VARCHAR(length=128), nullable=False),
    sa.Column('last_login_at', sa.DATETIME(), nullable=True),
    sa.Column('created_at', sa.DATETIME(), nullable=False),
    sa.Column('updated_at', sa.DATETIME(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email')),
    sa.UniqueConstraint('lan_id', name=op.f('uq_users_lan_id'))
    )
    op.create_table('doc_repo_members',
    sa.Column('doc_repo_id', sa.INTEGER(), nullable=False),
    sa.Column('user_id', sa.INTEGER(), nullable=False),
    sa.Column('role', sa.VARCHAR(length=16), nullable=False),
    sa.Column('granted_by_id', sa.INTEGER(), nullable=True),
    sa.Column('granted_at', sa.DATETIME(), nullable=False),
    sa.CheckConstraint("role IN ('MAKER', 'CHECKER', 'VIEWER')", name=op.f('ck_doc_repo_members_role')),
    sa.ForeignKeyConstraint(['doc_repo_id'], ['doc_repos.id'], name=op.f('fk_doc_repo_members_doc_repo_id_doc_repos'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['granted_by_id'], ['users.id'], name=op.f('fk_doc_repo_members_granted_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_doc_repo_members_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('doc_repo_id', 'user_id', 'role', name=op.f('pk_doc_repo_members'))
    )
    op.create_table('user_system_roles',
    sa.Column('user_id', sa.INTEGER(), nullable=False),
    sa.Column('role_code', sa.VARCHAR(length=32), nullable=False),
    sa.Column('scope', sa.VARCHAR(length=16), nullable=False),
    sa.Column('granted_by_id', sa.INTEGER(), nullable=True),
    sa.Column('granted_at', sa.DATETIME(), nullable=False),
    sa.CheckConstraint("scope = 'system'", name=op.f('ck_user_system_roles_scope')),
    sa.ForeignKeyConstraint(['granted_by_id'], ['users.id'], name=op.f('fk_user_system_roles_granted_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['role_code', 'scope'], ['roles.code', 'roles.scope'], name=op.f('fk_user_system_roles_role_code_scope_roles')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_system_roles_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'role_code', name=op.f('pk_user_system_roles'))
    )
    op.create_table('roles',
    sa.Column('code', sa.VARCHAR(length=32), nullable=False),
    sa.Column('scope', sa.VARCHAR(length=16), nullable=False),
    sa.Column('name', sa.VARCHAR(length=64), nullable=False),
    sa.Column('description', sa.VARCHAR(length=256), nullable=False),
    sa.CheckConstraint("scope IN ('system', 'org_unit')", name=op.f('ck_roles_scope')),
    sa.PrimaryKeyConstraint('code', name=op.f('pk_roles')),
    sa.UniqueConstraint('code', 'scope', name=op.f('uq_roles_code_scope'))
    )
    with op.batch_alter_table('metadata_value', schema=None) as batch_op:
        batch_op.drop_index('ix_metadata_value_field_value')
        batch_op.drop_index('ix_metadata_value_document_id')

    op.drop_table('metadata_value')
    op.drop_table('user_group_member_role')
    with op.batch_alter_table('node_team_grant', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_node_team_grant_hierarchy_node_id'))

    op.drop_table('node_team_grant')
    op.drop_table('metadata_field')
    with op.batch_alter_table('user_group_member', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_group_member_user_id'))

    op.drop_table('user_group_member')
    with op.batch_alter_table('document', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_document_upload_batch'))
        batch_op.drop_index('ix_document_doc_repo_id_status')

    op.drop_table('document')
    op.drop_table('default_grant')
    with op.batch_alter_table('user_group', schema=None) as batch_op:
        batch_op.drop_index('uq_user_group_one_members_group', sqlite_where=sa.text("group_type = 'MEMBERS'"), postgresql_where=sa.text("group_type = 'MEMBERS'"))
        batch_op.drop_index(batch_op.f('ix_user_group_hierarchy_node_id'))

    op.drop_table('user_group')
    op.drop_table('doc_repo')
    with op.batch_alter_table('approval_task_assignment', schema=None) as batch_op:
        batch_op.drop_index('ix_approval_task_assignment_inbox')

    op.drop_table('approval_task_assignment')
    op.drop_table('approval_event')
    op.drop_table('approval_decision')
    with op.batch_alter_table('hierarchy_node', schema=None) as batch_op:
        batch_op.drop_index('uq_hierarchy_node_one_root', sqlite_where=sa.text('parent_id IS NULL'), postgresql_where=sa.text('parent_id IS NULL'))
        batch_op.drop_index(batch_op.f('ix_hierarchy_node_parent_id'))

    op.drop_table('hierarchy_node')
    op.drop_table('approval_task')
    op.drop_table('role_permission')
    with op.batch_alter_table('resource_hierarchy_binding', schema=None) as batch_op:
        batch_op.drop_index('uq_resource_hierarchy_binding_one_active', sqlite_where=sa.text("status = 'ACTIVE'"), postgresql_where=sa.text("status = 'ACTIVE'"))

    op.drop_table('resource_hierarchy_binding')
    op.drop_table('hierarchy')
    with op.batch_alter_table('audit_event', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_event_hierarchy_node_id'))
        batch_op.drop_index(batch_op.f('ix_audit_event_created_at'))

    op.drop_table('audit_event')
    with op.batch_alter_table('approval_request', schema=None) as batch_op:
        batch_op.drop_index('ix_approval_request_subject')
        batch_op.drop_index('ix_approval_request_resource_status')

    op.drop_table('approval_request')
    op.drop_table('source_system')
    op.drop_table('role')
    op.drop_table('resource')
    op.drop_table('permission')
    op.drop_table('approval_type')
    op.drop_table('app_user')
