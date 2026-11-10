import re

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import (
    AccessRequest,
    AccessRequestStatus,
    Department,
    KbFavorite,
    KbViewGrant,
    KnowledgeBase,
    User,
    UserRole,
)
from app.core.permissions import RoleCode
from app.services import audit, authz, roles
from app.services.auth import Principal
from app.services.errors import Conflict, Forbidden, InvalidRequest, NotFound


_KB_LOAD = (selectinload(KnowledgeBase.department), selectinload(KnowledgeBase.admin))


def get_kb(db: Session, kb_id: str) -> KnowledgeBase:
    kb = db.scalar(
        select(KnowledgeBase)
        .where(KnowledgeBase.id == kb_id)
        .options(*_KB_LOAD)
        .execution_options(populate_existing=True)
    )
    if kb is None:
        raise NotFound("Knowledge base not found.")
    return kb


def get_visible_kb(db: Session, p: Principal, kb_id: str) -> tuple[KnowledgeBase, str]:
    """The KB and how the user sees it. Hidden KBs look the same as missing ones (404)."""
    kb = get_kb(db, kb_id)
    access = authz.kb_access(db, p, kb)
    if access is None:
        raise NotFound("Knowledge base not found.")
    return kb, access


def list_visible(db: Session, p: Principal) -> list[tuple[KnowledgeBase, str, bool]]:
    """(kb, access, is_favourite) for every KB the user can see, most recently updated first."""
    access = authz.visible_kb_ids(db, p)
    if not access:
        return []
    kbs = db.scalars(
        select(KnowledgeBase)
        .where(KnowledgeBase.id.in_(access))
        .options(*_KB_LOAD)
        .order_by(KnowledgeBase.updated_at.desc())
    ).all()
    favs = set(db.scalars(select(KbFavorite.kb_id).where(KbFavorite.user_id == p.user_id)))
    return [(kb, access[kb.id], kb.id in favs) for kb in kbs]


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:60] or "knowledge-base"


def create_kb(
    db: Session, p: Principal, name: str, description: str, department_code: str, admin_lan_id: str
) -> KnowledgeBase:
    """Create a KB and name its department admin. If the chosen user isn't a department admin
    yet, they become one, in the same transaction (so a refused promotion creates nothing)."""
    if not authz.can_create_kb(p):
        raise Forbidden("Only system admins can create knowledge bases.")
    name = name.strip()
    if not name:
        raise InvalidRequest("Name is required.")
    dept = db.scalar(select(Department).where(Department.code == department_code.strip().upper()))
    if dept is None:
        raise InvalidRequest(f"Department '{department_code}' not found.")
    admin = db.scalar(
        select(User)
        .where(User.lan_id == admin_lan_id.strip().lower())
        .options(selectinload(User.role_links).selectinload(UserRole.role))
    )
    if admin is None or not admin.is_active:
        raise InvalidRequest(f"User '{admin_lan_id}' not found.")
    if admin.department_id != dept.id:
        raise InvalidRequest(f"{admin.display_name} isn't in {dept.name}; choose someone from that department.")
    promoted = roles.grant_role(db, p, admin, RoleCode.DEPARTMENT_ADMIN)  # Conflict if maker/checker

    base = _slugify(name)
    slug, n = base, 2
    while db.get(KnowledgeBase, slug) is not None:
        slug, n = f"{base}-{n}", n + 1
    kb = KnowledgeBase(id=slug, name=name, description=description.strip(), department_id=dept.id,
                       admin_id=admin.id, created_by_id=p.user_id)
    db.add(kb)
    audit.record(db, "kb.create", actor_id=p.user_id, actor_lan_id=p.lan_id, target_type="knowledge_base",
                 target_id=slug, detail={"department": dept.code, "admin": admin.lan_id,
                                         "admin_promoted": promoted})
    db.commit()
    return get_kb(db, slug)


def update_kb(db: Session, p: Principal, kb_id: str, name: str | None, description: str | None) -> KnowledgeBase:
    kb, _ = get_visible_kb(db, p, kb_id)
    if not authz.can_update_kb(p, kb):
        raise Forbidden("You can't edit this knowledge base.")
    changes = {}
    if name is not None:
        if not name.strip():
            raise InvalidRequest("Name can't be empty.")
        kb.name, changes["name"] = name.strip(), name.strip()
    if description is not None:
        kb.description, changes["description"] = description.strip(), description.strip()
    audit.record(db, "kb.update", actor_id=p.user_id, actor_lan_id=p.lan_id, target_type="knowledge_base",
                 target_id=kb.id, detail=changes)
    db.commit()
    return get_kb(db, kb.id)


def set_favorite(db: Session, p: Principal, kb_id: str, favorite: bool) -> None:
    get_visible_kb(db, p, kb_id)
    existing = db.get(KbFavorite, (p.user_id, kb_id))
    if favorite and existing is None:
        db.add(KbFavorite(user_id=p.user_id, kb_id=kb_id))
    elif not favorite and existing is not None:
        db.delete(existing)
    db.commit()


def list_viewers(db: Session, p: Principal, kb_id: str) -> list[tuple[KbViewGrant, User]]:
    """Users from other departments with view access (department admins of the KB only)."""
    kb = get_kb(db, kb_id)
    if not authz.can_decide_access(p, kb):
        raise Forbidden("Only this knowledge base's department admin can see its viewers.")
    rows = db.execute(
        select(KbViewGrant, User)
        .join(User, User.id == KbViewGrant.user_id)
        .where(KbViewGrant.kb_id == kb_id)
        .options(selectinload(User.department))
        .order_by(User.display_name)
    ).all()
    return [(g, u) for g, u in rows]


def revoke_viewer(db: Session, p: Principal, kb_id: str, lan_id: str) -> None:
    kb = get_kb(db, kb_id)
    if not authz.can_decide_access(p, kb):
        raise Forbidden("Only this knowledge base's department admin can remove viewers.")
    user = db.scalar(select(User).where(User.lan_id == lan_id.strip().lower()))
    grant = db.get(KbViewGrant, (kb_id, user.id)) if user else None
    if grant is None:
        raise Conflict("This user doesn't have granted access to this knowledge base.")
    db.delete(grant)
    audit.record(db, "access.revoke", actor_id=p.user_id, actor_lan_id=p.lan_id, target_type="knowledge_base",
                 target_id=kb_id, detail={"user": user.lan_id})
    db.commit()


def directory(db: Session, p: Principal) -> list[tuple[KnowledgeBase, str | None, bool]]:
    """Every KB (names and departments only) with the user's access and whether they have a
    pending request, so users can find other departments' KBs and ask for access."""
    access = authz.visible_kb_ids(db, p)
    pending = set(db.scalars(
        select(AccessRequest.kb_id).where(
            AccessRequest.requester_id == p.user_id, AccessRequest.status == AccessRequestStatus.PENDING
        )
    ))
    kbs = db.scalars(
        select(KnowledgeBase).options(selectinload(KnowledgeBase.department)).order_by(KnowledgeBase.name)
    ).all()
    return [(kb, access.get(kb.id), kb.id in pending) for kb in kbs]
