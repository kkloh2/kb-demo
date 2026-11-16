"""Approval endpoints (the inbox).

    GET  /api/approvals                    signed in   tasks waiting for my decision, oldest first (from
                                                       my assignee rows and the tasks' metadata only)
    GET  /api/approvals/{task_id}          signed in   one of them in full, with its summary (404 when it
                                                       isn't waiting for me)
    POST /api/approvals/{task_id}/decision signed in   {decision: approve | reject | request_changes, comment}

Anyone signed in may call these; each only ever shows tasks the caller may decide (assigned to a
group where they hold the required role, not their own requests). The UI shows the page to people
who can decide something (GET /api/me/access -> can_decide).
"""

import uuid

from fastapi import APIRouter

from app.access import service as access
from app.access.models import AppUser
from app.approvals import service
from app.approvals.models import Decision
from app.approvals.schemas import ApprovalListOut, ApprovalOut, DecisionIn, DecisionOut, PersonRef, RequestHistoryOut, RoundOut
from app.auth.dependencies import CurrentUser
from app.core.errors import InvalidRequest
from app.db.session import Db

router = APIRouter(prefix="/approvals", tags=["approvals"])

_DECISIONS = {"approve": Decision.APPROVED, "reject": Decision.REJECTED, "request_changes": Decision.CHANGES_REQUESTED}


def person_ref(u: AppUser | None) -> PersonRef | None:
    return PersonRef(lan_id=u.lan_id, display_name=u.display_name) if u else None


def _out(i: service.InboxItem) -> ApprovalOut:
    return ApprovalOut(id=i.task.id, request_id=i.request.id, kind=i.kind.type_code, kind_label=i.kind.label,
                       title=i.request.title, round=i.task.round, resource_name=i.resource_name,
                       summary=i.request.payload, requested_by=person_ref(i.requester),
                       requested_at=i.task.created_at)


def _list_out(t) -> ApprovalListOut:
    m = t.task_metadata or {}
    who = m.get("submitted_by")
    return ApprovalListOut(id=t.id, kind=m.get("type", ""), kind_label=m.get("type_label", ""),
                           title=m.get("title", ""), round=m.get("round", t.round),
                           resource_name=(m.get("resource") or {}).get("name", ""),
                           requested_by=PersonRef(**who) if who else None,
                           requested_at=m.get("submitted_at") or t.created_at, metadata=m)


@router.get("", response_model=list[ApprovalListOut])
def list_approvals(db: Db, p: CurrentUser) -> list[ApprovalListOut]:
    return [_list_out(t) for t in service.inbox(db, access.require_user(db, p.lan_id))]


@router.get("/{task_id}", response_model=ApprovalOut, responses={404: {"description": "Not waiting for you"}})
def get_approval(task_id: uuid.UUID, db: Db, p: CurrentUser) -> ApprovalOut:
    return _out(service.inbox_item(db, access.require_user(db, p.lan_id), task_id))


@router.post("/{task_id}/decision", status_code=204,
             responses={404: {"description": "Not waiting for you"}, 409: {"description": "Already decided"}})
def decide(task_id: uuid.UUID, body: DecisionIn, db: Db, p: CurrentUser) -> None:
    decision = _DECISIONS.get(body.decision.strip().lower())
    if decision is None:
        raise InvalidRequest("decision is approve, reject or request_changes.")
    service.decide(db, access.require_user(db, p.lan_id), task_id, decision, body.comment)


def history_out(items: list[service.RequestHistory]) -> list[RequestHistoryOut]:
    """For modules that show a subject's approval history (e.g. a document's)."""
    return [
        RequestHistoryOut(
            id=h.request.id, reference=h.request.external_reference_id, status=h.request.status,
            requested_by=person_ref(h.requester), submitted_at=h.request.submitted_at,
            completed_at=h.request.completed_at,
            rounds=[RoundOut(id=t.id, round=t.round, step=((t.task_metadata or {}).get("step") or {}).get("name"),
                             status=t.status, outcome=t.outcome, created_at=t.created_at,
                             completed_at=t.completed_at,
                             decisions=[DecisionOut(decision=d.decision, comment=d.comment,
                                                    decided_by=person_ref(d.decided_by), decided_at=d.decided_at,
                                                    round=d.round) for d in ds])
                    for t, ds in h.rounds],
        )
        for h in items
    ]
