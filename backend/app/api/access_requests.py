from typing import Literal

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, Db
from app.db.models import AccessRequest
from app.schemas.auth import DepartmentOut
from app.schemas.people import AccessDecision, AccessRequestCreate, AccessRequestOut, UserRef
from app.services import access_requests as service

router = APIRouter(tags=["access-requests"])


def _out(r: AccessRequest) -> AccessRequestOut:
    req = r.requester
    return AccessRequestOut(
        id=r.id,
        kb_id=r.kb_id,
        kb_name=r.kb.name,
        kb_department=DepartmentOut(code=r.kb.department.code, name=r.kb.department.name),
        requester=UserRef(
            username=req.lan_id,
            display_name=req.display_name,
            department=DepartmentOut(code=req.department.code, name=req.department.name) if req.department else None,
        ),
        reason=r.reason,
        status=r.status,
        created_at=r.created_at,
        decided_by=r.decided_by.lan_id if r.decided_by else None,
        decided_at=r.decided_at,
        decision_note=r.decision_note,
    )


@router.post(
    "/knowledge-bases/{kb_id}/access-requests",
    response_model=AccessRequestOut,
    status_code=status.HTTP_201_CREATED,
)
def request_access(kb_id: str, body: AccessRequestCreate, p: CurrentUser, db: Db) -> AccessRequestOut:
    """Ask for view access to another department's knowledge base."""
    return _out(service.create_request(db, p, kb_id, body.reason))


@router.get("/access-requests", response_model=list[AccessRequestOut])
def list_access_requests(
    p: CurrentUser, db: Db, status: Literal["pending", "approved", "rejected"] | None = None
) -> list[AccessRequestOut]:
    """Your own requests, plus (department admins) requests for your department's knowledge bases."""
    return [_out(r) for r in service.list_requests(db, p, status)]


@router.post("/access-requests/{request_id}/approve", response_model=AccessRequestOut)
def approve(request_id: int, body: AccessDecision, p: CurrentUser, db: Db) -> AccessRequestOut:
    return _out(service.decide(db, p, request_id, True, body.note))


@router.post("/access-requests/{request_id}/reject", response_model=AccessRequestOut)
def reject(request_id: int, body: AccessDecision, p: CurrentUser, db: Db) -> AccessRequestOut:
    return _out(service.decide(db, p, request_id, False, body.note))
