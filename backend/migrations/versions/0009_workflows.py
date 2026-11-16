"""Approval flows: versioned JSON definitions, bindings, instances and step instances.

- workflow_definition / workflow_version (the JSON flow, published versions never change) /
  workflow_binding (which version new requests use: a node's own, else the type's default).
- workflow_instance: one per request, pinned to its version. step_instance: one per step reached per
  round, with the node it ran at. approval_task now belongs to a step instance (one each), so a
  round can have several tasks (one per REVIEW step); the (request, round) unique key goes.
- approval_task_assignment.group_id becomes optional (a step may run at a node without a default group).

Seeded: Doc Hub's DOCUMENT_UPLOAD flow as version 1 (the behaviour so far: a maker check, then any one
checker at the repository), bound as the default, when that approval type exists. Every existing
request gets an instance on it, and every existing task its checker_review step instance.

Revision ID: 0009
Revises: 0008
Created: 2026-11-16 19:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

import app.db.base
from app.db.base import utcnow, uuid7

revision: str = '0009'
down_revision: str | None = '0008'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONX = sa.JSON().with_variant(JSONB(), "postgresql")
TS = app.db.base.UTCDateTime()

# The flow as it stood when this migration was written (a copy: the file in app/ may change later).
DOC_FLOW = {
    "code": "DOC_HUB.DOCUMENT_UPLOAD", "approval_type": "DOCUMENT_UPLOAD", "start": "maker_check",
    "steps": [
        {"id": "maker_check", "type": "CHECK", "name": "Raised by a maker", "node": {"selector": "RESOURCE_NODE"},
         "check": {"code": "HOLDS_ROLE", "role": "MAKER", "of": "REQUESTER"},
         "on": {"PASSED": "checker_review", "FAILED": "END:REFUSED"}},
        {"id": "checker_review", "type": "REVIEW", "name": "Checker review", "node": {"selector": "RESOURCE_NODE"},
         "assignment": {"role": "CHECKER", "exclude": ["MAKER", "REQUESTER"]}, "completion": {"rule": "ANY"},
         "on": {"APPROVED": "END:APPROVED", "REJECTED": "END:REJECTED", "CHANGES_REQUESTED": "maker"}},
    ],
}

approval_type = sa.table("approval_type", sa.column("id", sa.Uuid()), sa.column("code", sa.String()),
                         sa.column("name", sa.String()))
definition = sa.table("workflow_definition", sa.column("id", sa.Uuid()), sa.column("code", sa.String()),
                      sa.column("approval_type_id", sa.Uuid()), sa.column("name", sa.String()),
                      sa.column("created_at", TS), sa.column("updated_at", TS))
version = sa.table("workflow_version", sa.column("id", sa.Uuid()), sa.column("workflow_definition_id", sa.Uuid()),
                   sa.column("version", sa.Integer()), sa.column("definition", JSONX), sa.column("status", sa.String()),
                   sa.column("created_at", TS), sa.column("published_at", TS))
binding = sa.table("workflow_binding", sa.column("id", sa.Uuid()), sa.column("approval_type_id", sa.Uuid()),
                   sa.column("workflow_version_id", sa.Uuid()), sa.column("hierarchy_node_id", sa.Uuid()),
                   sa.column("status", sa.String()), sa.column("created_at", TS), sa.column("updated_at", TS))
instance = sa.table("workflow_instance", sa.column("id", sa.Uuid()), sa.column("approval_request_id", sa.Uuid()),
                    sa.column("workflow_version_id", sa.Uuid()), sa.column("current_step", sa.String()),
                    sa.column("status", sa.String()), sa.column("created_at", TS), sa.column("updated_at", TS))
step = sa.table("step_instance", sa.column("id", sa.Uuid()), sa.column("workflow_instance_id", sa.Uuid()),
                sa.column("round", sa.Integer()), sa.column("step_id", sa.String()), sa.column("step_type", sa.String()),
                sa.column("hierarchy_node_id", sa.Uuid()), sa.column("status", sa.String()),
                sa.column("outcome", sa.String()), sa.column("detail", sa.JSON()), sa.column("started_at", TS),
                sa.column("completed_at", TS))
request = sa.table("approval_request", sa.column("id", sa.Uuid()), sa.column("approval_type_id", sa.Uuid()),
                   sa.column("status", sa.String()), sa.column("submitted_at", TS))
task = sa.table("approval_task", sa.column("id", sa.Uuid()), sa.column("approval_request_id", sa.Uuid()),
                sa.column("round", sa.Integer()), sa.column("status", sa.String()), sa.column("outcome", sa.String()),
                sa.column("created_at", TS), sa.column("completed_at", TS), sa.column("step_instance_id", sa.Uuid()),
                sa.column("metadata", JSONX))
assignment = sa.table("approval_task_assignment", sa.column("approval_task_id", sa.Uuid()),
                      sa.column("hierarchy_node_id", sa.Uuid()))

INSTANCE_STATUS = {"PENDING": "RUNNING", "CHANGES_REQUESTED": "WAITING_MAKER", "APPROVED": "COMPLETED",
                   "REJECTED": "COMPLETED", "CANCELLED": "CANCELLED"}
STEP_STATUS = {"PENDING": "ACTIVE", "COMPLETED": "COMPLETED", "CANCELLED": "CANCELLED"}


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
    op.create_table(
        'workflow_definition',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('code', sa.String(length=128), nullable=False),
        sa.Column('approval_type_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('created_at', TS, nullable=False),
        sa.Column('updated_at', TS, nullable=False),
        sa.ForeignKeyConstraint(['approval_type_id'], ['approval_type.id'],
                                name='fk_workflow_definition_approval_type_id_approval_type'),
        sa.PrimaryKeyConstraint('id', name='pk_workflow_definition'),
        sa.UniqueConstraint('code', name='uq_workflow_definition_code'),
    )
    with op.batch_alter_table('workflow_definition', schema=None) as batch_op:
        batch_op.create_index('ix_workflow_definition_approval_type_id', ['approval_type_id'], unique=False)
    op.create_table(
        'workflow_version',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('workflow_definition_id', sa.Uuid(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('definition', JSONX, nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('created_at', TS, nullable=False),
        sa.Column('published_at', TS, nullable=True),
        sa.CheckConstraint("status IN ('DRAFT', 'PUBLISHED', 'RETIRED')", name='ck_workflow_version_status'),
        sa.ForeignKeyConstraint(['workflow_definition_id'], ['workflow_definition.id'],
                                name='fk_workflow_version_workflow_definition_id_workflow_definition'),
        sa.PrimaryKeyConstraint('id', name='pk_workflow_version'),
        sa.UniqueConstraint('workflow_definition_id', 'version', name='uq_workflow_version_workflow_definition_id_version'),
    )
    op.create_table(
        'workflow_binding',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('approval_type_id', sa.Uuid(), nullable=False),
        sa.Column('workflow_version_id', sa.Uuid(), nullable=False),
        sa.Column('hierarchy_node_id', sa.Uuid(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('created_at', TS, nullable=False),
        sa.Column('updated_at', TS, nullable=False),
        sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name='ck_workflow_binding_status'),
        sa.ForeignKeyConstraint(['approval_type_id'], ['approval_type.id'],
                                name='fk_workflow_binding_approval_type_id_approval_type'),
        sa.ForeignKeyConstraint(['workflow_version_id'], ['workflow_version.id'],
                                name='fk_workflow_binding_workflow_version_id_workflow_version'),
        sa.PrimaryKeyConstraint('id', name='pk_workflow_binding'),
    )
    with op.batch_alter_table('workflow_binding', schema=None) as batch_op:
        batch_op.create_index('uq_workflow_binding_one_default', ['approval_type_id'], unique=True,
                              sqlite_where=sa.text("hierarchy_node_id IS NULL AND status = 'ACTIVE'"),
                              postgresql_where=sa.text("hierarchy_node_id IS NULL AND status = 'ACTIVE'"))
        batch_op.create_index('uq_workflow_binding_one_per_node', ['approval_type_id', 'hierarchy_node_id'], unique=True,
                              sqlite_where=sa.text("hierarchy_node_id IS NOT NULL AND status = 'ACTIVE'"),
                              postgresql_where=sa.text("hierarchy_node_id IS NOT NULL AND status = 'ACTIVE'"))
    op.create_table(
        'workflow_instance',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('approval_request_id', sa.Uuid(), nullable=False),
        sa.Column('workflow_version_id', sa.Uuid(), nullable=False),
        sa.Column('current_step', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('created_at', TS, nullable=False),
        sa.Column('updated_at', TS, nullable=False),
        sa.CheckConstraint("status IN ('RUNNING', 'WAITING_MAKER', 'COMPLETED', 'CANCELLED')",
                           name='ck_workflow_instance_status'),
        sa.ForeignKeyConstraint(['approval_request_id'], ['approval_request.id'],
                                name='fk_workflow_instance_approval_request_id_approval_request'),
        sa.ForeignKeyConstraint(['workflow_version_id'], ['workflow_version.id'],
                                name='fk_workflow_instance_workflow_version_id_workflow_version'),
        sa.PrimaryKeyConstraint('id', name='pk_workflow_instance'),
        sa.UniqueConstraint('approval_request_id', name='uq_workflow_instance_approval_request_id'),
    )
    op.create_table(
        'step_instance',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('workflow_instance_id', sa.Uuid(), nullable=False),
        sa.Column('round', sa.Integer(), nullable=False),
        sa.Column('step_id', sa.String(length=64), nullable=False),
        sa.Column('step_type', sa.String(length=16), nullable=False),
        sa.Column('hierarchy_node_id', sa.Uuid(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('outcome', sa.String(length=24), nullable=True),
        sa.Column('detail', sa.JSON(), nullable=False),
        sa.Column('started_at', TS, nullable=False),
        sa.Column('completed_at', TS, nullable=True),
        sa.CheckConstraint("status IN ('ACTIVE', 'COMPLETED', 'CANCELLED')", name='ck_step_instance_status'),
        sa.CheckConstraint("step_type IN ('CHECK', 'REVIEW')", name='ck_step_instance_step_type'),
        sa.ForeignKeyConstraint(['workflow_instance_id'], ['workflow_instance.id'],
                                name='fk_step_instance_workflow_instance_id_workflow_instance'),
        sa.PrimaryKeyConstraint('id', name='pk_step_instance'),
        sa.UniqueConstraint('workflow_instance_id', 'round', 'step_id',
                            name='uq_step_instance_workflow_instance_id_round_step_id'),
    )

    _sqlite_foreign_keys(False)
    with op.batch_alter_table('approval_task', schema=None) as batch_op:
        batch_op.add_column(sa.Column('step_instance_id', sa.Uuid(), nullable=True))
    with op.batch_alter_table('approval_task_assignment', schema=None) as batch_op:
        batch_op.alter_column('group_id', existing_type=sa.Uuid(), nullable=True)

    bind = op.get_bind()
    now = utcnow()
    doc_type = bind.execute(sa.select(approval_type.c.id, approval_type.c.name)
                            .where(approval_type.c.code == "DOCUMENT_UPLOAD")).first()
    if doc_type is not None:
        def_id, ver_id = uuid7(), uuid7()
        bind.execute(definition.insert().values(id=def_id, code=DOC_FLOW["code"], approval_type_id=doc_type.id,
                                                name=f"{doc_type.name} (default)", created_at=now, updated_at=now))
        bind.execute(version.insert().values(id=ver_id, workflow_definition_id=def_id, version=1, definition=DOC_FLOW,
                                             status="PUBLISHED", created_at=now, published_at=now))
        bind.execute(binding.insert().values(id=uuid7(), approval_type_id=doc_type.id, workflow_version_id=ver_id,
                                             hierarchy_node_id=None, status="ACTIVE", created_at=now, updated_at=now))
        for req_id, req_status, submitted in bind.execute(
                sa.select(request.c.id, request.c.status, request.c.submitted_at)
                .where(request.c.approval_type_id == doc_type.id)).all():
            inst_id = uuid7()
            bind.execute(instance.insert().values(
                id=inst_id, approval_request_id=req_id, workflow_version_id=ver_id,
                current_step="checker_review" if req_status == "PENDING" else None,
                status=INSTANCE_STATUS[req_status], created_at=submitted or now, updated_at=now))
            for t_id, rnd, t_status, outcome, created, completed, meta, node_id in bind.execute(
                    sa.select(task.c.id, task.c.round, task.c.status, task.c.outcome, task.c.created_at,
                              task.c.completed_at, task.c.metadata, assignment.c.hierarchy_node_id)
                    .outerjoin(assignment, assignment.c.approval_task_id == task.c.id)
                    .where(task.c.approval_request_id == req_id)).all():
                step_id = uuid7()
                bind.execute(step.insert().values(
                    id=step_id, workflow_instance_id=inst_id, round=rnd, step_id="checker_review", step_type="REVIEW",
                    hierarchy_node_id=node_id, status=STEP_STATUS[t_status], outcome=outcome, detail={},
                    started_at=created or now, completed_at=completed))
                meta = {**(meta or {}), "step": {"id": "checker_review", "name": "Checker review"}}
                bind.execute(task.update().where(task.c.id == t_id).values(step_instance_id=step_id, metadata=meta))

    with op.batch_alter_table('approval_task', schema=None) as batch_op:
        batch_op.alter_column('step_instance_id', existing_type=sa.Uuid(), nullable=False)
        batch_op.drop_constraint('uq_approval_task_approval_request_id_round', type_='unique')
        batch_op.create_unique_constraint('uq_approval_task_step_instance_id', ['step_instance_id'])
        batch_op.create_foreign_key('fk_approval_task_step_instance_id_step_instance', 'step_instance',
                                    ['step_instance_id'], ['id'])
    _sqlite_foreign_keys(True)


def downgrade() -> None:
    """Back to one task per round. Fails if any round has more than one task (a multi-step flow ran)."""
    _sqlite_foreign_keys(False)
    with op.batch_alter_table('approval_task', schema=None) as batch_op:
        batch_op.drop_constraint('fk_approval_task_step_instance_id_step_instance', type_='foreignkey')
        batch_op.drop_constraint('uq_approval_task_step_instance_id', type_='unique')
        batch_op.drop_column('step_instance_id')
        batch_op.create_unique_constraint('uq_approval_task_approval_request_id_round', ['approval_request_id', 'round'])
    with op.batch_alter_table('approval_task_assignment', schema=None) as batch_op:
        batch_op.alter_column('group_id', existing_type=sa.Uuid(), nullable=False)
    op.drop_table('step_instance')
    op.drop_table('workflow_instance')
    with op.batch_alter_table('workflow_binding', schema=None) as batch_op:
        batch_op.drop_index('uq_workflow_binding_one_per_node',
                            sqlite_where=sa.text("hierarchy_node_id IS NOT NULL AND status = 'ACTIVE'"),
                            postgresql_where=sa.text("hierarchy_node_id IS NOT NULL AND status = 'ACTIVE'"))
        batch_op.drop_index('uq_workflow_binding_one_default',
                            sqlite_where=sa.text("hierarchy_node_id IS NULL AND status = 'ACTIVE'"),
                            postgresql_where=sa.text("hierarchy_node_id IS NULL AND status = 'ACTIVE'"))
    op.drop_table('workflow_binding')
    op.drop_table('workflow_version')
    with op.batch_alter_table('workflow_definition', schema=None) as batch_op:
        batch_op.drop_index('ix_workflow_definition_approval_type_id')
    op.drop_table('workflow_definition')
    _sqlite_foreign_keys(True)
