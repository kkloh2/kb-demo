"""Authorization policy: who may do what to which knowledge base or document.

Permissions (in the token) say what kind of action a user may take; these functions add
the *scope* rules: same department, explicit view grants, and maker-checker separation.
"""

from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import Perm, RoleCode
from app.db.models import Document, DocumentStatus, KbViewGrant, KnowledgeBase, User
from app.services.auth import Principal

KbAccess = Literal["admin", "department", "granted"]


def _same_department(p: Principal, department_id: int) -> bool:
    return p.department_id is not None and p.department_id == department_id


def has_view_grant(db: Session, p: Principal, kb_id: str) -> bool:
    return db.get(KbViewGrant, (kb_id, p.user_id)) is not None


def kb_access(db: Session, p: Principal, kb: KnowledgeBase) -> KbAccess | None:
    """How the user can see this knowledge base, or None if they can't.

    admin       system admin (any KB) or department admin (own department): manage only
    department  member of the owning department: view approved documents
    granted     another department's member with an approved view request
    """
    if p.has_role(RoleCode.SYSTEM_ADMIN):
        return "admin"
    if p.has_role(RoleCode.DEPARTMENT_ADMIN):
        return "admin" if _same_department(p, kb.department_id) else None
    if not p.has(Perm.KB_VIEW):
        return None
    if _same_department(p, kb.department_id):
        return "department"
    if has_view_grant(db, p, kb.id):
        return "granted"
    return None


def visible_kb_ids(db: Session, p: Principal) -> dict[str, KbAccess]:
    """Every knowledge base the user can see, with how they see it."""
    kbs = db.scalars(select(KnowledgeBase)).all()
    granted = set(db.scalars(select(KbViewGrant.kb_id).where(KbViewGrant.user_id == p.user_id)))
    out: dict[str, KbAccess] = {}
    for kb in kbs:
        if p.has_role(RoleCode.SYSTEM_ADMIN):
            out[kb.id] = "admin"
        elif p.has_role(RoleCode.DEPARTMENT_ADMIN):
            if _same_department(p, kb.department_id):
                out[kb.id] = "admin"
        elif p.has(Perm.KB_VIEW):
            if _same_department(p, kb.department_id):
                out[kb.id] = "department"
            elif kb.id in granted:
                out[kb.id] = "granted"
    return out


# --------------------------------------------------------------------------- knowledge bases


def can_create_kb(p: Principal) -> bool:
    return p.has(Perm.KB_CREATE)


def can_update_kb(p: Principal, kb: KnowledgeBase) -> bool:
    if not p.has(Perm.KB_UPDATE):
        return False
    return p.has_role(RoleCode.SYSTEM_ADMIN) or _same_department(p, kb.department_id)


# --------------------------------------------------------------------------- documents


def visible_document_statuses(db: Session, p: Principal, kb: KnowledgeBase) -> set[str] | None:
    """Statuses this user may see in a KB, or None if they may not see its documents at all.

    Admins never see document contents. Viewers (own department or granted) see approved
    documents only. Makers and checkers also see pending and rejected ones in their department.
    """
    access = kb_access(db, p, kb)
    if access not in ("department", "granted") or not p.has(Perm.DOCUMENTS_VIEW):
        return None
    statuses = {DocumentStatus.APPROVED.value}
    if access == "department" and p.has(Perm.DOCUMENTS_VIEW_UNAPPROVED):
        statuses |= {DocumentStatus.PENDING.value, DocumentStatus.REJECTED.value}
    return statuses


def can_upload(p: Principal, kb: KnowledgeBase) -> bool:
    return p.has(Perm.DOCUMENTS_UPLOAD) and _same_department(p, kb.department_id)


def can_review(p: Principal, doc: Document, maker: User) -> bool:
    """Only a checker of the same department as the KB *and* the maker, never the maker."""
    return (
        p.has(Perm.DOCUMENTS_APPROVE)
        and _same_department(p, doc.kb.department_id)
        and maker.department_id == p.department_id
        and doc.maker_id != p.user_id
    )


# --------------------------------------------------------------------------- people & access


def can_decide_access(p: Principal, kb: KnowledgeBase) -> bool:
    return p.has(Perm.ACCESS_REQUESTS_DECIDE) and _same_department(p, kb.department_id)


def can_request_access(p: Principal, kb: KnowledgeBase) -> bool:
    return (
        p.has(Perm.ACCESS_REQUESTS_CREATE)
        and p.department_id is not None
        and p.department_id != kb.department_id
    )


def can_view_users(p: Principal, department_id: int | None) -> bool:
    """System admins see everyone; department admins see their own department."""
    if not p.has(Perm.USERS_VIEW):
        return False
    return p.has_role(RoleCode.SYSTEM_ADMIN) or (
        department_id is not None and _same_department(p, department_id)
    )


def can_manage_role(p: Principal, target: User, role: RoleCode) -> bool:
    if role is RoleCode.DEPARTMENT_ADMIN:
        return p.has(Perm.DEPARTMENT_ADMINS_MANAGE)
    if role in (RoleCode.MAKER, RoleCode.CHECKER):
        return (
            p.has(Perm.DEPARTMENT_ROLES_MANAGE)
            and target.department_id is not None
            and _same_department(p, target.department_id)
        )
    return False  # system_admin and viewer can't be assigned through the API
