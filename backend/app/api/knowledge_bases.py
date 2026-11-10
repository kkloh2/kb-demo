from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, Db
from app.core.permissions import Perm
from app.db.models import KbFavorite, KnowledgeBase
from app.schemas.auth import DepartmentOut
from app.schemas.knowledge_base import (
    KbCapabilities,
    KnowledgeBaseCreate,
    KnowledgeBaseDetail,
    KnowledgeBaseDirectoryEntry,
    KnowledgeBaseOut,
    KnowledgeBaseUpdate,
    UserBrief,
    ViewerOut,
)
from app.services import authz
from app.services import knowledge_bases as kb_service

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


def _dept(kb: KnowledgeBase) -> DepartmentOut:
    return DepartmentOut(code=kb.department.code, name=kb.department.name)


def _out(kb: KnowledgeBase, access: str, favorite: bool) -> KnowledgeBaseOut:
    return KnowledgeBaseOut(
        id=kb.id, name=kb.name, description=kb.description, department=_dept(kb),
        admin=UserBrief(username=kb.admin.lan_id, display_name=kb.admin.display_name) if kb.admin else None,
        access=access, updated_at=kb.updated_at, favorite=favorite,
    )


@router.get("", response_model=list[KnowledgeBaseOut])
def list_knowledge_bases(p: CurrentUser, db: Db) -> list[KnowledgeBaseOut]:
    """Knowledge bases you can see: your department's, those shared with you, or those you manage."""
    return [_out(kb, access, fav) for kb, access, fav in kb_service.list_visible(db, p)]


@router.get("/directory", response_model=list[KnowledgeBaseDirectoryEntry])
def directory(p: CurrentUser, db: Db) -> list[KnowledgeBaseDirectoryEntry]:
    """All knowledge bases (no documents), so you can request access to other departments'."""
    return [
        KnowledgeBaseDirectoryEntry(
            id=kb.id, name=kb.name, description=kb.description, department=_dept(kb),
            access=access, request_pending=pending,
        )
        for kb, access, pending in kb_service.directory(db, p)
    ]


@router.get("/{kb_id}", response_model=KnowledgeBaseDetail)
def get_knowledge_base(kb_id: str, p: CurrentUser, db: Db) -> KnowledgeBaseDetail:
    """One knowledge base, plus what you can do in it (so the UI shows the right controls)."""
    kb, access = kb_service.get_visible_kb(db, p, kb_id)
    statuses = authz.visible_document_statuses(db, p, kb)
    base = _out(kb, access, db.get(KbFavorite, (p.user_id, kb.id)) is not None)
    return KnowledgeBaseDetail(
        **base.model_dump(),
        capabilities=KbCapabilities(
            view_documents=statuses is not None,
            view_unapproved=bool(statuses and len(statuses) > 1),
            upload=authz.can_upload(p, kb),
            review=p.has(Perm.DOCUMENTS_APPROVE) and authz.kb_access(db, p, kb) == "department",
            edit=authz.can_update_kb(p, kb),
        ),
    )


@router.post("", response_model=KnowledgeBaseOut, status_code=status.HTTP_201_CREATED)
def create_knowledge_base(body: KnowledgeBaseCreate, p: CurrentUser, db: Db) -> KnowledgeBaseOut:
    """System admins only. Names the KB's department admin (promoting them if needed)."""
    kb = kb_service.create_kb(db, p, body.name, body.description, body.department_code, body.admin_lan_id)
    return _out(kb, authz.kb_access(db, p, kb) or "admin", False)


@router.patch("/{kb_id}", response_model=KnowledgeBaseOut)
def update_knowledge_base(kb_id: str, body: KnowledgeBaseUpdate, p: CurrentUser, db: Db) -> KnowledgeBaseOut:
    """System admins, or the department admin of the knowledge base's department."""
    kb = kb_service.update_kb(db, p, kb_id, body.name, body.description)
    return _out(kb, authz.kb_access(db, p, kb) or "admin", False)


@router.put("/{kb_id}/favorite", status_code=status.HTTP_204_NO_CONTENT)
def add_favorite(kb_id: str, p: CurrentUser, db: Db) -> Response:
    kb_service.set_favorite(db, p, kb_id, True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{kb_id}/favorite", status_code=status.HTTP_204_NO_CONTENT)
def remove_favorite(kb_id: str, p: CurrentUser, db: Db) -> Response:
    kb_service.set_favorite(db, p, kb_id, False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{kb_id}/viewers", response_model=list[ViewerOut])
def list_viewers(kb_id: str, p: CurrentUser, db: Db) -> list[ViewerOut]:
    """Users from other departments with view access. The KB's department admin only."""
    return [
        ViewerOut(
            username=u.lan_id,
            display_name=u.display_name,
            department=DepartmentOut(code=u.department.code, name=u.department.name) if u.department else None,
            granted_at=g.granted_at,
        )
        for g, u in kb_service.list_viewers(db, p, kb_id)
    ]


@router.delete("/{kb_id}/viewers/{lan_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_viewer(kb_id: str, lan_id: str, p: CurrentUser, db: Db) -> Response:
    kb_service.revoke_viewer(db, p, kb_id, lan_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
