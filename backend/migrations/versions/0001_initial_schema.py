"""Initial schema: sign-in sessions, users and roles, departments, document repositories.

The starting point for every database. Later changes go in later migrations, never here.

Revision ID: 0001
Revises: 
Created: 2026-11-12 17:15:27.942393
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db.base

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('auth_sessions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('lan_id', sa.String(length=64), nullable=False),
    sa.Column('issued_at', app.db.base.UTCDateTime(), nullable=False),
    sa.Column('expires_at', app.db.base.UTCDateTime(), nullable=False),
    sa.Column('revoked_at', app.db.base.UTCDateTime(), nullable=True),
    sa.Column('revoked_reason', sa.String(length=64), nullable=True),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.String(length=256), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_auth_sessions'))
    )
    with op.batch_alter_table('auth_sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_auth_sessions_lan_id'), ['lan_id'], unique=False)

    op.create_table('roles',
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('scope', sa.String(length=16), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('description', sa.String(length=256), nullable=False),
    sa.CheckConstraint("scope IN ('system', 'org_unit')", name='ck_roles_scope'),
    sa.PrimaryKeyConstraint('code', name=op.f('pk_roles')),
    sa.UniqueConstraint('code', 'scope', name='uq_roles_code_scope')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('lan_id', sa.String(length=64), nullable=False),
    sa.Column('display_name', sa.String(length=128), nullable=False),
    sa.Column('email', sa.String(length=256), nullable=False),
    sa.Column('department', sa.String(length=128), nullable=False),
    sa.Column('title', sa.String(length=128), nullable=False),
    sa.Column('last_login_at', app.db.base.UTCDateTime(), nullable=True),
    sa.Column('created_at', app.db.base.UTCDateTime(), nullable=False),
    sa.Column('updated_at', app.db.base.UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email')),
    sa.UniqueConstraint('lan_id', name=op.f('uq_users_lan_id'))
    )
    op.create_table('departments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', app.db.base.UTCDateTime(), nullable=False),
    sa.CheckConstraint('code = upper(code) AND length(code) > 0', name='ck_departments_code'),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=op.f('fk_departments_created_by_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_departments')),
    sa.UniqueConstraint('code', name=op.f('uq_departments_code'))
    )
    op.create_table('user_system_roles',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('role_code', sa.String(length=32), nullable=False),
    sa.Column('scope', sa.String(length=16), nullable=False),
    sa.Column('granted_by_id', sa.Integer(), nullable=True),
    sa.Column('granted_at', app.db.base.UTCDateTime(), nullable=False),
    sa.CheckConstraint("scope = 'system'", name='ck_user_system_roles_scope'),
    sa.ForeignKeyConstraint(['granted_by_id'], ['users.id'], name=op.f('fk_user_system_roles_granted_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['role_code', 'scope'], ['roles.code', 'roles.scope'], name=op.f('fk_user_system_roles_role_code_scope_roles')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_system_roles_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'role_code', name=op.f('pk_user_system_roles'))
    )
    op.create_table('doc_repos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('department_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('department_metadata', sa.JSON(), nullable=False),
    sa.Column('repository_metadata', sa.JSON(), nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', app.db.base.UTCDateTime(), nullable=False),
    sa.Column('updated_at', app.db.base.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=op.f('fk_doc_repos_created_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=op.f('fk_doc_repos_department_id_departments'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_doc_repos')),
    sa.UniqueConstraint('department_id', 'name', name='uq_doc_repos_department_name')
    )
    with op.batch_alter_table('doc_repos', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_doc_repos_department_id'), ['department_id'], unique=False)

    op.create_table('user_org_unit_roles',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('department_id', sa.Integer(), nullable=False),
    sa.Column('role_code', sa.String(length=32), nullable=False),
    sa.Column('scope', sa.String(length=16), nullable=False),
    sa.Column('granted_by_id', sa.Integer(), nullable=True),
    sa.Column('granted_at', app.db.base.UTCDateTime(), nullable=False),
    sa.CheckConstraint("scope = 'org_unit'", name='ck_user_org_unit_roles_scope'),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=op.f('fk_user_org_unit_roles_department_id_departments'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['granted_by_id'], ['users.id'], name=op.f('fk_user_org_unit_roles_granted_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['role_code', 'scope'], ['roles.code', 'roles.scope'], name=op.f('fk_user_org_unit_roles_role_code_scope_roles')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_org_unit_roles_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'department_id', 'role_code', name=op.f('pk_user_org_unit_roles'))
    )
    with op.batch_alter_table('user_org_unit_roles', schema=None) as batch_op:
        batch_op.create_index('ix_user_org_unit_roles_department', ['department_id', 'role_code'], unique=False)

    op.create_table('doc_repo_members',
    sa.Column('doc_repo_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('granted_by_id', sa.Integer(), nullable=True),
    sa.Column('granted_at', app.db.base.UTCDateTime(), nullable=False),
    sa.CheckConstraint("role IN ('MAKER', 'CHECKER', 'VIEWER')", name='ck_doc_repo_members_role'),
    sa.ForeignKeyConstraint(['doc_repo_id'], ['doc_repos.id'], name=op.f('fk_doc_repo_members_doc_repo_id_doc_repos'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['granted_by_id'], ['users.id'], name=op.f('fk_doc_repo_members_granted_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_doc_repo_members_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('doc_repo_id', 'user_id', 'role', name=op.f('pk_doc_repo_members'))
    )
    op.create_table('documents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('doc_repo_id', sa.Integer(), nullable=False),
    sa.Column('folder', sa.String(length=512), nullable=False),
    sa.Column('filename', sa.String(length=256), nullable=False),
    sa.Column('content_type', sa.String(length=128), nullable=True),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('storage_path', sa.String(length=512), nullable=False),
    sa.Column('upload_batch', sa.String(length=36), nullable=True),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('maker_id', sa.Integer(), nullable=True),
    sa.Column('checker_id', sa.Integer(), nullable=True),
    sa.Column('submitted_at', app.db.base.UTCDateTime(), nullable=True),
    sa.Column('decided_at', app.db.base.UTCDateTime(), nullable=True),
    sa.Column('rejection_reason', sa.Text(), nullable=True),
    sa.Column('department_metadata', sa.JSON(), nullable=False),
    sa.Column('department_overrides', sa.JSON(), nullable=False),
    sa.Column('ai_metadata', sa.JSON(), nullable=False),
    sa.Column('created_at', app.db.base.UTCDateTime(), nullable=False),
    sa.Column('updated_at', app.db.base.UTCDateTime(), nullable=False),
    sa.CheckConstraint("status IN ('draft', 'pending_approval', 'approved', 'rejected')", name='ck_documents_status'),
    sa.CheckConstraint('checker_id IS NULL OR checker_id <> maker_id', name='ck_documents_maker_checker'),
    sa.ForeignKeyConstraint(['checker_id'], ['users.id'], name=op.f('fk_documents_checker_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['doc_repo_id'], ['doc_repos.id'], name=op.f('fk_documents_doc_repo_id_doc_repos'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['maker_id'], ['users.id'], name=op.f('fk_documents_maker_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_documents'))
    )
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.create_index('ix_documents_doc_repo_folder', ['doc_repo_id', 'folder'], unique=False)
        batch_op.create_index('ix_documents_doc_repo_status', ['doc_repo_id', 'status'], unique=False)
        batch_op.create_index(batch_op.f('ix_documents_upload_batch'), ['upload_batch'], unique=False)

    op.create_table('document_values',
    sa.Column('document_id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=8), nullable=False),
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('value', sa.Text(), nullable=False),
    sa.CheckConstraint("source IN ('field', 'extra')", name='ck_document_values_source'),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_document_values_document_id_documents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('document_id', 'source', 'key', name=op.f('pk_document_values'))
    )
    with op.batch_alter_table('document_values', schema=None) as batch_op:
        batch_op.create_index('ix_document_values_key_value', ['key', 'value'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('document_values', schema=None) as batch_op:
        batch_op.drop_index('ix_document_values_key_value')

    op.drop_table('document_values')
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_documents_upload_batch'))
        batch_op.drop_index('ix_documents_doc_repo_status')
        batch_op.drop_index('ix_documents_doc_repo_folder')

    op.drop_table('documents')
    op.drop_table('doc_repo_members')
    with op.batch_alter_table('user_org_unit_roles', schema=None) as batch_op:
        batch_op.drop_index('ix_user_org_unit_roles_department')

    op.drop_table('user_org_unit_roles')
    with op.batch_alter_table('doc_repos', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_doc_repos_department_id'))

    op.drop_table('doc_repos')
    op.drop_table('user_system_roles')
    op.drop_table('departments')
    op.drop_table('users')
    op.drop_table('roles')
    with op.batch_alter_table('auth_sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_auth_sessions_lan_id'))

    op.drop_table('auth_sessions')
