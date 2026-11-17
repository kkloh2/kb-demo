"""Document endpoints (inside one repository).

    GET  /api/doc-repos/{id}/documents                    docs.repository.view   the documents I may see
    POST /api/doc-repos/{id}/documents                    docs.document.upload   upload files / a folder
    GET  /api/doc-repos/{id}/documents/{doc}              docs.repository.view   (404 when hidden)
    GET  /api/doc-repos/{id}/documents/{doc}/download     docs.repository.view
    GET  /api/doc-repos/{id}/documents/{doc}/history      docs.repository.view   its approval requests and decisions
    PUT  /api/doc-repos/{id}/documents/{doc}/metadata     docs.document.upload   not when pending or approved
    POST /api/doc-repos/{id}/documents/submit             docs.document.upload   {ids, statuses}: send for approval (all or none)
    POST /api/doc-repos/{id}/documents/delete             docs.document.upload   {ids}: soft delete
    GET  /api/doc-repos/{id}/documents/{doc}/versions     makers, checkers, auditors: every version
    GET  /api/doc-repos/{id}/documents/{doc}/versions/{n}/download
    POST /api/doc-repos/{id}/documents/{doc}/versions/{n}/restore   docs.document.upload   as the latest, a draft
    POST /api/doc-repos/{id}/documents/{doc}/discard-version        docs.document.upload   back to the one before

Uploading a name that's already in the folder gives that document a new version (see versions.py).

Decisions happen on the Approvals page (/api/approvals), never here.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Path, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.access.authorization import Can
from app.access.catalog import P
from app.access.models import AppUser
from app.approvals.router import history_out
from app.approvals.schemas import RequestHistoryOut
from app.audit import service as audit
from app.auth.dependencies import CurrentUser
from app.core.config import get_settings
from app.core.errors import InvalidRequest, NotFound
from app.db.session import Db
from app.documents import documents as docs
from app.documents import metadata
from app.documents.models import DocRepo, Document, DocumentVersion
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
    VersionOut,
)
from app.documents import versions
from app.documents.service import RepoAccess, access_to, get_repo

router = APIRouter(tags=["documents"])

DocumentId = Annotated[uuid.UUID, Path(description="Document id")]
readers = Can(P.REPO_VIEW, at=at_repo())


def _decision(dec) -> DecisionRef | None:
    return DecisionRef(decision=dec.decision, comment=dec.comment, decided_by=ref(dec.decided_by),
                       decided_at=dec.decided_at, round=dec.round) if dec else None


def outs(db: Db, repo: DocRepo, items: list[versions.View], a: RepoAccess,
         outcomes: dict[uuid.UUID, str] | None = None) -> list[DocumentOut]:
    """Each document as the person sees it (the latest version, or the latest approved one)."""
    entries = metadata.entries(db, [v.doc for v in items if v.latest], repo.node)
    decisions = docs.decisions_for(db, items)
    makers = {u.id: u for u in db.scalars(select(AppUser).where(AppUser.id.in_({v.maker_id for v in items if v.maker_id})))}
    uploaded = {(r.document_id, r.number): r.created_at for r in db.scalars(select(DocumentVersion).where(
        DocumentVersion.document_id.in_([v.doc.id for v in items])))}
    out = []
    for v in items:
        d = v.doc
        act = docs.actions_for(db, v, a)
        shown = entries.get(d.id, []) if v.latest else versions.entries_from_snapshot(v.snapshot)
        out.append(DocumentOut(
            id=d.id, doc_repo_id=d.doc_repo_id, folder=d.folder, filename=v.filename, content_type=v.content_type,
            size_bytes=v.size_bytes, status=v.status, maker=ref(makers.get(v.maker_id)), created_at=d.created_at,
            updated_at=v.updated_at, submitted_at=v.submitted_at, last_decision=_decision(decisions.get(d.id)),
            metadata=[MetadataEntryOut(**e.__dict__) for e in shown],
            actions=DocumentActionsOut(edit=act.edit, submit=act.submit, delete=act.delete, discard=act.discard,
                                       versions=act.versions),
            version=v.version, uploaded_at=uploaded.get((d.id, v.version), d.created_at), latest=v.latest,
            approved_version=d.approved_version,
            outcome=(outcomes or {}).get(d.id),
        ))
    return out


def _one(db: Db, user: AppUser, repo_id: uuid.UUID, doc_id: uuid.UUID, published: bool = False) -> DocumentOut:
    repo, view, a = docs.get_view(db, user, repo_id, doc_id, published)
    return outs(db, repo, [view], a)[0]


def _views(db: Db, user: AppUser, repo_id: uuid.UUID, items: list[Document]) -> tuple[DocRepo, list[versions.View], RepoAccess]:
    repo = get_repo(db, repo_id)
    a = access_to(db, user, repo)
    return repo, versions.views(db, items, a), a


def _bulk(db: Db, user: AppUser, repo_id: uuid.UUID, result: docs.BulkResult, deleted: bool = False) -> BulkOut:
    repo, seen, a = _views(db, user, repo_id, [] if deleted else result.done)
    return BulkOut(done=outs(db, repo, seen, a),
                   skipped=[SkippedOut(id=s.document_id, filename=s.filename, reason=s.reason) for s in result.skipped])


@router.get("/doc-repos/{doc_repo_id}/documents", response_model=list[DocumentOut])
@readers
def list_documents(doc_repo_id: DocRepoId, db: Db, p: CurrentUser,
                   view: Annotated[str, Query(description="all, published (latest approved versions) or "
                                                          "in_progress (latest versions not yet approved)")] = "all",
                   ) -> list[DocumentOut]:
    """Makers and auditors see every status; checkers submitted ones; viewers, owners and admins approved ones."""
    repo, seen, a = docs.list_documents(db, me(db, p), doc_repo_id, view)
    return outs(db, repo, seen, a)


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
    uploaded = docs.upload(db, user, doc_repo_id, incoming)
    repo, seen, a = _views(db, user, doc_repo_id, [u.doc for u in uploaded])
    return outs(db, repo, seen, a, {u.doc.id: u.outcome for u in uploaded})


@router.get("/doc-repos/{doc_repo_id}/documents/{document_id}", response_model=DocumentOut)
@readers
def get_document(doc_repo_id: DocRepoId, document_id: DocumentId, db: Db, p: CurrentUser,
                 published: Annotated[bool, Query(description="Its latest approved version")] = False) -> DocumentOut:
    return _one(db, me(db, p), doc_repo_id, document_id, published)


@router.get("/doc-repos/{doc_repo_id}/documents/{document_id}/download", response_class=FileResponse)
@readers
def download(doc_repo_id: DocRepoId, document_id: DocumentId, db: Db, p: CurrentUser,
             published: Annotated[bool, Query(description="Its latest approved version")] = False) -> FileResponse:
    """The version the person sees (the latest, or for viewers the latest approved one)."""
    user = me(db, p)
    repo, view, _ = docs.get_view(db, user, doc_repo_id, document_id, published)
    return _file(db, user, repo, view.doc, view, view.version)


def _file(db: Db, user: AppUser, repo: DocRepo, doc: Document, f, number: int) -> FileResponse:
    path = docs.file_path(f)
    audit.record(db, "DOCUMENT_DOWNLOADED", actor=user, target=("document", doc.id), node_id=repo.hierarchy_node_id,
                 details={"filename": f.filename, "version": number})
    db.commit()
    return FileResponse(path, filename=f.filename, media_type=f.content_type or "application/octet-stream")


def _with_versions(db: Db, user: AppUser, repo_id: uuid.UUID, document_id: uuid.UUID) -> tuple[DocRepo, Document, RepoAccess]:
    repo, doc, a = docs.get_document(db, user, repo_id, document_id)
    if not versions.sees_versions(a):
        raise NotFound("No such document in this repository.")
    return repo, doc, a


@router.get("/doc-repos/{doc_repo_id}/documents/{document_id}/versions", response_model=list[VersionOut])
@readers
def list_versions(doc_repo_id: DocRepoId, document_id: DocumentId, db: Db, p: CurrentUser) -> list[VersionOut]:
    """Every version, newest first (makers, checkers and auditors; 404 for others)."""
    user = me(db, p)
    _, doc, a = _with_versions(db, user, doc_repo_id, document_id)
    items = versions.list_versions(db, doc)
    decisions = docs.version_decisions(db, items)
    can_upload = a.has(P.DOC_UPLOAD) and doc.status != "pending_approval"
    return [VersionOut(
        number=v.number, filename=v.filename, content_type=v.content_type, size_bytes=v.size_bytes, status=v.status,
        uploaded_by=ref(v.uploaded_by), created_at=v.created_at, submitted_at=v.submitted_at,
        superseded_at=v.superseded_at, discarded_at=v.discarded_at, restored_from=v.restored_from,
        approval_request_id=v.approval_request_id,
        latest=v.number == doc.version, approved=v.number == doc.approved_version,
        last_decision=_decision(decisions.get(v.id)),
        can_restore=can_upload and v.number != doc.version and v.discarded_at is None,
    ) for v in items]


@router.get("/doc-repos/{doc_repo_id}/documents/{document_id}/versions/{number}/download", response_class=FileResponse)
@readers
def download_version(doc_repo_id: DocRepoId, document_id: DocumentId, number: int, db: Db, p: CurrentUser) -> FileResponse:
    user = me(db, p)
    repo, doc, _ = _with_versions(db, user, doc_repo_id, document_id)
    return _file(db, user, repo, doc, versions.get_version(db, doc, number), number)


@router.post("/doc-repos/{doc_repo_id}/documents/{document_id}/versions/{number}/restore", response_model=DocumentOut,
             responses={409: {"description": "Waiting for approval, discarded, or already the latest"}})
@Can(P.DOC_UPLOAD, at=at_repo())
def restore_version(doc_repo_id: DocRepoId, document_id: DocumentId, number: int, db: Db, p: CurrentUser) -> DocumentOut:
    """Make an earlier version the latest again (its file and metadata), as a draft to submit."""
    user = me(db, p)
    docs.restore_version(db, user, doc_repo_id, document_id, number)
    return _one(db, user, doc_repo_id, document_id)


@router.post("/doc-repos/{doc_repo_id}/documents/{document_id}/discard-version", response_model=DocumentOut,
             responses={409: {"description": "Approved, waiting, or no earlier version"}})
@Can(P.DOC_UPLOAD, at=at_repo())
def discard_version(doc_repo_id: DocRepoId, document_id: DocumentId, db: Db, p: CurrentUser) -> DocumentOut:
    """Throw away the latest (unapproved) version; the document goes back to the version before."""
    user = me(db, p)
    docs.discard_version(db, user, doc_repo_id, document_id)
    return _one(db, user, doc_repo_id, document_id)


@router.get("/doc-repos/{doc_repo_id}/documents/{document_id}/history", response_model=list[RequestHistoryOut])
@readers
def document_history(doc_repo_id: DocRepoId, document_id: DocumentId, db: Db, p: CurrentUser) -> list[RequestHistoryOut]:
    """Every approval request for the document, newest first, with each round's decisions. People
    who see only the approved version (viewers) get that version's request only."""
    _, view, a = docs.get_view(db, me(db, p), doc_repo_id, document_id)
    items = docs.history(db, view.doc)
    if not versions.sees_versions(a):
        items = [h for h in items if h.request.id == view.approval_request_id]
    return history_out(items)


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

