"""Generic workflow endpoints: inbox, task completion, history, definitions."""

import json

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, Db, require
from app.core.permissions import Perm
from app.db.models import User
from app.schemas.workflow import DefinitionOut, InboxTaskOut, InstanceOut, TaskComplete, TaskOut
from app.workflow import service as workflow
from app.workflow.handlers import get_handler
from app.workflow.models import WorkflowDefinition, WorkflowInstance, WorkflowTask

router = APIRouter(prefix="/workflow", tags=["workflow"])


def _task(t: WorkflowTask, users: dict[int, str]) -> TaskOut:
    return TaskOut(
        id=t.id, name=t.name, title=t.title, lane=t.lane, status=t.status, created_at=t.created_at,
        completed_by=users.get(t.completed_by_id) if t.completed_by_id else None,
        completed_at=t.completed_at, data=json.loads(t.data) if t.data else None,
    )


def _lan_ids(db, ids) -> dict[int, str]:
    ids = {i for i in ids if i}
    return dict(db.execute(select(User.id, User.lan_id).where(User.id.in_(ids))).all()) if ids else {}


def _instance(i: WorkflowInstance, users: dict[int, str]) -> InstanceOut:
    return InstanceOut(
        id=i.id, workflow=f"{i.definition.key}@v{i.definition.version}", engine=i.definition.engine,
        subject_type=i.subject_type, subject_id=i.subject_id, status=i.status,
        outcome=json.loads(i.outcome) if i.outcome else None,
        started_at=i.started_at, completed_at=i.completed_at, tasks=[_task(t, users) for t in i.tasks],
    )


@router.get("/tasks", response_model=list[InboxTaskOut])
def my_tasks(p: CurrentUser, db: Db) -> list[InboxTaskOut]:
    """Your inbox: ready tasks in your roles' lanes that you're allowed to complete."""
    out = []
    for t in workflow.inbox(db, p):
        i = t.instance
        out.append(InboxTaskOut(
            **_task(t, {}).model_dump(), instance_id=i.id, subject_type=i.subject_type, subject_id=i.subject_id,
            subject=get_handler(i.subject_type).describe(db, i.subject_id),
            workflow=f"{i.definition.key}@v{i.definition.version}",
        ))
    return out


@router.post("/tasks/{task_id}/complete", response_model=InstanceOut)
def complete_task(task_id: int, body: TaskComplete, p: CurrentUser, db: Db) -> InstanceOut:
    """Complete a task with data. The subject's rules decide who may and what data is valid."""
    instance = workflow.complete_task(db, task_id, p, body.data)
    db.commit()
    db.refresh(instance)
    return _instance(instance, _lan_ids(db, [t.completed_by_id for t in instance.tasks]))


@router.get("/subjects/{subject_type}/{subject_id}/instances", response_model=list[InstanceOut])
def subject_history(subject_type: str, subject_id: str, p: CurrentUser, db: Db) -> list[InstanceOut]:
    """Every workflow run for a subject (e.g. document 5), newest first."""
    instances = workflow.history(db, p, subject_type, subject_id)
    users = _lan_ids(db, [t.completed_by_id for i in instances for t in i.tasks])
    return [_instance(i, users) for i in instances]


@router.get("/definitions", response_model=list[DefinitionOut], dependencies=[require(Perm.WORKFLOWS_VIEW)])
def definitions(db: Db) -> list[DefinitionOut]:
    """All workflow definitions and versions (system admins)."""
    rows = db.scalars(select(WorkflowDefinition).order_by(WorkflowDefinition.key, WorkflowDefinition.version.desc()))
    return [
        DefinitionOut(
            id=d.id, key=d.key, version=d.version, name=d.name, description=d.description, engine=d.engine,
            is_active=d.is_active, has_source=bool(d.source), source_filename=d.source_filename,
            created_at=d.created_at,
        )
        for d in rows
    ]
