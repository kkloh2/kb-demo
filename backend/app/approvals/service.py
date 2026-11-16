"""CAMS: approval requests, tasks, the inbox and decisions. Each request runs a standalone workflow
instance (app.workflows), started on the flow bound at its resource's node; the flow's steps are
step types the source system registers, built from what this module offers them:

    open_review(...)         a review step: a task for the people holding a role in a named user group
    holds_role_in_group(...) a check step: does the submitter hold a role in a named user group?

    request_approval   submit: a new request starts its flow; after changes were requested, the same
                       request's flow is signalled again (the flow decides what that means)
    inbox / inbox_item tasks the person may decide (their own assignee rows); never their own work
    decide             APPROVED, REJECTED or CHANGES_REQUESTED: completes the task's step; the flow moves on
    cancel_subject / set_resource_active   withdraw requests when their subject or resource goes

When the flow ends, its END word is the request's outcome (APPROVED, REJECTED); any other END refuses
the submission (Refused). The feature reacts through ApprovalKind.on_decided. Callers commit unless
a function says it commits.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session, aliased, selectinload

from app.access import service as access
from app.access.catalog import RoleCode
from app.access.models import AppUser, HierarchyNode, SourceSystem
from app.approvals.hooks import ApprovalKind, kind_of, kinds
from app.approvals.models import (
    ApprovalDecision,
    ApprovalEvent,
    ApprovalRequest,
    ApprovalTask,
    ApprovalTaskAssignee,
    ApprovalTaskAssignment,
    ApprovalType,
    AssignmentStatus,
    Decision,
    RequestStatus,
    Resource,
    TaskStatus,
)
from app.audit import service as audit
from app.audit.catalog import register_actions
from app.core.errors import Conflict, InvalidRequest, NotFound
from app.db.base import utcnow
from app.workflows import engine
from app.workflows.models import InstanceStatus, StepInstance

SUBJECT = "APPROVAL_REQUEST"  # what approvals' workflow instances run for

register_actions("APPROVALS", {
    "APPROVAL_SUBMITTED": ("approval", "Sent for approval", "Submitted, or resubmitted after changes (a new round)."),
    "APPROVAL_REFUSED": ("approval", "Submission refused", "The workflow refused it, e.g. not a maker in its group."),
    "APPROVAL_DECIDED": ("approval", "Decision recorded", "A reviewer approved, rejected or requested changes."),
    "APPROVAL_COMPLETED": ("approval", "Approval completed", "The request ended approved or rejected."),
    "APPROVAL_CANCELLED": ("approval", "Approval cancelled", "Withdrawn, e.g. the document or repository was deleted."),
})


def _audit(db: Session, code: str, request: ApprovalRequest, actor: AppUser | None, **details: Any) -> None:
    """An approvals summary event at the request's resource node (its full history stays in approval_event)."""
    resource = db.get(Resource, request.resource_pk)
    audit.record(db, code, actor=actor, target=(request.subject_type, request.subject_id),
                 node_id=resource.hierarchy_node_id if resource else None, source_system="APPROVALS",
                 details={"title": request.title, "request": str(request.id), "round": request.current_round,
                          **details})

OPEN = (RequestStatus.PENDING.value, RequestStatus.CHANGES_REQUESTED.value)


# --------------------------------------------------------------------------- set-up


def _system_id(db: Session, code: str) -> uuid.UUID:
    return db.scalar(select(SourceSystem.id).where(SourceSystem.code == str(code)))


def sync_types(db: Session) -> None:
    """An approval_type row for every registered kind whose source system exists. Runs at start-up
    (and a missing one is added when first needed); the caller commits."""
    for kind in kinds():
        system_id = _system_id(db, kind.system)
        if system_id is None:  # the system isn't created yet
            continue
        row = db.scalar(select(ApprovalType).where(ApprovalType.source_system_id == system_id,
                                                   ApprovalType.code == kind.type_code))
        if row is None:
            row = ApprovalType(source_system_id=system_id, code=kind.type_code, name=kind.name)
            db.add(row)
            db.flush()
        else:
            row.name = kind.name


def _type(db: Session, kind: ApprovalKind) -> ApprovalType:
    system_id = _system_id(db, kind.system)
    row = db.scalar(select(ApprovalType).where(ApprovalType.source_system_id == system_id,
                                               ApprovalType.code == kind.type_code))
    if row is None:  # the source system was created after start-up
        row = ApprovalType(source_system_id=system_id, code=kind.type_code, name=kind.name)
        db.add(row)
        db.flush()
    return row


def _resource(db: Session, system: str, resource_type: str, resource_id: str) -> Resource | None:
    return db.scalar(select(Resource).where(Resource.source_system_id == _system_id(db, system),
                                            Resource.resource_type == resource_type,
                                            Resource.resource_id == resource_id))


def register_resource(db: Session, system: str, resource_type: str, resource_id: str, name: str,
                      node_id: uuid.UUID) -> Resource:
    """Register (or re-activate) a resource at its node. The caller commits."""
    resource = _resource(db, system, resource_type, resource_id)
    if resource is None:
        resource = Resource(source_system_id=_system_id(db, system), resource_type=resource_type,
                            resource_id=resource_id, name=name, hierarchy_node_id=node_id)
        db.add(resource)
    resource.name, resource.status, resource.hierarchy_node_id = name, "ACTIVE", node_id
    db.flush()
    return resource


def rename_resource(db: Session, system: str, resource_type: str, resource_id: str, name: str) -> None:
    resource = _resource(db, system, resource_type, resource_id)
    if resource is not None:
        resource.name = name


def set_resource_active(db: Session, system: str, resource_type: str, resource_id: str, active: bool,
                        actor: AppUser) -> int:
    """Activate or deactivate a resource. Deactivating cancels its open requests. Returns how many
    were cancelled. The caller commits."""
    resource = _resource(db, system, resource_type, resource_id)
    if resource is None:
        return 0
    resource.status = "ACTIVE" if active else "INACTIVE"
    if active:
        return 0
    requests = db.scalars(select(ApprovalRequest).where(ApprovalRequest.resource_pk == resource.id,
                                                        ApprovalRequest.status.in_(OPEN)))
    return sum(_cancel(db, r, actor, "The repository was deleted.") for r in requests)


# --------------------------------------------------------------------------- submitting


def _event(db: Session, request: ApprovalRequest, event_type: str, actor: AppUser | None,
           data: dict[str, Any] | None = None, task: ApprovalTask | None = None) -> None:
    request.last_event_sequence += 1
    db.add(ApprovalEvent(approval_request_id=request.id, approval_task_id=task.id if task else None,
                         event_type=event_type, actor_id=actor.id if actor else None, event_data=data or {},
                         event_sequence=request.last_event_sequence))


def task_metadata(kind: ApprovalKind, request: ApprovalRequest, resource: Resource, submitter: AppUser,
                  extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """What lists show for a task, stored on it so they never look anything else up."""
    return {
        "type": kind.type_code, "type_label": kind.label, "title": request.title, "round": request.current_round,
        "submitted_by": {"lan_id": submitter.lan_id, "display_name": submitter.display_name},
        "submitted_at": utcnow().isoformat(),
        "resource": {"type": resource.resource_type, "id": resource.resource_id, "name": resource.name},
        "subject": {"type": request.subject_type, "id": request.subject_id},
        **(extra or {}),
    }


class Refused(Conflict):
    """A CHECK step failed and the flow says END:REFUSED: the submission isn't accepted."""


def _resource_node(db: Session, request: ApprovalRequest) -> HierarchyNode:
    resource = db.get(Resource, request.resource_pk)
    if resource is None or resource.status != "ACTIVE":
        raise Conflict("This repository isn't set up for approvals.")
    return db.get(HierarchyNode, resource.hierarchy_node_id)


def request_of(db: Session, instance) -> ApprovalRequest:
    """The approval request a workflow instance runs for."""
    return db.get(ApprovalRequest, uuid.UUID(instance.subject_id))


# --------------------------------------------------------------------------- what step types are built from


def holds_role_in_group(db: Session, user: AppUser, node_id: uuid.UUID, group_name: str, role: str) -> str | None:
    """None when the person holds the role in the node's user group of that name; else why not."""
    node = db.get(HierarchyNode, node_id)
    group = access.group_named(db, node_id, group_name)
    if group is None:
        return f"{node.name} has no user group named {group_name}."
    if not access.holds_in_group(db, user.id, group.id, role):
        return f"{user.display_name} needs the {role.title()} role in {node.name}'s {group.name} user group."
    return None


def open_review(db: Session, request: ApprovalRequest, si: StepInstance, step_name: str, group_name: str, role: str,
                data: dict[str, Any]) -> ApprovalTask:
    """A review step: a task for the active members of the node's user group `group_name` who hold
    `role` there (never the maker or whoever submitted). `data` carries the snapshot and list metadata."""
    node_id = si.instance.hierarchy_node_id
    group = access.group_named(db, node_id, group_name)
    if group is None:
        raise Refused(f"{db.get(HierarchyNode, node_id).name} has no user group named {group_name}.")
    request.current_round = si.round
    task = ApprovalTask(approval_request_id=request.id, step_instance_id=si.id, round=si.round,
                        subject_snapshot=data.get("snapshot", {}),
                        task_metadata={**data.get("metadata", {}), "round": si.round,
                                       "step": {"id": si.step_id, "name": step_name}})
    db.add(task)
    db.flush()
    db.add(ApprovalTaskAssignment(approval_task_id=task.id, group_id=group.id, hierarchy_node_id=node_id,
                                  required_role_id=access.role_ids(db)[role]))
    _event(db, request, "TASK_CREATED", None, {"round": si.round, "step": si.step_id}, task)
    _sync_assignees(db, _assignment(db, task.id))
    return task


def on_flow_end(db: Session, instance, outcome: str, actor: AppUser | None, data: dict[str, Any]) -> None:
    """The request's flow reached END:<outcome> (registered with the workflow engine in app.main).
    APPROVED / REJECTED settle the request; anything else refuses the submission."""
    request = request_of(db, instance)
    if outcome not in (RequestStatus.APPROVED.value, RequestStatus.REJECTED.value):
        raise Refused(data.get("reason") or f"It wasn't accepted ({outcome.replace('_', ' ').lower()}).")
    request.status, request.completed_at = outcome, utcnow()
    _event(db, request, f"REQUEST_{outcome}", actor, {"round": request.current_round})
    _audit(db, "APPROVAL_COMPLETED", request, actor, outcome=outcome)
    kind_of(db.get(ApprovalType, request.approval_type_id).code).on_decided(db, request, outcome, actor, None)


# --------------------------------------------------------------------------- who each task is assigned to


def _excluded(db: Session, request: ApprovalRequest) -> set[uuid.UUID]:
    """Who never decides the request: its maker, whoever asked, and whoever submitted any round."""
    submitters = db.scalars(select(ApprovalEvent.actor_id).where(
        ApprovalEvent.approval_request_id == request.id, ApprovalEvent.actor_id.is_not(None),
        ApprovalEvent.event_type.in_(["REQUEST_SUBMITTED", "REQUEST_RESUBMITTED"])))
    return {request.requested_by, *([request.maker_id] if request.maker_id else []), *submitters}


def _role_code(db: Session, role_id: uuid.UUID) -> str:
    return {rid: code for code, rid in access.role_ids(db).items()}[role_id]


def _sync_assignees(db: Session, assignment: ApprovalTaskAssignment) -> None:
    """Make the task's ACTIVE assignee rows exactly the people who may decide it now: active users
    holding the required role in the assignment's user group (or, for older tasks without one, at the
    node), less those excluded. Closed tasks keep none."""
    task = db.get(ApprovalTask, assignment.approval_task_id)
    rows = {r.user_id: r for r in db.scalars(select(ApprovalTaskAssignee).where(
        ApprovalTaskAssignee.approval_task_id == task.id))}
    wanted: set[uuid.UUID] = set()
    if task.status == TaskStatus.PENDING.value and assignment.status == AssignmentStatus.ACTIVE.value:
        role = _role_code(db, assignment.required_role_id)
        holders = (access.holders_in_group(db, assignment.group_id, role) if assignment.group_id
                   else access.holders_of(db, assignment.hierarchy_node_id, RoleCode(role)))
        wanted = {u.id for u in holders if u.status == "ACTIVE"} - _excluded(db, task.request)
    for user_id, row in rows.items():
        if user_id not in wanted and row.status == AssignmentStatus.ACTIVE.value:
            row.status = AssignmentStatus.CLOSED.value
    for user_id in wanted:
        row = rows.get(user_id)
        if row is None:
            db.add(ApprovalTaskAssignee(approval_task_id=task.id, user_id=user_id))
        elif row.status != AssignmentStatus.ACTIVE.value:
            row.status, row.assigned_at = AssignmentStatus.ACTIVE.value, utcnow()
    db.flush()


def _close_assignees(db: Session, task_id: uuid.UUID) -> None:
    db.execute(update(ApprovalTaskAssignee).where(ApprovalTaskAssignee.approval_task_id == task_id,
                                                  ApprovalTaskAssignee.status == AssignmentStatus.ACTIVE.value)
               .values(status=AssignmentStatus.CLOSED.value, updated_at=utcnow()))


def on_roles_changed(db: Session, node_id: uuid.UUID | None, user_id: uuid.UUID | None) -> None:
    """Roles changed (access.on_roles_changed): re-work who the affected waiting tasks are assigned to.
    A node: its open assignments. A user: open assignments where they hold a role or are assigned."""
    query = select(ApprovalTaskAssignment).where(ApprovalTaskAssignment.status == AssignmentStatus.ACTIVE.value)
    if node_id is not None:
        assignments = db.scalars(query.where(ApprovalTaskAssignment.hierarchy_node_id == node_id)).all()
    elif user_id is not None:
        held = access.held_roles(user_id)
        mine = select(ApprovalTaskAssignee.approval_task_id).where(
            ApprovalTaskAssignee.user_id == user_id, ApprovalTaskAssignee.status == AssignmentStatus.ACTIVE.value)
        assignments = db.scalars(query.where(or_(
            ApprovalTaskAssignment.hierarchy_node_id.in_(select(held.c.node_id)),
            ApprovalTaskAssignment.approval_task_id.in_(mine)))).all()
    else:
        return
    for assignment in assignments:
        _sync_assignees(db, assignment)


def _assignment(db: Session, task_id: uuid.UUID) -> ApprovalTaskAssignment:
    db.flush()
    return db.scalar(select(ApprovalTaskAssignment).where(ApprovalTaskAssignment.approval_task_id == task_id))


# --------------------------------------------------------------------------- submitting


def open_request(db: Session, subject_type: str, subject_id: str) -> ApprovalRequest | None:
    return db.scalar(select(ApprovalRequest).where(
        ApprovalRequest.subject_type == subject_type, ApprovalRequest.subject_id == subject_id,
        ApprovalRequest.status.in_(OPEN)))


def request_approval(db: Session, type_code: str, *, resource_id: str, subject_id: str, title: str,
                     payload: dict[str, Any], snapshot: dict[str, Any], requester: AppUser,
                     maker: AppUser | None = None, listing: dict[str, Any] | None = None) -> ApprovalRequest:
    """Submit the subject for approval. A new request starts the flow bound at its resource's node
    (pinned to its latest version); after changes were requested, the same request's flow is signalled
    again. `maker`: who made the subject (default: the requester); they never decide it. `listing`:
    what the module adds to tasks' metadata for lists. Raises Refused when the flow refuses it.
    The caller commits."""
    kind = kind_of(type_code)
    resource = _resource(db, kind.system, kind.resource_type, resource_id)
    if resource is None or resource.status != "ACTIVE":
        raise Conflict("This repository isn't set up for approvals.")
    request = open_request(db, kind.subject_type, subject_id)
    if request is not None and request.status == RequestStatus.PENDING.value:
        raise Conflict(f"{title} is already waiting for approval.")
    if request is not None:  # changes were requested: the flow is waiting for this
        request.status, request.title, request.payload = RequestStatus.PENDING.value, title, payload
        instance = db.get(engine.WorkflowInstance, request.workflow_instance_id)
        request.current_round = instance.round
        _event(db, request, "REQUEST_RESUBMITTED", requester, {"round": instance.round})
        engine.signal(db, instance, requester, {
            "snapshot": snapshot, "metadata": task_metadata(kind, request, resource, requester, listing)})
        _audit(db, "APPROVAL_SUBMITTED", request, requester, resubmitted=True)
        return request
    n = db.scalar(select(func.count()).select_from(ApprovalRequest).where(
        ApprovalRequest.subject_type == kind.subject_type, ApprovalRequest.subject_id == subject_id)) + 1
    approval_type = _type(db, kind)
    request = ApprovalRequest(
        source_system_id=_system_id(db, kind.system), approval_type_id=approval_type.id, resource_pk=resource.id,
        external_reference_id=f"{kind.subject_type.lower()}:{subject_id}:{n}", subject_type=kind.subject_type,
        subject_id=subject_id, title=title, payload=payload, requested_by=requester.id,
        maker_id=(maker or requester).id,
    )
    db.add(request)
    db.flush()
    _event(db, request, "REQUEST_SUBMITTED", requester, {"external_reference_id": request.external_reference_id})
    instance = engine.start(db, _resource_node(db, request).id, kind.workflow_kind, SUBJECT, str(request.id), requester,
                            {"snapshot": snapshot, "metadata": task_metadata(kind, request, resource, requester, listing)})
    request.workflow_instance_id = instance.id
    _audit(db, "APPROVAL_SUBMITTED", request, requester,
           workflow=instance.version.workflow.code, version=instance.version.version)
    return request


# --------------------------------------------------------------------------- the inbox


@dataclass(frozen=True)
class InboxItem:
    task: ApprovalTask
    request: ApprovalRequest
    kind: ApprovalKind
    requester: AppUser | None
    resource_name: str


def _inbox_query(user: AppUser):
    """One task in full, for opening or deciding it: the person's ACTIVE assignee row, the waiting
    task and pending request, the approval type, resource and source system, and who asked, with
    every condition checked again."""
    requester = aliased(AppUser)
    return (
        select(ApprovalTask, ApprovalRequest, ApprovalType.code, Resource.name, requester)
        .select_from(ApprovalTaskAssignee)
        .join(ApprovalTask, and_(ApprovalTask.id == ApprovalTaskAssignee.approval_task_id,
                                 ApprovalTask.status == TaskStatus.PENDING.value))
        .join(ApprovalRequest, and_(ApprovalRequest.id == ApprovalTask.approval_request_id,
                                    ApprovalRequest.status == RequestStatus.PENDING.value))
        .join(ApprovalType, ApprovalType.id == ApprovalRequest.approval_type_id)
        .join(Resource, and_(Resource.id == ApprovalRequest.resource_pk, Resource.status == "ACTIVE"))
        .join(SourceSystem, SourceSystem.id == ApprovalRequest.source_system_id)
        .outerjoin(requester, requester.id == ApprovalRequest.requested_by)
        .where(ApprovalTaskAssignee.user_id == user.id,
               ApprovalTaskAssignee.status == AssignmentStatus.ACTIVE.value,
               ApprovalRequest.requested_by != user.id,
               or_(ApprovalRequest.maker_id.is_(None), ApprovalRequest.maker_id != user.id))
        .order_by(ApprovalTask.created_at, ApprovalTask.id)
    )


def _items(db: Session, query) -> list[InboxItem]:
    return [InboxItem(task, request, kind_of(code), who, resource_name)
            for task, request, code, resource_name, who in db.execute(query).unique().all()]


def inbox(db: Session, user: AppUser) -> list[ApprovalTask]:
    """Tasks the person may decide now, oldest first, for listing: their ACTIVE assignee rows and the
    tasks, nothing else. Each task's metadata has what the list shows; the request, its summary and
    the live checks are looked up only when one is opened (inbox_item)."""
    return list(db.scalars(
        select(ApprovalTask)
        .join(ApprovalTaskAssignee, ApprovalTaskAssignee.approval_task_id == ApprovalTask.id)
        .where(ApprovalTaskAssignee.user_id == user.id, ApprovalTaskAssignee.status == AssignmentStatus.ACTIVE.value)
        .order_by(ApprovalTask.created_at, ApprovalTask.id)))


def inbox_item(db: Session, user: AppUser, task_id: uuid.UUID) -> InboxItem:
    """One task, if it's waiting for the person: the same query, for that task only, plus a live
    check that they still hold the required role in the task's user group (a safety net behind the
    assignee rows)."""
    items = _items(db, _inbox_query(user).where(ApprovalTask.id == task_id))
    assignment = db.scalar(select(ApprovalTaskAssignment).where(ApprovalTaskAssignment.approval_task_id == task_id))
    if not items or assignment is None:
        raise NotFound("That approval isn't waiting for you.")
    role = _role_code(db, assignment.required_role_id)
    holds = (access.holds_in_group(db, user.id, assignment.group_id, role) if assignment.group_id
             else role in access.roles_at(db, user.id, assignment.hierarchy_node_id))
    if not holds:
        raise NotFound("That approval isn't waiting for you.")
    return items[0]


# --------------------------------------------------------------------------- deciding

def decide(db: Session, user: AppUser, task_id: uuid.UUID, decision: Decision, comment: str | None) -> ApprovalRequest:
    """Record the decision, move the request on, and let the feature react. Commits."""
    comment = (comment or "").strip() or None
    if decision is not Decision.APPROVED and not comment:
        raise InvalidRequest("Say why: the maker sees this." if decision is Decision.CHANGES_REQUESTED
                             else "Give a reason for rejecting.")
    item = inbox_item(db, user, task_id)  # re-checks the role now; never the requester's own
    task, request = item.task, item.request
    now = utcnow()
    claimed = db.execute(update(ApprovalTask).where(ApprovalTask.id == task.id, ApprovalTask.status == TaskStatus.PENDING.value)
                         .values(status=TaskStatus.COMPLETED.value, outcome=decision.value, completed_at=now))
    if claimed.rowcount != 1:  # another checker got there first
        db.rollback()
        raise Conflict("Someone else has already decided this.")
    db.execute(update(ApprovalTaskAssignment).where(ApprovalTaskAssignment.approval_task_id == task.id)
               .values(status=AssignmentStatus.CLOSED.value))  # out of every inbox
    _close_assignees(db, task.id)
    try:
        db.add(ApprovalDecision(approval_task_id=task.id, decided_by=user.id, decision=decision.value,
                                comment=comment, decided_at=now))
        db.refresh(task)
        _event(db, request, "DECISION_RECORDED", user, {"decision": decision.value, "comment": comment,
                                                       "round": task.round}, task)
        _audit(db, "APPROVAL_DECIDED", request, user, decision=decision.value, comment=comment,
               step=(task.task_metadata or {}).get("step", {}).get("name"))
        meta = {k: v for k, v in (task.task_metadata or {}).items() if k != "step"}
        instance = engine.complete(db, task.step_instance_id, decision.value, user,
                                   {"snapshot": task.subject_snapshot, "metadata": meta})
        waiting_review = db.scalar(select(ApprovalTask.id).where(
            ApprovalTask.approval_request_id == request.id, ApprovalTask.status == TaskStatus.PENDING.value))
        if instance.status == InstanceStatus.RUNNING.value and waiting_review is None:
            # the flow went back to a step that waits for the maker (e.g. maker_upload): changes requested
            request.status = RequestStatus.CHANGES_REQUESTED.value
            _event(db, request, "REQUEST_CHANGES_REQUESTED", user, {"round": task.round}, task)
            item.kind.on_decided(db, request, RequestStatus.CHANGES_REQUESTED.value, user, comment)
        elif instance.status == InstanceStatus.RUNNING.value:
            _event(db, request, "STEP_COMPLETED", user, {"outcome": decision.value, "round": task.round}, task)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return request


# --------------------------------------------------------------------------- withdrawing


def _cancel(db: Session, request: ApprovalRequest, actor: AppUser | None, reason: str) -> int:
    for task in request.tasks:
        if task.status == TaskStatus.PENDING.value:
            task.status, task.completed_at = TaskStatus.CANCELLED.value, utcnow()
            if task.assignment is not None:
                task.assignment.status = AssignmentStatus.CLOSED.value
            _close_assignees(db, task.id)
    request.status, request.completed_at = RequestStatus.CANCELLED.value, utcnow()
    if request.workflow_instance_id is not None:
        engine.cancel(db, db.get(engine.WorkflowInstance, request.workflow_instance_id))
    _event(db, request, "REQUEST_CANCELLED", actor, {"reason": reason})
    _audit(db, "APPROVAL_CANCELLED", request, actor, reason=reason)
    return 1


def cancel_subject(db: Session, subject_type: str, subject_id: str, actor: AppUser | None, reason: str) -> int:
    """Cancel the subject's open request, if any. The caller commits."""
    request = open_request(db, subject_type, subject_id)
    return _cancel(db, request, actor, reason) if request else 0


# --------------------------------------------------------------------------- reading


@dataclass(frozen=True)
class DecisionView:
    decision: str
    comment: str | None
    decided_by: AppUser | None
    decided_at: Any
    round: int


def _users(db: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, AppUser]:
    return {u.id: u for u in db.scalars(select(AppUser).where(AppUser.id.in_(ids)))} if ids else {}


def latest_decisions(db: Session, request_ids: set[uuid.UUID]) -> dict[uuid.UUID, DecisionView]:
    """For each request, its most recent decision."""
    if not request_ids:
        return {}
    rows = db.execute(
        select(ApprovalTask.approval_request_id, ApprovalTask.round, ApprovalDecision)
        .join(ApprovalDecision, ApprovalDecision.approval_task_id == ApprovalTask.id)
        .where(ApprovalTask.approval_request_id.in_(request_ids))
        .order_by(ApprovalDecision.decided_at)
    ).all()
    people = _users(db, {d.decided_by for _, _, d in rows})
    out: dict[uuid.UUID, DecisionView] = {}
    for request_id, round_, d in rows:
        out[request_id] = DecisionView(d.decision, d.comment, people.get(d.decided_by), d.decided_at, round_)
    return out


@dataclass(frozen=True)
class RequestHistory:
    request: ApprovalRequest
    requester: AppUser | None
    rounds: list[tuple[ApprovalTask, list[DecisionView]]]


def history(db: Session, subject_type: str, subject_id: str) -> list[RequestHistory]:
    """Every request for the subject, newest first, with its rounds and decisions."""
    requests = db.scalars(
        select(ApprovalRequest).where(ApprovalRequest.subject_type == subject_type, ApprovalRequest.subject_id == subject_id)
        .options(selectinload(ApprovalRequest.tasks).selectinload(ApprovalTask.decisions))
        .order_by(ApprovalRequest.submitted_at.desc())
    ).all()
    people = _users(db, {r.requested_by for r in requests} |
                    {d.decided_by for r in requests for t in r.tasks for d in t.decisions})
    return [
        RequestHistory(r, people.get(r.requested_by), [
            (t, [DecisionView(d.decision, d.comment, people.get(d.decided_by), d.decided_at, t.round) for d in t.decisions])
            for t in r.tasks
        ])
        for r in requests
    ]
