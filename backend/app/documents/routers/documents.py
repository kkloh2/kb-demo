"""Document endpoints (inside one repository).

    GET  /api/doc-repos/{id}/documents                    docs.repository.view   the documents I may see
    POST /api/doc-repos/{id}/documents                    docs.document.upload   upload files / a folder
    GET  /api/doc-repos/{id}/documents/{doc}              docs.repository.view   (404 when hidden)
    GET  /api/doc-repos/{id}/documents/{doc}/download     docs.repository.view
    GET  /api/doc-repos/{id}/documents/{doc}/history      docs.repository.view   its approval requests and decisions
    PUT  /api/doc-repos/{id}/documents/{doc}/metadata     docs.document.upload   not when pending or approved
    POST /api/doc-repos/{id}/documents/submit             docs.document.upload   {ids, statuses}: send for approval (all or none)
    POST /api/doc-repos/{id}/documents/delete             docs.document.upload   {ids}: soft delete

Decisions happen on the Approvals page (/api/approvals), never here.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Path, UploadFile, status
from fastapi.responses import FileResponse

from app.access.authorization import Can
from app.access.catalog import P
from app.access.models import AppUser
from app.approvals.router import history_out
from app.approvals.schemas import RequestHistoryOut
from app.audit import service as audit
from app.auth.dependencies import CurrentUser
from app.core.config import get_settings
from app.core.errors import InvalidRequest
from app.db.session import Db
from app.documents import documents as docs
from app.documents import metadata
from app.documents.models import DocRepo, Document
from app.documents.routers.doc_repos import DocRepoId, at_repo, me, ref
from app.documents.schemas import (
    BulkOut,
    DecisionRef,
    DocumentActionsOut,
    DocumentIds,
    DocumentOut,
    MetadataEntryOut,
    MetadataUpdate,
    SkippedOut,
    SubmitIn,
)
from app.documents.service import RepoAccess

router = APIRouter(tags=["documents"])

DocumentId = Annotated[uuid.UUID, Path(description="Document id")]
readers = Can(P.REPO_VIEW, at=at_repo())


def outs(db: Db, repo: DocRepo, items: list[Document], a: RepoAccess) -> list[DocumentOut]:
    entries = metadata.entries(db, items, repo.node)
    decisions = docs.decisions_for(db, items)
    out = []
    for d in items:
        act = docs.actions_for(d, a)
        dec = decisions.get(d.id)
        out.append(DocumentOut(
            id=d.id, doc_repo_id=d.doc_repo_id, folder=d.folder, filename=d.filename, content_type=d.content_type,
            size_bytes=d.size_bytes, status=d.status, maker=ref(d.maker), created_at=d.created_at,
            updated_at=d.updated_at, submitted_at=d.submitted_at,
            last_decision=DecisionRef(decision=dec.decision, comment=dec.comment, decided_by=ref(dec.decided_by),
                                      decided_at=dec.decided_at, round=dec.round) if dec else None,
            metadata=[MetadataEntryOut(**e.__dict__) for e in entries.get(d.id, [])],
            actions=DocumentActionsOut(edit=act.edit, submit=act.submit, delete=act.delete),
        ))
    return out


def _one(db: Db, user: AppUser, repo_id: uuid.UUID, doc_id: uuid.UUID) -> DocumentOut:
    repo, doc, a = docs.get_document(db, user, repo_id, doc_id)
    return outs(db, repo, [doc], a)[0]


def _bulk(db: Db, user: AppUser, repo_id: uuid.UUID, result: docs.BulkResult, deleted: bool = False) -> BulkOut:
    repo, _, a = docs.list_documents(db, user, repo_id)
    return BulkOut(done=[] if deleted else outs(db, repo, result.done, a),
                   skipped=[SkippedOut(id=s.document_id, filename=s.filename, reason=s.reason) for s in result.skipped])


@router.get("/doc-repos/{doc_repo_id}/documents", response_model=list[DocumentOut])
@readers
def list_documents(doc_repo_id: DocRepoId, db: Db, p: CurrentUser) -> list[DocumentOut]:
    """Makers and auditors see every status; checkers submitted ones; viewers, owners and admins approved ones."""
    repo, items, a = docs.list_documents(db, me(db, p), doc_repo_id)
    return outs(db, repo, items, a)


@router.post("/doc-repos/{doc_repo_id}/documents", response_model=list[DocumentOut],
             status_code=status.HTTP_201_CREATED,
             responses={422: {"description": "A file's type, size or count isn't allowed"}})
@Can(P.DOC_UPLOAD, at=at_repo())
async def upload_documents(
    doc_repo_id: DocRepoId,
    db: Db,
    p: CurrentUser,
    files: Annotated[list[UploadFile], File(description="The files")],
    paths: Annotated[list[str] | None, Form(description="Each file's path in a folder upload, same order")] = None,
) -> list[DocumentOut]:
    """Upload files, or a folder (its structure is kept). Each becomes a draft with the repository's
    metadata. All-or-nothing."""
    if paths is not None and len(paths) != len(files):
        raise InvalidRequest("Send one path per file, or none.")
    limit = get_settings().max_upload_mb * 1024 * 1024
    incoming = []
    for i, f in enumerate(files):
        data = await f.read(limit + 1)
        incoming.append(docs.IncomingFile(relative_path=paths[i] if paths else (f.filename or ""),
                                          content_type=f.content_type, data=data))
    user = me(db, p)
    created = docs.upload(db, user, doc_repo_id, incoming)
    repo, _, a = docs.list_documents(db, user, doc_repo_id)
    return outs(db, repo, created, a)


@router.get("/doc-repos/{doc_repo_id}/documents/{document_id}", response_model=DocumentOut)
@readers
def get_document(doc_repo_id: DocRepoId, document_id: DocumentId, db: Db, p: CurrentUser) -> DocumentOut:
    return _one(db, me(db, p), doc_repo_id, document_id)


@router.get("/doc-repos/{doc_repo_id}/documents/{document_id}/download", response_class=FileResponse)
@readers
def download(doc_repo_id: DocRepoId, document_id: DocumentId, db: Db, p: CurrentUser) -> FileResponse:
    user = me(db, p)
    repo, doc, _ = docs.get_document(db, user, doc_repo_id, document_id)
    path = docs.file_path(doc)
    audit.record(db, "DOCUMENT_DOWNLOADED", actor=user, target=("document", doc.id), node_id=repo.hierarchy_node_id,
                 details={"filename": doc.filename})
    db.commit()
    return FileResponse(path, filename=doc.filename, media_type=doc.content_type or "application/octet-stream")


@router.get("/doc-repos/{doc_repo_id}/documents/{document_id}/history", response_model=list[RequestHistoryOut])
@readers
def document_history(doc_repo_id: DocRepoId, document_id: DocumentId, db: Db, p: CurrentUser) -> list[RequestHistoryOut]:
    """Every approval request for the document, newest first, with each round's decisions."""
    _, doc, _ = docs.get_document(db, me(db, p), doc_repo_id, document_id)
    return history_out(docs.history(db, doc))


@router.put("/doc-repos/{doc_repo_id}/documents/{document_id}/metadata", response_model=DocumentOut,
            responses={409: {"description": "Pending or approved: locked"}})
@Can(P.DOC_UPLOAD, at=at_repo())
def update_metadata(doc_repo_id: DocRepoId, document_id: DocumentId, body: MetadataUpdate, db: Db,
                    p: CurrentUser) -> DocumentOut:
    """Keep, override or remove each repository field, and set the document's own fields."""
    user = me(db, p)
    docs.update_metadata(db, user, doc_repo_id, document_id,
                         {c.field_id: (c.state, c.value) for c in body.inherited},
                         [(m.label, m.value) for m in body.own])
    return _one(db, user, doc_repo_id, document_id)


@router.post("/doc-repos/{doc_repo_id}/documents/submit", response_model=BulkOut,
             responses={409: {"description": "One changed since it was chosen, or was refused: nothing submitted"}})
@Can(P.DOC_UPLOAD, at=at_repo())
def submit_documents(doc_repo_id: DocRepoId, body: SubmitIn, db: Db, p: CurrentUser) -> BulkOut:
    """Send documents for approval, all or none; they appear on the repository checkers' Approvals
    page. 409 (nothing submitted) when any has changed since it was chosen or the flow refuses any."""
    user = me(db, p)
    return _bulk(db, user, doc_repo_id, docs.submit(db, user, doc_repo_id, body.ids, body.statuses))


@router.post("/doc-repos/{doc_repo_id}/documents/delete", response_model=BulkOut)
@Can(P.DOC_UPLOAD, at=at_repo())
def delete_documents(doc_repo_id: DocRepoId, body: DocumentIds, db: Db, p: CurrentUser) -> BulkOut:
    """Delete drafts, rejected and changes-requested documents (kept, hidden). Others are skipped."""
    user = me(db, p)
    return _bulk(db, user, doc_repo_id, docs.delete_documents(db, user, doc_repo_id, body.ids), deleted=True)

