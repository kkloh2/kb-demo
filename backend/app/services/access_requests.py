"""Cross-department view access: a user requests it; the KB's department admin decides."""

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.permissions import Perm
from app.db.models import AccessRequest, AccessRequestStatus, KbViewGrant, KnowledgeBase, User, utcnow
from app.services import audit, authz
from app.services.auth import Principal
from app.services.errors import Conflict, Forbidden, NotFound
from app.services.knowledge_bases import get_kb

_LOAD = (
    selectinload(AccessRequest.kb).selectinload(KnowledgeBase.department),
    selectinload(AccessRequest.requester).selectinload(User.department),
    selectinload(AccessRequest.decided_by),
)


def create_request(db: Session, p: Principal, kb_id: str, reason: str) -> AccessRequest:
    kb = get_kb(db, kb_id)  # users must be able to find other departments' KBs to ask for them
    if not authz.can_request_access(p, kb):
        if p.department_id == kb.department_id:
            raise Conflict("This knowledge base belongs to your department; you already have access.")
        raise Forbidden("You can't request access to knowledge bases.")
    if authz.has_view_grant(db, p, kb.id):
        raise Conflict("You already have view access to this knowledge base.")
    req = AccessRequest(kb_id=kb.id, requester_id=p.user_id, reason=reason.strip())
    db.add(req)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict("You already have a pending request for this knowledge base.") from None
    audit.record(db, "access.request", actor_id=p.user_id, actor_lan_id=p.lan_id,
                 target_type="knowledge_base", target_id=kb.id, detail={"request_id": req.id})
    db.commit()
    return _get(db, req.id)


def list_requests(db: Session, p: Principal, status: str | None = None) -> list[AccessRequest]:
    """Department admins: requests for their department's KBs. Everyone: their own requests."""
    conditions = [AccessRequest.requester_id == p.user_id]
    if p.has(Perm.ACCESS_REQUESTS_DECIDE) and p.department_id is not None:
        conditions.append(KnowledgeBase.department_id == p.department_id)
    q = (
        select(AccessRequest)
        .join(KnowledgeBase, KnowledgeBase.id == AccessRequest.kb_id)
        .where(or_(*conditions))
        .options(*_LOAD)
        .order_by(AccessRequest.created_at.desc())
    )
    if status:
        q = q.where(AccessRequest.status == status)
    return list(db.scalars(q))


def decide(db: Session, p: Principal, request_id: int, approve: bool, note: str | None) -> AccessRequest:
    req = _get(db, request_id)
    if not authz.can_decide_access(p, req.kb):
        raise Forbidden("Only this knowledge base's department admin can decide this request.")
    if req.status != AccessRequestStatus.PENDING:
        raise Conflict(f"This request has already been {req.status}.")
    req.status = AccessRequestStatus.APPROVED if approve else AccessRequestStatus.REJECTED
    req.decided_by_id = p.user_id
    req.decided_at = utcnow()
    req.decision_note = (note or "").strip() or None
    if approve and db.get(KbViewGrant, (req.kb_id, req.requester_id)) is None:
        db.add(KbViewGrant(kb_id=req.kb_id, user_id=req.requester_id, request_id=req.id,
                           granted_by_id=p.user_id))
    audit.record(db, "access.approve" if approve else "access.reject", actor_id=p.user_id,
                 actor_lan_id=p.lan_id, target_type="access_request", target_id=req.id,
                 detail={"kb": req.kb_id, "requester": req.requester.lan_id})
    db.commit()
    return _get(db, req.id)


def _get(db: Session, request_id: int) -> AccessRequest:
    req = db.scalar(
        select(AccessRequest)
        .where(AccessRequest.id == request_id)
        .options(*_LOAD)
        .execution_options(populate_existing=True)  # refresh relationships changed in this session
    )
    if req is None:
        raise NotFound("Access request not found.")
    return req
