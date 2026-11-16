"""Running flows, and managing their definitions and bindings. Callers commit.

    start(...)        a new instance for a subject, at a node, on the flow bound there; runs the start step
    signal(...)       someone acts on the active step (e.g. resubmits after changes were requested)
    complete(...)     a waiting step has its outcome (e.g. a review was decided)
    cancel(...)       stop an instance

A step's outcome follows its "on": to another step (going back to one already run starts a new round)
or to END:<WORD>, which completes the instance and tells the listeners for its subject type.
"""

import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.audit.catalog import register_actions
from app.core.errors import Conflict, InvalidRequest, NotFound
from app.db.base import utcnow
from app.workflows import flow as flows
from app.workflows.models import (
    InstanceStatus,
    StepInstance,
    StepStatus,
    VersionStatus,
    WorkflowBinding,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowVersion,
)

register_actions("WORKFLOWS", {
    "WORKFLOW_CREATED": ("configuration", "Workflow created"),
    "WORKFLOW_DEFAULT_CREATED": ("configuration", "Default workflow set up", "A feature's shipped workflow was "
                                                                             "created automatically."),
    "WORKFLOW_PUBLISHED": ("configuration", "Workflow version published"),
    "REPO_WORKFLOW_SET": ("configuration", "Workflow changed", "A node (e.g. a repository) switched workflow."),
})


def steps_changed(before: dict[str, Any] | None, after: dict[str, Any]) -> dict[str, Any]:
    """Which steps a new version adds, removes or changes (by step id), for the audit trail."""
    old = {s["id"]: s for s in (before or {}).get("steps", [])}
    new = {s["id"]: s for s in after.get("steps", [])}
    return {"added": sorted(set(new) - set(old)), "removed": sorted(set(old) - set(new)),
            "changed": sorted(k for k in set(old) & set(new) if old[k] != new[k]),
            "start": after.get("start") if (before or {}).get("start") != after.get("start") else None}


# (db, instance, the END word e.g. "APPROVED", actor, data). Registered per subject type.
EndListener = Callable[[Session, WorkflowInstance, str, Any, dict[str, Any]], None]
_end_listeners: dict[str, EndListener] = {}


def on_end(subject_type: str, listener: EndListener) -> EndListener:
    _end_listeners[subject_type] = listener
    return listener


# --------------------------------------------------------------------------- definitions and bindings


def flow_of(version: WorkflowVersion) -> flows.Flow:
    return flows.Flow.model_validate(version.definition)


def latest_version(db: Session, definition_id: uuid.UUID) -> WorkflowVersion | None:
    return db.scalar(select(WorkflowVersion).where(
        WorkflowVersion.workflow_definition_id == definition_id, WorkflowVersion.status == VersionStatus.PUBLISHED.value)
        .order_by(WorkflowVersion.version.desc()))


def create_definition(db: Session, definition: dict[str, Any], name: str | None = None) -> WorkflowVersion:
    """A new flow, published as version 1."""
    flow = flows.parse(definition)
    if db.scalar(select(WorkflowDefinition.id).where(WorkflowDefinition.code == flow.code)):
        raise Conflict(f"There's already a workflow {flow.code}.")
    wf = WorkflowDefinition(code=flow.code, name=name or flow.name or flow.code, kind=flow.kind)
    db.add(wf)
    db.flush()
    return _publish(db, wf, definition)


def publish_version(db: Session, definition_id: uuid.UUID, definition: dict[str, Any]) -> WorkflowVersion:
    """The flow's next version. Its code and kind can't change. Running instances keep theirs."""
    wf = get_definition(db, definition_id)
    flow = flows.parse(definition)
    if flow.code != wf.code:
        raise InvalidRequest(f'The flow\'s "code" must stay {wf.code}.')
    if flow.kind != wf.kind:
        raise InvalidRequest(f"The flow's steps must stay of kind {wf.kind}.")
    if flow.name:
        wf.name = flow.name
    wf.updated_at = utcnow()
    return _publish(db, wf, definition)


def _publish(db: Session, wf: WorkflowDefinition, definition: dict[str, Any]) -> WorkflowVersion:
    latest = db.scalar(select(func.max(WorkflowVersion.version)).where(WorkflowVersion.workflow_definition_id == wf.id))
    version = WorkflowVersion(workflow_definition_id=wf.id, version=(latest or 0) + 1, definition=definition,
                              status=VersionStatus.PUBLISHED.value, published_at=utcnow())
    db.add(version)
    db.flush()
    return version


def ensure_definition(db: Session, definition: dict[str, Any], name: str | None = None) -> WorkflowDefinition:
    """The flow with this code; created (as version 1) the first time. Never changes an existing one."""
    code = definition.get("code")
    wf = db.scalar(select(WorkflowDefinition).where(WorkflowDefinition.code == code))
    if wf is None:
        wf = create_definition(db, definition, name).workflow
        audit.record(db, "WORKFLOW_DEFAULT_CREATED", target=("workflow", wf.code), details={"name": wf.name})
    return wf


def get_definition(db: Session, definition_id: uuid.UUID) -> WorkflowDefinition:
    wf = db.get(WorkflowDefinition, definition_id)
    if wf is None:
        raise NotFound("No such workflow.")
    return wf


def bind(db: Session, node_id: uuid.UUID, definition_id: uuid.UUID, actor_id: uuid.UUID | None = None) -> WorkflowBinding:
    """Make the node use this flow for subjects of its kind (replacing what it used)."""
    wf = get_definition(db, definition_id)
    if latest_version(db, wf.id) is None:
        raise Conflict(f"{wf.name} has no published version.")
    for old in db.scalars(select(WorkflowBinding).where(
            WorkflowBinding.hierarchy_node_id == node_id, WorkflowBinding.kind == wf.kind,
            WorkflowBinding.status == "ACTIVE")):
        if old.workflow_definition_id == wf.id:
            return old
        old.status = "INACTIVE"
    db.flush()
    binding = WorkflowBinding(hierarchy_node_id=node_id, kind=wf.kind, workflow_definition_id=wf.id, bound_by_id=actor_id)
    db.add(binding)
    db.flush()
    return binding


def bound_definition(db: Session, node_id: uuid.UUID, kind: str) -> WorkflowDefinition | None:
    binding = db.scalar(select(WorkflowBinding).where(
        WorkflowBinding.hierarchy_node_id == node_id, WorkflowBinding.kind == kind, WorkflowBinding.status == "ACTIVE"))
    return db.get(WorkflowDefinition, binding.workflow_definition_id) if binding else None


def ensure_defaults(db: Session) -> None:
    """Create the flows features ship with, if they aren't there yet."""
    for definition in flows.default_flows():
        ensure_definition(db, definition)


def definitions(db: Session, kind: str | None = None) -> list[WorkflowDefinition]:
    ensure_defaults(db)
    query = select(WorkflowDefinition).order_by(WorkflowDefinition.name)
    return list(db.scalars(query.where(WorkflowDefinition.kind == kind) if kind else query))


# --------------------------------------------------------------------------- running


def start(db: Session, node_id: uuid.UUID, kind: str, subject_type: str, subject_id: str, actor: Any,
          data: dict[str, Any] | None = None) -> WorkflowInstance:
    """Start the flow bound at the node for this kind, on its latest version, and run its start step."""
    wf = bound_definition(db, node_id, kind)
    if wf is None:
        raise Conflict("No workflow is set up here.")
    version = latest_version(db, wf.id)
    instance = WorkflowInstance(workflow_version_id=version.id, subject_type=subject_type, subject_id=subject_id,
                                hierarchy_node_id=node_id)
    db.add(instance)
    db.flush()
    _enter(db, instance, flow_of(version).start, actor, data or {})
    return instance


def instance_for(db: Session, subject_type: str, subject_id: str) -> WorkflowInstance | None:
    """The subject's latest instance."""
    return db.scalars(select(WorkflowInstance).where(
        WorkflowInstance.subject_type == subject_type, WorkflowInstance.subject_id == subject_id)
        .order_by(WorkflowInstance.created_at.desc())).first()


def active_step(db: Session, instance: WorkflowInstance) -> StepInstance | None:
    return db.scalar(select(StepInstance).where(StepInstance.workflow_instance_id == instance.id,
                                                StepInstance.status == StepStatus.ACTIVE.value))


def signal(db: Session, instance: WorkflowInstance, actor: Any, data: dict[str, Any] | None = None) -> None:
    """Someone acts on the active step (its step type decides what that means)."""
    si = active_step(db, instance)
    if si is None or instance.status != InstanceStatus.RUNNING.value:
        raise Conflict("Nothing is waiting here.")
    flow = flow_of(instance.version)
    step = flow.step(si.step_id)
    st = flows.step_type(step.type)
    if st.signal is None:
        raise Conflict(f"{step.name} doesn't take that.")
    outcome = st.signal(db, flows.StepContext(instance, step, si, actor, data or {}))
    if outcome is not None:
        _done(db, instance, step, si, outcome, actor, data or {})


def complete(db: Session, step_instance_id: uuid.UUID, outcome: str, actor: Any,
             data: dict[str, Any] | None = None) -> WorkflowInstance:
    """The waiting step has its outcome (e.g. a review was decided): follow the flow on."""
    si = db.get(StepInstance, step_instance_id)
    if si is None or si.status != StepStatus.ACTIVE.value:
        raise Conflict("That step isn't waiting.")
    instance = si.instance
    step = flow_of(instance.version).step(si.step_id)
    if outcome not in step.on:
        raise InvalidRequest(f"{step.name} can't end with {outcome}.")
    _done(db, instance, step, si, outcome, actor, data or {})
    return instance


def cancel(db: Session, instance: WorkflowInstance) -> None:
    for si in db.scalars(select(StepInstance).where(StepInstance.workflow_instance_id == instance.id,
                                                    StepInstance.status == StepStatus.ACTIVE.value)):
        si.status, si.completed_at = StepStatus.CANCELLED.value, utcnow()
    instance.status, instance.current_step = InstanceStatus.CANCELLED.value, None


def _enter(db: Session, instance: WorkflowInstance, step_id: str, actor: Any, data: dict[str, Any]) -> None:
    flow = flow_of(instance.version)
    step = flow.step(step_id)
    reentry = db.scalar(select(StepInstance.id).where(
        StepInstance.workflow_instance_id == instance.id, StepInstance.round == instance.round,
        StepInstance.step_id == step_id)) is not None
    if reentry:
        instance.round += 1
    si = StepInstance(workflow_instance_id=instance.id, round=instance.round, step_id=step.id, step_type=step.type)
    db.add(si)
    db.flush()
    instance.current_step = step.id
    outcome = flows.step_type(step.type).enter(db, flows.StepContext(instance, step, si, actor, data, reentry))
    if outcome is not None:
        _done(db, instance, step, si, outcome, actor, data)


def _done(db: Session, instance: WorkflowInstance, step: flows.Step, si: StepInstance, outcome: str, actor: Any,
          data: dict[str, Any]) -> None:
    si.status, si.outcome, si.completed_at = StepStatus.COMPLETED.value, outcome, utcnow()
    target = step.on[outcome]
    if flows.END.match(target):
        instance.status, instance.current_step = InstanceStatus.COMPLETED.value, None
        instance.outcome = target.removeprefix("END:")
        listener = _end_listeners.get(instance.subject_type)
        if listener:
            listener(db, instance, instance.outcome, actor, {**data, "reason": si.detail.get("reason", "")})
        return
    _enter(db, instance, target, actor, data)
