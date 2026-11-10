from typing import Annotated

from fastapi import APIRouter, File, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import CurrentUser, Db
from app.core.config import get_settings
from app.db.models import Document, User
from app.schemas.document import ActivityOut, DocumentDecision, DocumentOut, PersonRef
from app.services import document_approval
from app.services import documents as service
from app.services.knowledge_bases import get_visible_kb
from app.services.errors import InvalidRequest

router = APIRouter(tags=["documents"])


def _person(u: User | None) -> PersonRef | None:
    return PersonRef(username=u.lan_id, display_name=u.display_name) if u else None


def _out(d: Document) -> DocumentOut:
    return DocumentOut(
        id=d.id, kb_id=d.kb_id, title=d.title, filename=d.filename,
        content_type=d.content_type, size_bytes=d.size_bytes, has_file=bool(d.storage_path),
        status=d.status, maker=_person(d.maker), checker=_person(d.checker),
        submitted_at=d.submitted_at, decided_at=d.decided_at, rejection_reason=d.rejection_reason,
    )


@router.get("/knowledge-bases/{kb_id}/documents", response_model=list[DocumentOut])
def list_documents(kb_id: str, p: CurrentUser, db: Db) -> list[DocumentOut]:
    """Viewers see approved documents; makers and checkers of the department also see pending
    and rejected ones. Admins can't list documents."""
    return [_out(d) for d in service.list_documents(db, p, kb_id)]


@router.get("/knowledge-bases/{kb_id}/activity", response_model=list[ActivityOut])
def kb_activity(kb_id: str, p: CurrentUser, db: Db) -> list[ActivityOut]:
    """Uploads and approval decisions for the documents you can see, newest first."""
    kb, _ = get_visible_kb(db, p, kb_id)
    return [ActivityOut(**e) for e in document_approval.kb_activity(db, p, kb)]


@router.post(
    "/knowledge-bases/{kb_id}/documents", response_model=list[DocumentOut], status_code=status.HTTP_201_CREATED
)
def upload_documents(
    kb_id: str, p: CurrentUser, db: Db, files: Annotated[list[UploadFile], File(description="One or more files")]
) -> list[DocumentOut]:
    """Makers of the knowledge base's department. Each file becomes a pending_approval document.

    A plain (sync) endpoint: FastAPI runs it in a worker thread, so file and DB I/O don't block.
    """
    limit = get_settings().max_upload_mb * 1024 * 1024
    incoming = []
    for f in files:
        data = f.file.read(limit + 1)  # one byte past the limit detects oversize files
        if len(data) > limit:
            raise InvalidRequest(f"{f.filename} is larger than {get_settings().max_upload_mb} MB.")
        incoming.append(service.IncomingFile(f.filename or "file", f.content_type, data))
    return [_out(d) for d in service.upload(db, p, kb_id, incoming)]


@router.get("/documents/{document_id}/download", response_class=FileResponse)
def download_document(document_id: int, p: CurrentUser, db: Db) -> FileResponse:
    """The file, for anyone who can see the document."""
    path, doc = service.open_file(db, p, document_id)
    return FileResponse(path, media_type=doc.content_type or "application/octet-stream", filename=doc.filename)


@router.post("/documents/{document_id}/approve", response_model=DocumentOut)
def approve_document(document_id: int, body: DocumentDecision, p: CurrentUser, db: Db) -> DocumentOut:
    """Checkers from the maker's department only."""
    return _out(service.decide(db, p, document_id, True, body.reason))


@router.post("/documents/{document_id}/reject", response_model=DocumentOut)
def reject_document(document_id: int, body: DocumentDecision, p: CurrentUser, db: Db) -> DocumentOut:
    return _out(service.decide(db, p, document_id, False, body.reason))
