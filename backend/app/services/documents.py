"""Documents: listing, uploading, downloading, and the approve/reject shortcuts.

Approval itself is run by the workflow module (app.workflow) with the document rules in
app.services.document_approval. Uploading starts a workflow; approving or rejecting
completes its review task. The document's status is the workflow's outcome.
"""

from dataclasses import dataclass
from pathlib import Path, PurePath

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Document, KnowledgeBase
from app.core.config import get_settings
from app.services import audit, authz, document_approval, storage
from app.services.auth import Principal
from app.services.errors import Conflict, Forbidden, InvalidRequest, NotFound
from app.workflow import service as workflow
from app.services.knowledge_bases import get_visible_kb

_LOAD = (
    selectinload(Document.kb).selectinload(KnowledgeBase.department),
    selectinload(Document.maker),
    selectinload(Document.checker),
)


def list_documents(db: Session, p: Principal, kb_id: str) -> list[Document]:
    kb, _ = get_visible_kb(db, p, kb_id)
    statuses = authz.visible_document_statuses(db, p, kb)
    if statuses is None:
        raise Forbidden("Admins manage knowledge bases and people; they can't view documents.")
    return list(db.scalars(
        select(Document)
        .where(Document.kb_id == kb.id, Document.status.in_(statuses))
        .options(*_LOAD)
        .order_by(Document.submitted_at.desc())
    ))


@dataclass(frozen=True)
class IncomingFile:
    filename: str
    content_type: str | None
    data: bytes


def upload(db: Session, p: Principal, kb_id: str, files: list[IncomingFile]) -> list[Document]:
    """Store one or more files as pending documents. All-or-nothing: one bad file rejects the batch."""
    kb, _ = get_visible_kb(db, p, kb_id)
    if not authz.can_upload(p, kb):
        raise Forbidden("Only makers of this knowledge base's department can upload documents.")
    if not files:
        raise InvalidRequest("Choose at least one file.")
    s = get_settings()
    allowed = {e.lower() for e in s.allowed_upload_extensions}
    limit = s.max_upload_mb * 1024 * 1024
    for f in files:
        name = storage.safe_filename(f.filename)
        if Path(name).suffix.lower() not in allowed:
            raise InvalidRequest(f"{name}: file type not allowed. Allowed: {', '.join(sorted(allowed))}.")
        if not f.data:
            raise InvalidRequest(f"{name} is empty.")
        if len(f.data) > limit:
            raise InvalidRequest(f"{name} is larger than {s.max_upload_mb} MB.")

    created: list[Document] = []
    written: list[str] = []
    try:
        for f in files:
            name = storage.safe_filename(f.filename)
            doc = Document(
                kb_id=kb.id,
                title=PurePath(name).stem,
                filename=name,
                content_type=(f.content_type or "application/octet-stream")[:128],
                size_bytes=len(f.data),
                maker_id=p.user_id,
            )
            db.add(doc)
            db.flush()
            doc.storage_path = storage.save(kb.id, doc.id, name, f.data)
            written.append(doc.storage_path)
            audit.record(db, "document.upload", actor_id=p.user_id, actor_lan_id=p.lan_id,
                         target_type="document", target_id=doc.id,
                         detail={"kb": kb.id, "filename": name, "bytes": len(f.data)})
            db.refresh(doc, ["maker"])
            document_approval.start_for(db, doc, p)  # same transaction as the upload
            created.append(doc)
        db.commit()
    except Exception:
        db.rollback()
        for rel in written:  # don't leave orphaned files behind
            storage.delete(rel)
        raise
    return [_get(db, d.id) for d in created]


def open_file(db: Session, p: Principal, document_id: int) -> tuple[Path, Document]:
    """The stored file, if the user may see this document. Hidden documents look missing (404)."""
    doc = _get(db, document_id)
    if authz.kb_access(db, p, doc.kb) is None:
        raise NotFound("Document not found.")
    statuses = authz.visible_document_statuses(db, p, doc.kb)
    if statuses is None:
        raise Forbidden("Admins manage knowledge bases and people; they can't view documents.")
    if doc.status not in statuses:
        raise NotFound("Document not found.")
    path = storage.resolve(doc.storage_path) if doc.storage_path else None
    if path is None:
        raise NotFound("This document has no stored file.")
    audit.record(db, "document.download", actor_id=p.user_id, actor_lan_id=p.lan_id,
                 target_type="document", target_id=doc.id, detail={"kb": doc.kb_id})
    db.commit()
    return path, doc


def decide(db: Session, p: Principal, document_id: int, approve: bool, reason: str | None) -> Document:
    """Approve or reject = complete the document's open review task in its workflow."""
    doc = _get(db, document_id)
    if authz.kb_access(db, p, doc.kb) is None:
        raise NotFound("Document not found.")
    task = workflow.open_task_for(db, document_approval.SUBJECT, doc.id, lane="checker")
    if task is None:
        if not authz.can_review(p, doc, doc.maker):
            raise Forbidden("Only a checker from the maker's department can approve or reject this document.")
        raise Conflict(f"This document is already {doc.status.replace('_', ' ')}.")
    workflow.complete_task(db, task.id, p, {"decision": "approve" if approve else "reject", "reason": reason})
    db.commit()
    return _get(db, doc.id)


def _get(db: Session, document_id: int) -> Document:
    doc = db.scalar(
        select(Document)
        .where(Document.id == document_id)
        .options(*_LOAD)
        .execution_options(populate_existing=True)  # refresh relationships changed in this session
    )
    if doc is None:
        raise NotFound("Document not found.")
    return doc
