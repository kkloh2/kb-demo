"""Document endpoints (all inside one doc-repo).

    PUT    /api/doc-repos/{id}/repository-metadata         the department's admin        [{key, value}]: replace it
    GET    /api/doc-repos/{id}/documents                   doc-repo role or dept admin    the documents the caller may see
    POST   /api/doc-repos/{id}/documents                   doc-repo maker                 upload files / a folder (multipart)
    GET    /api/doc-repos/{id}/documents/{doc}             doc-repo role or dept admin
    GET    /api/doc-repos/{id}/documents/{doc}/download    doc-repo role or dept admin
    PUT    /api/doc-repos/{id}/documents/{doc}/metadata    doc-repo maker                 drafts and rejected only
    POST   /api/doc-repos/{id}/documents/submit            doc-repo maker                 {ids}: send for review
    POST   /api/doc-repos/{id}/documents/review            doc-repo checker               {ids, decision, reason}
    POST   /api/doc-repos/{id}/documents/delete            doc-repo maker                 {ids}: drafts and rejected only
"""

from typing import Annotated

from fastapi import APIRouter, File, Form, Path, UploadFile, status
from fastapi.responses import FileResponse

from app.auth.dependencies import CurrentUser
from app.auth.identity import Principal
from app.core.config import get_settings
from app.core.errors import InvalidRequest
from app.db.session import Db
from app.documents import documents as docs
from app.documents.authorization import DocRepoRoles
from app.documents.models import Document
from app.documents.routers.doc_repos import ANY_DOC_REPO_ROLE, DEPARTMENT_ADMIN, DocRepoId
from app.documents.schemas import (
    DepartmentMetadata,
    BulkOut,
    DocumentActionsOut,
    DocumentIds,
    DocumentList,
    DocumentOut,
    MetadataPair,
    MetadataUpdate,
    PersonRef,
    ReviewIn,
    SkippedOut,
)
from app.documents.service import DocRepoAccess, get_doc_repo
from app.users.service import get_by_lan_id

router = APIRouter(tags=["documents"])

DocumentId = Annotated[int, Path(ge=1, description="Document id")]
_403 = {403: {"description": "Caller lacks the required role"}}
_404 = {404: {"description": "No such doc-repo or document (or not visible to the caller)"}}

# Who may read a doc-repo's documents: any doc-repo role, or the department's admin (a viewer).
readers = DocRepoRoles(*ANY_DOC_REPO_ROLE, department_roles=DEPARTMENT_ADMIN)


def _person(user) -> PersonRef | None:
    return PersonRef(lan_id=user.lan_id, display_name=user.display_name) if user else None


def _doc_out(db: Db, doc: Document, access: DocRepoAccess, caller_id: int | None) -> DocumentOut:
    a = docs.actions_for(doc, access, caller_id)
    return DocumentOut(
        id=doc.id, doc_repo_id=doc.doc_repo_id, folder=doc.folder, filename=doc.filename,
        content_type=doc.content_type, size_bytes=doc.size_bytes, status=doc.status,
        maker=_person(doc.maker), checker=_person(doc.checker),
        created_at=doc.created_at, updated_at=doc.updated_at, submitted_at=doc.submitted_at,
        decided_at=doc.decided_at, rejection_reason=doc.rejection_reason,
        department_metadata=DepartmentMetadata(**doc.department_metadata),
        department_overrides=doc.department_overrides,
        repository_metadata={v.key: v.value for v in doc.values if v.source == "field"},
        repository_overrides=docs.repository_overrides(doc, doc.doc_repo.repository_metadata),
        extra={v.key: v.value for v in doc.values if v.source == "extra"},
        ai_metadata=doc.ai_metadata,
        actions=DocumentActionsOut(edit=a.edit, submit=a.submit, review=a.review, delete=a.delete),
    )


def _caller_id(db: Db, p: Principal) -> int | None:
    user = get_by_lan_id(db, p.lan_id)
    return user.id if user else None


def _bulk_out(db: Db, p: Principal, doc_repo_id: int, result: docs.BulkResult, deleted: bool = False) -> BulkOut:
    from app.documents.service import access_to, get_doc_repo

    access = access_to(db, p, get_doc_repo(db, doc_repo_id))
    caller = _caller_id(db, p)
    return BulkOut(
        done=[] if deleted else [_doc_out(db, d, access, caller) for d in result.done],
        skipped=[SkippedOut(id=s.document_id, filename=s.filename, reason=s.reason) for s in result.skipped],
    )


# --------------------------------------------------------------------------- repository metadata


@router.put("/doc-repos/{doc_repo_id}/repository-metadata", response_model=list[MetadataPair],
            responses={**_403, **_404})
@DocRepoRoles(department_roles=DEPARTMENT_ADMIN)
def replace_repository_metadata(doc_repo_id: DocRepoId, body: list[MetadataPair], db: Db) -> list[MetadataPair]:
    """Make the doc-repo's repository metadata exactly these key/value pairs, in this order. New
    documents start with these values; a removed key's values stay on documents as the maker's own fields."""
    pairs = docs.replace_repository_metadata(db, doc_repo_id, [(m.key, m.value) for m in body])
    return [MetadataPair(**m) for m in pairs]


# --------------------------------------------------------------------------- documents


@router.get("/doc-repos/{doc_repo_id}/documents", response_model=DocumentList, responses={**_403, **_404})
@readers
def list_documents(doc_repo_id: DocRepoId, db: Db, p: CurrentUser) -> DocumentList:
    """The documents the caller may see (makers: all; checkers: submitted ones; viewers and the
    department admin: approved), with the doc-repo's repository metadata."""
    items, access = docs.list_documents(db, p, doc_repo_id)
    caller = _caller_id(db, p)
    return DocumentList(
        documents=[_doc_out(db, d, access, caller) for d in items],
        repository_metadata=[MetadataPair(**m) for m in get_doc_repo(db, doc_repo_id).repository_metadata],
    )


@router.post(
    "/doc-repos/{doc_repo_id}/documents",
    status_code=status.HTTP_201_CREATED,
    response_model=list[DocumentOut],
    responses={**_403, **_404, 422: {"description": "A file's type, size or count isn't allowed"}},
)
@DocRepoRoles("MAKER")
async def upload_documents(
    doc_repo_id: DocRepoId,
    db: Db,
    p: CurrentUser,
    files: Annotated[list[UploadFile], File(description="The files")],
    paths: Annotated[list[str] | None, Form(description="Relative path of each file in a folder upload, "
                                                       "e.g. Policies/2026/report.pdf; same order as files")] = None,
) -> list[DocumentOut]:
    """Upload files, or a folder (its structure is kept). Each becomes a draft with the doc-repo's
    department metadata. All-or-nothing: one bad file and nothing is stored."""
    if paths is not None and len(paths) != len(files):
        raise InvalidRequest("Send one path per file, or none.")
    limit = get_settings().max_upload_mb * 1024 * 1024
    incoming = []
    for i, f in enumerate(files):
        data = await f.read(limit + 1)  # one byte over the limit is enough to refuse it
        incoming.append(docs.IncomingFile(relative_path=paths[i] if paths else (f.filename or ""),
                                          content_type=f.content_type, data=data))
    created = docs.upload(db, p, doc_repo_id, incoming)
    items, access = docs.list_documents(db, p, doc_repo_id)
    by_id = {d.id: d for d in items}
    caller = _caller_id(db, p)
    return [_doc_out(db, by_id[d.id], access, caller) for d in created]


@router.get("/doc-repos/{doc_repo_id}/documents/{document_id}", response_model=DocumentOut, responses={**_403, **_404})
@readers
def get_document(doc_repo_id: DocRepoId, document_id: DocumentId, db: Db, p: CurrentUser) -> DocumentOut:
    doc, access = docs.get_document(db, p, doc_repo_id, document_id)
    return _doc_out(db, doc, access, _caller_id(db, p))


@router.get("/doc-repos/{doc_repo_id}/documents/{document_id}/download", response_class=FileResponse,
            responses={**_403, **_404})
@readers
def download_document(doc_repo_id: DocRepoId, document_id: DocumentId, db: Db, p: CurrentUser) -> FileResponse:
    doc, _ = docs.get_document(db, p, doc_repo_id, document_id)
    return FileResponse(docs.file_path(doc), filename=doc.filename,
                        media_type=doc.content_type or "application/octet-stream")


@router.put(
    "/doc-repos/{doc_repo_id}/documents/{document_id}/metadata",
    response_model=DocumentOut,
    responses={**_403, **_404, 409: {"description": "Not a draft or rejected document"}},
)
@DocRepoRoles("MAKER")
def update_metadata(doc_repo_id: DocRepoId, document_id: DocumentId, body: MetadataUpdate, db: Db,
                    p: CurrentUser) -> DocumentOut:
    """Replace the document's metadata: department metadata and repository metadata (both start from
    the doc-repo's), and extra fields the maker adds."""
    doc = docs.update_metadata(db, p, doc_repo_id, document_id,
                               docs.MetadataIn(department_metadata=body.department_metadata.model_dump(), repository_metadata=body.repository_metadata, extra=body.extra))
    _, access = docs.get_document(db, p, doc_repo_id, document_id)
    return _doc_out(db, doc, access, _caller_id(db, p))


@router.post("/doc-repos/{doc_repo_id}/documents/submit", response_model=BulkOut, responses={**_403, **_404})
@DocRepoRoles("MAKER")
def submit_documents(doc_repo_id: DocRepoId, body: DocumentIds, db: Db, p: CurrentUser) -> BulkOut:
    """Send documents for review. Any that can't go are skipped, with the reason."""
    return _bulk_out(db, p, doc_repo_id, docs.submit(db, p, doc_repo_id, body.ids))


@router.post("/doc-repos/{doc_repo_id}/documents/review", response_model=BulkOut, responses={**_403, **_404})
@DocRepoRoles("CHECKER")
def review_documents(doc_repo_id: DocRepoId, body: ReviewIn, db: Db, p: CurrentUser) -> BulkOut:
    """Approve, or reject with a reason, pending documents. Any that can't be decided are skipped."""
    if body.decision not in ("approve", "reject"):
        raise InvalidRequest("decision is approve or reject.")
    result = docs.review(db, p, doc_repo_id, body.ids, approve=body.decision == "approve", reason=body.reason)
    return _bulk_out(db, p, doc_repo_id, result)


@router.post("/doc-repos/{doc_repo_id}/documents/delete", response_model=BulkOut, responses={**_403, **_404})
@DocRepoRoles("MAKER")
def delete_documents(doc_repo_id: DocRepoId, body: DocumentIds, db: Db, p: CurrentUser) -> BulkOut:
    """Delete drafts and rejected documents. Others are skipped."""
    return _bulk_out(db, p, doc_repo_id, docs.delete_documents(db, p, doc_repo_id, body.ids), deleted=True)
