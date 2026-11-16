"""Standalone workflows: generic tables, the new flow format, and a workflow per repository.

- workflow_definition: no approval type any more; `kind` says what its steps work on (DOC_HUB.DOCUMENT).
- workflow_binding: a node (e.g. a repository) uses one flow per kind; chosen by its owner or admins.
- workflow_instance: runs for a generic subject (subject_type, subject_id, e.g. APPROVAL_REQUEST) at a
  node, with its own round and outcome; approval_request.workflow_instance_id points at it.
- step_instance: step_type is any registered type (DOCUMENT_UPLOAD, DOCUMENT_REVIEW ...); no node column.

The old flow (DOC_HUB.DOCUMENT_UPLOAD, CHECK/REVIEW steps) is replaced by DOC_HUB.DOCUMENT_APPROVAL v1
(maker_upload / checker_review, user group "default"). Every repository is bound to it, and every
request's instance and steps move onto it (same ids; maker_check becomes maker_upload). Existing tasks'
assignments lose their group, so whoever they're assigned to keeps them (any group at the node).

Revision ID: 0010
Revises: 0009
Created: 2026-11-16 21:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

import app.db.base
from app.db.base import utcnow, uuid7

revision: str = '0010'
down_revision: str | None = '0009'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONX = sa.JSON().with_variant(JSONB(), "postgresql")
TS = app.db.base.UTCDateTime()
KIND = "DOC_HUB.DOCUMENT"

NEW_FLOW = {  # a copy: the file in app/ may change later
    "code": "DOC_HUB.DOCUMENT_APPROVAL", "name": "Document approval", "start": "maker_upload",
    "steps": [
        {"id": "maker_upload", "type": "DOCUMENT_UPLOAD", "name": "Raised by a maker",
         "role": {"user_group": "default", "role": "MAKER"},
         "on": {"PASSED": "checker_review", "FAILED": "END:UNAUTHORIZED"}},
        {"id": "checker_review", "type": "DOCUMENT_REVIEW", "name": "Checker review",
         "role": {"user_group": "default", "role": "CHECKER"}, "completion": {"rule": "ANY"},
         "on": {"APPROVED": "END:APPROVED", "REJECTED": "END:REJECTED", "CHANGES_REQUESTED": "maker_upload"}},
    ],
}
OLD_FLOW = {  # 0009's, for downgrading
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
STEP_UP = {"maker_check": ("maker_upload", "DOCUMENT_UPLOAD"), "checker_review": ("checker_review", "DOCUMENT_REVIEW")}
STEP_DOWN = {"maker_upload": ("maker_check", "CHECK"), "checker_review": ("checker_review", "REVIEW")}


def t(name, *cols):
    return sa.table(name, *[sa.column(c, typ) for c, typ in cols])


U, S, I = sa.Uuid(), sa.String(), sa.Integer()
request = t("approval_request", ("id", U), ("status", S), ("current_round", I), ("resource_pk", U),
            ("approval_type_id", U), ("workflow_instance_id", U))
res_binding = t("resource_hierarchy_binding", ("resource_pk", U), ("hierarchy_node_id", U), ("status", S))
doc_repo = t("doc_repo", ("hierarchy_node_id", U))
approval_type = t("approval_type", ("id", U), ("code", S), ("name", S))
assignment = t("approval_task_assignment", ("group_id", U))


def _sqlite_foreign_keys(on: bool) -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    bind.exec_driver_sql(f"PRAGMA foreign_keys={'ON' if on else 'OFF'}")
    if on:
        problems = bind.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        if problems:
            raise RuntimeError(f"Foreign key problems after the rebuild: {problems[:5]}")


COLUMNS = {  # typed, so timestamps and ids come back as datetimes and UUIDs
    "old_instance": ("workflow_instance", (("id", U), ("approval_request_id", U), ("current_step", S), ("status", S),
                                           ("created_at", TS))),
    "new_instance": ("workflow_instance", (("id", U), ("subject_type", S), ("subject_id", S), ("hierarchy_node_id", U),
                                           ("current_step", S), ("status", S), ("created_at", TS))),
    "step": ("step_instance", (("id", U), ("workflow_instance_id", U), ("round", I), ("step_id", S), ("step_type", S),
                               ("status", S), ("outcome", S), ("detail", sa.JSON()), ("started_at", TS),
                               ("completed_at", TS))),
}


def _rows(which: str) -> list[dict]:
    name, cols = COLUMNS[which]
    table = sa.table(name, *[sa.column(c, typ) for c, typ in cols])
    return [dict(r._mapping) for r in op.get_bind().execute(sa.select(table)).all()]


def _drop_workflow_tables() -> None:
    for name in ("step_instance", "workflow_instance", "workflow_binding", "workflow_version", "workflow_definition"):
        op.drop_table(name)


def _create_version_table() -> None:
    op.create_table(
        'workflow_version',
        sa.Column('id', U, nullable=False), sa.Column('workflow_definition_id', U, nullable=False),
        sa.Column('version', I, nullable=False), sa.Column('definition', JSONX, nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False), sa.Column('created_at', TS, nullable=False),
        sa.Column('published_at', TS, nullable=True),
        sa.CheckConstraint("status IN ('DRAFT', 'PUBLISHED', 'RETIRED')", name='ck_workflow_version_status'),
        sa.ForeignKeyConstraint(['workflow_definition_id'], ['workflow_definition.id'],
                                name='fk_workflow_version_workflow_definition_id_workflow_definition'),
        sa.PrimaryKeyConstraint('id', name='pk_workflow_version'),
        sa.UniqueConstraint('workflow_definition_id', 'version', name='uq_workflow_version_workflow_definition_id_version'),
    )


def upgrade() -> None:
    bind = op.get_bind()
    old_instances, old_steps = _rows("old_instance"), _rows("step")
    _sqlite_foreign_keys(False)
    _drop_workflow_tables()

    op.create_table(
        'workflow_definition',
        sa.Column('id', U, nullable=False), sa.Column('code', sa.String(length=128), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False), sa.Column('kind', sa.String(length=64), nullable=False),
        sa.Column('created_at', TS, nullable=False), sa.Column('updated_at', TS, nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_workflow_definition'),
        sa.UniqueConstraint('code', name='uq_workflow_definition_code'),
    )
    with op.batch_alter_table('workflow_definition', schema=None) as batch_op:
        batch_op.create_index('ix_workflow_definition_kind', ['kind'], unique=False)
    _create_version_table()
    op.create_table(
        'workflow_binding',
        sa.Column('id', U, nullable=False), sa.Column('hierarchy_node_id', U, nullable=False),
        sa.Column('kind', sa.String(length=64), nullable=False), sa.Column('workflow_definition_id', U, nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False), sa.Column('bound_by_id', U, nullable=True),
        sa.Column('created_at', TS, nullable=False), sa.Column('updated_at', TS, nullable=False),
        sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name='ck_workflow_binding_status'),
        sa.ForeignKeyConstraint(['workflow_definition_id'], ['workflow_definition.id'],
                                name='fk_workflow_binding_workflow_definition_id_workflow_definition'),
        sa.PrimaryKeyConstraint('id', name='pk_workflow_binding'),
    )
    with op.batch_alter_table('workflow_binding', schema=None) as batch_op:
        batch_op.create_index('uq_workflow_binding_one_per_node_kind', ['hierarchy_node_id', 'kind'], unique=True,
                              sqlite_where=sa.text("status = 'ACTIVE'"), postgresql_where=sa.text("status = 'ACTIVE'"))
    op.create_table(
        'workflow_instance',
        sa.Column('id', U, nullable=False), sa.Column('workflow_version_id', U, nullable=False),
        sa.Column('subject_type', sa.String(length=64), nullable=False),
        sa.Column('subject_id', sa.String(length=64), nullable=False),
        sa.Column('hierarchy_node_id', U, nullable=False), sa.Column('round', I, nullable=False),
        sa.Column('current_step', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False), sa.Column('outcome', sa.String(length=32), nullable=True),
        sa.Column('created_at', TS, nullable=False), sa.Column('updated_at', TS, nullable=False),
        sa.CheckConstraint("status IN ('RUNNING', 'COMPLETED', 'CANCELLED')", name='ck_workflow_instance_status'),
        sa.ForeignKeyConstraint(['workflow_version_id'], ['workflow_version.id'],
                                name='fk_workflow_instance_workflow_version_id_workflow_version'),
        sa.PrimaryKeyConstraint('id', name='pk_workflow_instance'),
    )
    with op.batch_alter_table('workflow_instance', schema=None) as batch_op:
        batch_op.create_index('ix_workflow_instance_subject', ['subject_type', 'subject_id'], unique=False)
    op.create_table(
        'step_instance',
        sa.Column('id', U, nullable=False), sa.Column('workflow_instance_id', U, nullable=False),
        sa.Column('round', I, nullable=False), sa.Column('step_id', sa.String(length=64), nullable=False),
        sa.Column('step_type', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False), sa.Column('outcome', sa.String(length=32), nullable=True),
        sa.Column('detail', sa.JSON(), nullable=False), sa.Column('started_at', TS, nullable=False),
        sa.Column('completed_at', TS, nullable=True),
        sa.CheckConstraint("status IN ('ACTIVE', 'COMPLETED', 'CANCELLED')", name='ck_step_instance_status'),
        sa.ForeignKeyConstraint(['workflow_instance_id'], ['workflow_instance.id'],
                                name='fk_step_instance_workflow_instance_id_workflow_instance'),
        sa.PrimaryKeyConstraint('id', name='pk_step_instance'),
        sa.UniqueConstraint('workflow_instance_id', 'round', 'step_id',
                            name='uq_step_instance_workflow_instance_id_round_step_id'),
    )
    with op.batch_alter_table('approval_request', schema=None) as batch_op:
        batch_op.add_column(sa.Column('workflow_instance_id', U, nullable=True))
        batch_op.create_foreign_key('fk_approval_request_workflow_instance_id_workflow_instance', 'workflow_instance',
                                    ['workflow_instance_id'], ['id'])

    # ----- data
    now = utcnow()
    repo_nodes = bind.execute(sa.select(doc_repo.c.hierarchy_node_id)).scalars().all()
    if repo_nodes or old_instances:
        def_id, ver_id = uuid7(), uuid7()
        bind.execute(sa.table("workflow_definition", sa.column("id", U), sa.column("code", S), sa.column("name", S),
                              sa.column("kind", S), sa.column("created_at", TS), sa.column("updated_at", TS)).insert()
                     .values(id=def_id, code=NEW_FLOW["code"], name=NEW_FLOW["name"], kind=KIND, created_at=now,
                             updated_at=now))
        bind.execute(sa.table("workflow_version", sa.column("id", U), sa.column("workflow_definition_id", U),
                              sa.column("version", I), sa.column("definition", JSONX), sa.column("status", S),
                              sa.column("created_at", TS), sa.column("published_at", TS)).insert()
                     .values(id=ver_id, workflow_definition_id=def_id, version=1, definition=NEW_FLOW,
                             status="PUBLISHED", created_at=now, published_at=now))
        binding = sa.table("workflow_binding", sa.column("id", U), sa.column("hierarchy_node_id", U), sa.column("kind", S),
                           sa.column("workflow_definition_id", U), sa.column("status", S), sa.column("created_at", TS),
                           sa.column("updated_at", TS))
        for node_id in repo_nodes:
            bind.execute(binding.insert().values(id=uuid7(), hierarchy_node_id=node_id, kind=KIND,
                                                 workflow_definition_id=def_id, status="ACTIVE", created_at=now,
                                                 updated_at=now))
        inst_t = sa.table("workflow_instance", *[sa.column(c, typ) for c, typ in (
            ("id", U), ("workflow_version_id", U), ("subject_type", S), ("subject_id", S), ("hierarchy_node_id", U),
            ("round", I), ("current_step", S), ("status", S), ("outcome", S), ("created_at", TS), ("updated_at", TS))])
        step_t = sa.table("step_instance", *[sa.column(c, typ) for c, typ in (
            ("id", U), ("workflow_instance_id", U), ("round", I), ("step_id", S), ("step_type", S), ("status", S),
            ("outcome", S), ("detail", sa.JSON()), ("started_at", TS), ("completed_at", TS))])
        steps_by_instance: dict = {}
        for st in old_steps:
            steps_by_instance.setdefault(str(st["workflow_instance_id"]), []).append(st)
        for inst in old_instances:
            req = bind.execute(sa.select(request).where(request.c.id == _uuid(inst["approval_request_id"]))).first()
            if req is None:
                continue
            node = bind.execute(sa.select(res_binding.c.hierarchy_node_id).where(
                res_binding.c.resource_pk == req.resource_pk).order_by(res_binding.c.status)).scalar()
            rnd, current, status, outcome = req.current_round, inst["current_step"], inst["status"], None
            if status == "WAITING_MAKER":
                rnd, current, status = req.current_round + 1, "maker_upload", "RUNNING"
            elif status == "COMPLETED":
                outcome = req.status
            elif current:
                current = STEP_UP.get(current, (current,))[0]
            inst_id = _uuid(inst["id"])
            bind.execute(inst_t.insert().values(
                id=inst_id, workflow_version_id=ver_id, subject_type="APPROVAL_REQUEST", subject_id=str(req.id),
                hierarchy_node_id=node, round=rnd, current_step=current, status=status, outcome=outcome,
                created_at=inst["created_at"] or now, updated_at=now))
            for st in steps_by_instance.get(str(inst["id"]), []):
                step_id, step_type = STEP_UP.get(st["step_id"], (st["step_id"], st["step_type"]))
                bind.execute(step_t.insert().values(
                    id=_uuid(st["id"]), workflow_instance_id=inst_id, round=st["round"], step_id=step_id,
                    step_type=step_type, status=st["status"], outcome=st["outcome"], detail=_json(st["detail"]),
                    started_at=st["started_at"], completed_at=st["completed_at"]))
            if inst["status"] == "WAITING_MAKER":
                bind.execute(step_t.insert().values(
                    id=uuid7(), workflow_instance_id=inst_id, round=rnd, step_id="maker_upload",
                    step_type="DOCUMENT_UPLOAD", status="ACTIVE", outcome=None, detail={}, started_at=now,
                    completed_at=None))
            bind.execute(request.update().where(request.c.id == req.id).values(workflow_instance_id=inst_id))
    bind.execute(assignment.update().values(group_id=None))
    _sqlite_foreign_keys(True)


def _uuid(value):
    import uuid
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _json(value):
    import json
    return json.loads(value) if isinstance(value, str) else (value or {})


def downgrade() -> None:
    """Back to 0009's tables; instances move onto its DOC_HUB.DOCUMENT_UPLOAD flow (the type's default)."""
    bind = op.get_bind()
    new_instances, new_steps = _rows("new_instance"), _rows("step")
    _sqlite_foreign_keys(False)
    with op.batch_alter_table('approval_request', schema=None) as batch_op:
        batch_op.drop_constraint('fk_approval_request_workflow_instance_id_workflow_instance', type_='foreignkey')
        batch_op.drop_column('workflow_instance_id')
    _drop_workflow_tables()
    op.create_table(
        'workflow_definition',
        sa.Column('id', U, nullable=False), sa.Column('code', sa.String(length=128), nullable=False),
        sa.Column('approval_type_id', U, nullable=False), sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('created_at', TS, nullable=False), sa.Column('updated_at', TS, nullable=False),
        sa.ForeignKeyConstraint(['approval_type_id'], ['approval_type.id'],
                                name='fk_workflow_definition_approval_type_id_approval_type'),
        sa.PrimaryKeyConstraint('id', name='pk_workflow_definition'),
        sa.UniqueConstraint('code', name='uq_workflow_definition_code'),
    )
    with op.batch_alter_table('workflow_definition', schema=None) as batch_op:
        batch_op.create_index('ix_workflow_definition_approval_type_id', ['approval_type_id'], unique=False)
    _create_version_table()
    op.create_table(
        'workflow_binding',
        sa.Column('id', U, nullable=False), sa.Column('approval_type_id', U, nullable=False),
        sa.Column('workflow_version_id', U, nullable=False), sa.Column('hierarchy_node_id', U, nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False), sa.Column('created_at', TS, nullable=False),
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
        sa.Column('id', U, nullable=False), sa.Column('approval_request_id', U, nullable=False),
        sa.Column('workflow_version_id', U, nullable=False), sa.Column('current_step', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False), sa.Column('created_at', TS, nullable=False),
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
        sa.Column('id', U, nullable=False), sa.Column('workflow_instance_id', U, nullable=False),
        sa.Column('round', I, nullable=False), sa.Column('step_id', sa.String(length=64), nullable=False),
        sa.Column('step_type', sa.String(length=16), nullable=False), sa.Column('hierarchy_node_id', U, nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False), sa.Column('outcome', sa.String(length=24), nullable=True),
        sa.Column('detail', sa.JSON(), nullable=False), sa.Column('started_at', TS, nullable=False),
        sa.Column('completed_at', TS, nullable=True),
        sa.CheckConstraint("status IN ('ACTIVE', 'COMPLETED', 'CANCELLED')", name='ck_step_instance_status'),
        sa.CheckConstraint("step_type IN ('CHECK', 'REVIEW')", name='ck_step_instance_step_type'),
        sa.ForeignKeyConstraint(['workflow_instance_id'], ['workflow_instance.id'],
                                name='fk_step_instance_workflow_instance_id_workflow_instance'),
        sa.PrimaryKeyConstraint('id', name='pk_step_instance'),
        sa.UniqueConstraint('workflow_instance_id', 'round', 'step_id',
                            name='uq_step_instance_workflow_instance_id_round_step_id'),
    )
    now = utcnow()
    doc_type = bind.execute(sa.select(approval_type.c.id, approval_type.c.name)
                            .where(approval_type.c.code == "DOCUMENT_UPLOAD")).first()
    if doc_type is not None:
        def_id, ver_id = uuid7(), uuid7()
        op.bulk_insert(sa.table("workflow_definition", sa.column("id", U), sa.column("code", S),
                                sa.column("approval_type_id", U), sa.column("name", S), sa.column("created_at", TS),
                                sa.column("updated_at", TS)),
                       [{"id": def_id, "code": OLD_FLOW["code"], "approval_type_id": doc_type.id,
                         "name": f"{doc_type.name} (default)", "created_at": now, "updated_at": now}])
        op.bulk_insert(sa.table("workflow_version", sa.column("id", U), sa.column("workflow_definition_id", U),
                                sa.column("version", I), sa.column("definition", JSONX), sa.column("status", S),
                                sa.column("created_at", TS), sa.column("published_at", TS)),
                       [{"id": ver_id, "workflow_definition_id": def_id, "version": 1, "definition": OLD_FLOW,
                         "status": "PUBLISHED", "created_at": now, "published_at": now}])
        op.bulk_insert(sa.table("workflow_binding", sa.column("id", U), sa.column("approval_type_id", U),
                                sa.column("workflow_version_id", U), sa.column("hierarchy_node_id", U),
                                sa.column("status", S), sa.column("created_at", TS), sa.column("updated_at", TS)),
                       [{"id": uuid7(), "approval_type_id": doc_type.id, "workflow_version_id": ver_id,
                         "hierarchy_node_id": None, "status": "ACTIVE", "created_at": now, "updated_at": now}])
        inst_t = sa.table("workflow_instance", *[sa.column(c, typ) for c, typ in (
            ("id", U), ("approval_request_id", U), ("workflow_version_id", U), ("current_step", S), ("status", S),
            ("created_at", TS), ("updated_at", TS))])
        step_t = sa.table("step_instance", *[sa.column(c, typ) for c, typ in (
            ("id", U), ("workflow_instance_id", U), ("round", I), ("step_id", S), ("step_type", S),
            ("hierarchy_node_id", U), ("status", S), ("outcome", S), ("detail", sa.JSON()), ("started_at", TS),
            ("completed_at", TS))])
        waiting = {str(s["workflow_instance_id"]) for s in new_steps
                   if s["status"] == "ACTIVE" and s["step_id"] == "maker_upload"}
        for inst in new_instances:
            if inst["subject_type"] != "APPROVAL_REQUEST":
                continue
            status = "WAITING_MAKER" if str(inst["id"]) in waiting else inst["status"]
            current = STEP_DOWN.get(inst["current_step"], (inst["current_step"],))[0] if inst["current_step"] else None
            bind.execute(inst_t.insert().values(
                id=_uuid(inst["id"]), approval_request_id=_uuid(inst["subject_id"]), workflow_version_id=ver_id,
                current_step=None if status == "WAITING_MAKER" else current, status=status,
                created_at=inst["created_at"] or now, updated_at=now))
            for st in new_steps:
                if str(st["workflow_instance_id"]) != str(inst["id"]):
                    continue
                if st["status"] == "ACTIVE" and st["step_id"] == "maker_upload":
                    continue  # waiting for the maker: 0009 had no step for that
                step_id, step_type = STEP_DOWN.get(st["step_id"], (st["step_id"], "REVIEW"))
                bind.execute(step_t.insert().values(
                    id=_uuid(st["id"]), workflow_instance_id=_uuid(inst["id"]), round=st["round"], step_id=step_id,
                    step_type=step_type, hierarchy_node_id=_uuid(inst["hierarchy_node_id"]), status=st["status"],
                    outcome=st["outcome"], detail=_json(st["detail"]), started_at=st["started_at"],
                    completed_at=st["completed_at"]))
    _sqlite_foreign_keys(True)
