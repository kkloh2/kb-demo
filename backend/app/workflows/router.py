"""Approval workflow endpoints (platform admins): the flows, their versions, and the step types they
can use. Shown under Approvals > Approval Workflows.

    GET  /api/approval-workflows                  every flow
    POST /api/approval-workflows                  {definition}: a new flow, published as version 1
    GET  /api/approval-workflows/step-types       what steps can do (registered by features)
    POST /api/approval-workflows/validate         {definition}: check a flow without saving it
    GET  /api/approval-workflows/{id}             one flow, with every version's JSON and where it's used
    POST /api/approval-workflows/{id}/versions    {definition}: publish the next version (code and kind stay)

The JSON format is described in app.workflows.flow. Which flow a node uses is chosen by its feature
(e.g. a repository's owner or admins).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, status
from sqlalchemy import func, select

from app.access import service as access
from app.access.authorization import PlatformAdmin
from app.auth.dependencies import CurrentUser
from app.db.session import Db
from app.sources.models import HierarchyNode
from app.workflows import engine
from app.workflows import flow as flows
from app.workflows.models import WorkflowBinding, WorkflowDefinition, WorkflowVersion
from app.workflows.schemas import (
    FlowCheckOut,
    FlowIn,
    StepTypeOut,
    WorkflowOut,
    WorkflowSummaryOut,
    WorkflowVersionOut,
)

router = APIRouter(prefix="/approval-workflows", tags=["approval workflows"])
WorkflowId = Annotated[uuid.UUID, Path(description="Workflow id")]
_403 = {403: {"description": "Platform admins only"}}


def _summary(db: Db, wf: WorkflowDefinition) -> WorkflowSummaryOut:
    latest = engine.latest_version(db, wf.id)
    used = db.scalar(select(func.count()).select_from(WorkflowBinding).where(
        WorkflowBinding.workflow_definition_id == wf.id, WorkflowBinding.status == "ACTIVE"))
    return WorkflowSummaryOut(
        id=wf.id, code=wf.code, name=wf.name, kind=wf.kind, kind_label=flows.kind_label(wf.kind),
        latest_version=latest.version if latest else 0, last_published_at=latest.published_at if latest else None,
        steps=[{"id": s["id"], "name": s["name"], "type": s["type"]}
               for s in (latest.definition.get("steps", []) if latest else [])],
        used_by=used or 0)


def _version(v: WorkflowVersion) -> WorkflowVersionOut:
    return WorkflowVersionOut(id=v.id, version=v.version, status=v.status, published_at=v.published_at,
                              definition=v.definition)


@router.get("", response_model=list[WorkflowSummaryOut], responses=_403)
@PlatformAdmin
def list_workflows(db: Db) -> list[WorkflowSummaryOut]:
    items = engine.definitions(db)
    db.commit()  # the shipped defaults, if they were just created
    return [_summary(db, wf) for wf in items]


@router.post("", response_model=WorkflowOut, status_code=status.HTTP_201_CREATED,
             responses={**_403, 409: {"description": "That code is taken"}, 422: {"description": "Not valid"}})
@PlatformAdmin
def create_workflow(body: FlowIn, db: Db, p: CurrentUser) -> WorkflowOut:
    version = engine.create_definition(db, body.definition)
    access.record(db, access.require_user(db, p.lan_id), "WORKFLOW_CREATED", "workflow", version.workflow.code, None,
                  {"version": version.version})
    db.commit()
    return get_workflow.guarded_endpoint(version.workflow_definition_id, db)


@router.get("/step-types", response_model=list[StepTypeOut], responses=_403)
@PlatformAdmin
def step_types() -> list[StepTypeOut]:
    return [StepTypeOut(code=t.code, kind=t.kind, kind_label=t.kind_label, outcomes=list(t.outcomes),
                        description=t.description) for t in flows._types.values()]


@router.post("/validate", response_model=FlowCheckOut, responses=_403)
@PlatformAdmin
def validate(body: FlowIn) -> FlowCheckOut:
    """Check a flow without saving it. A problem answers 422 saying what's wrong."""
    flow = flows.parse(body.definition)
    return FlowCheckOut(ok=True, steps=len(flow.steps), start=flow.start, kind=flow.kind)


@router.get("/{workflow_id}", response_model=WorkflowOut, responses=_403)
@PlatformAdmin
def get_workflow(workflow_id: WorkflowId, db: Db) -> WorkflowOut:
    wf = engine.get_definition(db, workflow_id)
    versions = db.scalars(select(WorkflowVersion).where(WorkflowVersion.workflow_definition_id == wf.id)
                          .order_by(WorkflowVersion.version.desc())).all()
    nodes = db.scalars(select(HierarchyNode.name).join(
        WorkflowBinding, WorkflowBinding.hierarchy_node_id == HierarchyNode.id).where(
        WorkflowBinding.workflow_definition_id == wf.id, WorkflowBinding.status == "ACTIVE")
        .order_by(HierarchyNode.name)).all()
    return WorkflowOut(**_summary(db, wf).model_dump(), versions=[_version(v) for v in versions],
                       used_by_nodes=list(nodes))


@router.post("/{workflow_id}/versions", response_model=WorkflowVersionOut, status_code=status.HTTP_201_CREATED,
             responses={**_403, 422: {"description": "Not valid"}})
@PlatformAdmin
def publish(workflow_id: WorkflowId, body: FlowIn, db: Db, p: CurrentUser) -> WorkflowVersionOut:
    previous = engine.latest_version(db, workflow_id)
    version = engine.publish_version(db, workflow_id, body.definition)
    access.record(db, access.require_user(db, p.lan_id), "WORKFLOW_PUBLISHED", "workflow", version.workflow.code, None,
                  {"version": version.version,
                   "steps": engine.steps_changed(previous.definition if previous else None, body.definition)})
    db.commit()
    return _version(version)
