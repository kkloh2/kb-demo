"""The workflow module's public interface.

Functions here never commit: the caller owns the transaction, so starting a workflow and
saving the subject (e.g. an uploaded document) succeed or fail together.
"""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import utcnow
from app.services import audit
from app.services.errors import Conflict, Forbidden, InvalidRequest, NotFound
from app.workflow.engine import EngineSnapshot, get_engine
from app.workflow.handlers import Actor, get_handler
from app.workflow.models import WorkflowDefinition, WorkflowInstance, WorkflowTask

# Definitions every installation starts with. Uploaded definitions become new versions.
BUILTIN_DEFINITIONS = [
    {
        "key": "document_approval",
        "engine": "builtin.single_review",
        "name": "Document approval",
        "description": "A checker from the maker's department approves or rejects each uploaded document.",
    },
]


def ensure_builtin_definitions(db: Session) -> None:
    """Create version 1 of each built-in definition if its key has no versions yet."""
    for d in BUILTIN_DEFINITIONS:
        if db.scalar(select(WorkflowDefinition.id).where(WorkflowDefinition.key == d["key"])) is None:
            db.add(WorkflowDefinition(version=1, is_active=True, **d))
    db.flush()


def active_definition(db: Session, key: str) -> WorkflowDefinition:
    d = db.scalar(
        select(WorkflowDefinition).where(WorkflowDefinition.key == key, WorkflowDefinition.is_active.is_(True))
    )
    if d is None:
        raise LookupError(f"No active workflow definition for '{key}'.")
    return d


# --------------------------------------------------------------------------- running


def start(
    db: Session, subject_type: str, subject_id: str | int, context: dict[str, Any], actor: Actor | None = None
) -> WorkflowInstance:
    """Start the active workflow for a subject and record its first tasks."""
    handler = get_handler(subject_type)
    definition = active_definition(db, handler.definition_key)
    snapshot = get_engine(definition.engine).start(definition.source, context)
    instance = WorkflowInstance(
        definition_id=definition.id,
        subject_type=subject_type,
        subject_id=str(subject_id),
        state=json.dumps(snapshot.state),
        started_by_id=actor.user_id if actor else None,
    )
    db.add(instance)
    db.flush()
    audit.record(db, "workflow.start", actor_id=actor.user_id if actor else None,
                 actor_lan_id=actor.lan_id if actor else None, target_type="workflow_instance",
                 target_id=instance.id,
                 detail={"definition": f"{definition.key}@v{definition.version}", "subject": f"{subject_type}:{subject_id}"})
    _apply(db, instance, snapshot, actor)
    return instance


def complete_task(
    db: Session, task_id: int, actor: Actor, data: dict[str, Any], *, check_permission: bool = True
) -> WorkflowInstance:
    """Complete a ready task. The subject's handler decides who may and what data is valid."""
    task = db.scalar(
        select(WorkflowTask)
        .where(WorkflowTask.id == task_id)
        .options(selectinload(WorkflowTask.instance).selectinload(WorkflowInstance.definition))
    )
    if task is None:
        raise NotFound("Task not found.")
    instance = task.instance
    handler = get_handler(instance.subject_type)
    if check_permission:
        handler.authorize(db, actor, task, instance)
    if task.status != "ready":
        raise Conflict("This task has already been completed.")
    clean = handler.validate(task, data)

    engine = get_engine(instance.definition.engine)
    try:
        snapshot = engine.complete(json.loads(instance.state), task.engine_task_id, clean)
    except ValueError as e:
        raise InvalidRequest(str(e)) from None

    task.status = "completed"
    task.data = json.dumps(clean)
    task.completed_by_id = actor.user_id
    task.completed_at = utcnow()
    audit.record(db, "workflow.task.complete", actor_id=actor.user_id, actor_lan_id=actor.lan_id,
                 target_type="workflow_task", target_id=task.id,
                 detail={"instance": instance.id, "task": task.name, "data": clean})
    _apply(db, instance, snapshot, actor)
    return instance


def _apply(db: Session, instance: WorkflowInstance, snapshot: EngineSnapshot, actor: Actor | None) -> None:
    """Store the engine's new state and bring workflow_tasks in line with its ready tasks."""
    instance.state = json.dumps(snapshot.state)
    open_tasks = {t.engine_task_id: t for t in instance.tasks if t.status == "ready"}
    ready_ids = {t.id for t in snapshot.ready}
    for engine_id, t in open_tasks.items():
        if engine_id not in ready_ids:  # the engine moved past it (e.g. a parallel branch ended)
            t.status = "cancelled"
    for t in snapshot.ready:
        if t.id not in open_tasks:
            instance.tasks.append(
                WorkflowTask(engine_task_id=t.id, name=t.name, title=t.title, lane=t.lane)
            )

    if snapshot.completed:
        instance.status = "completed"
        instance.outcome = json.dumps(snapshot.outcome)
        instance.completed_at = utcnow()
        audit.record(db, "workflow.complete", actor_id=actor.user_id if actor else None,
                     actor_lan_id=actor.lan_id if actor else None, target_type="workflow_instance",
                     target_id=instance.id, detail={"outcome": snapshot.outcome})
        db.flush()
        get_handler(instance.subject_type).on_completed(db, instance, snapshot.outcome, actor)
    db.flush()


# --------------------------------------------------------------------------- queries


def open_task_for(db: Session, subject_type: str, subject_id: str | int, lane: str | None = None) -> WorkflowTask | None:
    """The oldest ready task on a subject's running workflow (optionally in one lane)."""
    q = (
        select(WorkflowTask)
        .join(WorkflowInstance)
        .where(
            WorkflowInstance.subject_type == subject_type,
            WorkflowInstance.subject_id == str(subject_id),
            WorkflowInstance.status == "running",
            WorkflowTask.status == "ready",
        )
        .order_by(WorkflowTask.id)
    )
    if lane:
        q = q.where(WorkflowTask.lane == lane)
    return db.scalars(q).first()


def has_instance(db: Session, subject_type: str, subject_id: str | int) -> bool:
    return db.scalar(
        select(WorkflowInstance.id).where(
            WorkflowInstance.subject_type == subject_type, WorkflowInstance.subject_id == str(subject_id)
        ).limit(1)
    ) is not None


def inbox(db: Session, actor: Actor) -> list[WorkflowTask]:
    """Ready tasks in the actor's lanes (roles) that their handler lets them complete."""
    lanes = [str(r) for r in actor.roles]
    candidates = db.scalars(
        select(WorkflowTask)
        .join(WorkflowInstance)
        .where(WorkflowTask.status == "ready", WorkflowTask.lane.in_(lanes), WorkflowInstance.status == "running")
        .options(selectinload(WorkflowTask.instance).selectinload(WorkflowInstance.definition))
        .order_by(WorkflowTask.created_at)
    ).all()
    allowed = []
    for t in candidates:
        try:
            get_handler(t.instance.subject_type).authorize(db, actor, t, t.instance)
        except (Forbidden, NotFound):
            continue
        allowed.append(t)
    return allowed


def history(db: Session, actor: Actor, subject_type: str, subject_id: str) -> list[WorkflowInstance]:
    """Every workflow run for a subject, newest first, with its tasks."""
    if not get_handler(subject_type).can_view(db, actor, subject_id):
        raise NotFound("Not found.")
    return list(db.scalars(
        select(WorkflowInstance)
        .where(WorkflowInstance.subject_type == subject_type, WorkflowInstance.subject_id == subject_id)
        .options(selectinload(WorkflowInstance.tasks), selectinload(WorkflowInstance.definition))
        .order_by(WorkflowInstance.id.desc())
    ))
