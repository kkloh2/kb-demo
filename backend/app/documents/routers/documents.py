"""Document endpoints (all inside one project).

    GET    /api/projects/{id}/fields                      anyone who sees the project   its metadata fields
    PUT    /api/projects/{id}/fields                      the department's admin        replace them
    GET    /api/projects/{id}/documents                   project role or dept admin    the documents the caller may see
    POST   /api/projects/{id}/documents                   project maker                 upload files / a folder (multipart)
    GET    /api/projects/{id}/documents/{doc}             project role or dept admin
    GET    /api/projects/{id}/documents/{doc}/download    project role or dept admin
    PUT    /api/projects/{id}/documents/{doc}/metadata    project maker                 drafts and rejected only
    POST   /api/projects/{id}/documents/submit            project maker                 {ids}: send for review
    POST   /api/projects/{id}/documents/review            project checker               {ids, decision, reason}
    POST   /api/projects/{id}/documents/delete            project maker                 {ids}: drafts and rejected only
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
from app.documents.authorization import ProjectRoles
from app.documents.models import Document, ProjectField
from app.documents.routers.projects import ANY_PROJECT_ROLE, DEPARTMENT_ADMIN, ProjectId
from app.documents.schemas import (
    BaseMetadata,
    BulkOut,
    DocumentActionsOut,
    DocumentIds,
    DocumentList,
    DocumentOut,
    FieldDef,
    MetadataUpdate,
    PersonRef,
    ReviewIn,
    SkippedOut,
)
from app.documents.service import ProjectAccess
from app.users.service import get_by_lan_id

router = APIRouter(tags=["documents"])

DocumentId = Annotated[int, Path(ge=1, description="Document id")]
_403 = {403: {"description": "Caller lacks the required role"}}
_404 = {404: {"description": "No such project or document (or not visible to the caller)"}}

# Who may read a project's documents: any project role, or the department's admin (a viewer).
readers = ProjectRoles(*ANY_PROJECT_ROLE, department_roles=DEPARTMENT_ADMIN)


def _person(user) -> PersonRef | None:
    return PersonRef(lan_id=user.lan_id, display_name=user.display_name) if user else None


def _field_out(f: ProjectField) -> FieldDef:
    return FieldDef(key=f.key, label=f.label, type=f.type, options=f.options, required=f.required)


def _doc_out(db: Db, doc: Document, access: ProjectAccess, caller_id: int | None) -> DocumentOut:
    a = docs.actions_for(doc, access, caller_id)
    return DocumentOut(
        id=doc.id, project_id=doc.project_id, folder=doc.folder, filename=doc.filename,
        content_type=doc.content_type, size_bytes=doc.size_bytes, status=doc.status,
        maker=_person(doc.maker), checker=_person(doc.checker),
        created_at=doc.created_at, updated_at=doc.updated_at, submitted_at=doc.submitted_at,
        decided_at=doc.decided_at, rejection_reason=doc.rejection_reason,
        base=BaseMetadata(country=doc.country, business_unit=doc.business_unit, purpose=doc.purpose,
                          valid_till=doc.valid_till),
        base_overrides=doc.base_overrides,
        fields={v.key: v.value for v in doc.values if v.source == "field"},
        extra={v.key: v.value for v in doc.values if v.source == "extra"},
        ai_metadata=doc.ai_metadata,
        missing_required=docs.missing_required(db, doc),
        actions=DocumentActionsOut(edit=a.edit, submit=a.submit, review=a.review, delete=a.delete),
    )


def _caller_id(db: Db, p: Principal) -> int | None:
    user = get_by_lan_id(db, p.lan_id)
    return user.id if user else None


def _bulk_out(db: Db, p: Principal, project_id: int, result: docs.BulkResult, deleted: bool = False) -> BulkOut:
    from app.documents.service import access_to, get_project

    access = access_to(db, p, get_project(db, project_id))
    caller = _caller_id(db, p)
    return BulkOut(
        done=[] if deleted else [_doc_out(db, d, access, caller) for d in result.done],
        skipped=[SkippedOut(id=s.document_id, filename=s.filename, reason=s.reason) for s in result.skipped],
    )


# --------------------------------------------------------------------------- fields


@router.get("/projects/{project_id}/fields", response_model=list[FieldDef], responses={**_403, **_404})
@ProjectRoles(*ANY_PROJECT_ROLE, department_roles=("DEPARTMENT_ADMIN", "VIEWER"))
def list_fields(project_id: ProjectId, db: Db) -> list[FieldDef]:
    """The metadata fields the project's documents fill in, in order."""
    return [_field_out(f) for f in docs.list_fields(db, project_id)]


@router.put("/projects/{project_id}/fields", response_model=list[FieldDef], responses={**_403, **_404})
@ProjectRoles(department_roles=DEPARTMENT_ADMIN)
def replace_fields(project_id: ProjectId, body: list[FieldDef], db: Db) -> list[FieldDef]:
    """Make the project's fields exactly these, in this order. Values of a removed field stay on
    the documents as the maker's own fields."""
    fields = [docs.FieldIn(label=f.label, key=f.key, type=f.type, options=tuple(f.options), required=f.required)
              for f in body]
    return [_field_out(f) for f in docs.replace_fields(db, project_id, fields)]


# --------------------------------------------------------------------------- documents


@router.get("/projects/{project_id}/documents", response_model=DocumentList, responses={**_403, **_404})
@readers
def list_documents(project_id: ProjectId, db: Db, p: CurrentUser) -> DocumentList:
    """The documents the caller may see (makers: all; checkers: submitted ones; viewers and the
    department admin: approved), with the project's fields."""
    items, access = docs.list_documents(db, p, project_id)
    caller = _caller_id(db, p)
    return DocumentList(
        documents=[_doc_out(db, d, access, caller) for d in items],
        fields=[_field_out(f) for f in docs.list_fields(db, project_id)],
    )


@router.post(
    "/projects/{project_id}/documents",
    status_code=status.HTTP_201_CREATED,
    response_model=list[DocumentOut],
    responses={**_403, **_404, 422: {"description": "A file's type, size or count isn't allowed"}},
)
@ProjectRoles("MAKER")
async def upload_documents(
    project_id: ProjectId,
    db: Db,
    p: CurrentUser,
    files: Annotated[list[UploadFile], File(description="The files")],
    paths: Annotated[list[str] | None, Form(description="Relative path of each file in a folder upload, "
                                                       "e.g. Policies/2026/report.pdf; same order as files")] = None,
) -> list[DocumentOut]:
    """Upload files, or a folder (its structure is kept). Each becomes a draft with the project's
    base metadata. All-or-nothing: one bad file and nothing is stored."""
    if paths is not None and len(paths) != len(files):
        raise InvalidRequest("Send one path per file, or none.")
    limit = get_settings().max_upload_mb * 1024 * 1024
    incoming = []
    for i, f in enumerate(files):
        data = await f.read(limit + 1)  # one byte over the limit is enough to refuse it
        incoming.append(docs.IncomingFile(relative_path=paths[i] if paths else (f.filename or ""),
                                          content_type=f.content_type, data=data))
    created = docs.upload(db, p, project_id, incoming)
    items, access = docs.list_documents(db, p, project_id)
    by_id = {d.id: d for d in items}
    caller = _caller_id(db, p)
    return [_doc_out(db, by_id[d.id], access, caller) for d in created]


@router.get("/projects/{project_id}/documents/{document_id}", response_model=DocumentOut, responses={**_403, **_404})
@readers
def get_document(project_id: ProjectId, document_id: DocumentId, db: Db, p: CurrentUser) -> DocumentOut:
    doc, access = docs.get_document(db, p, project_id, document_id)
    return _doc_out(db, doc, access, _caller_id(db, p))


@router.get("/projects/{project_id}/documents/{document_id}/download", response_class=FileResponse,
            responses={**_403, **_404})
@readers
def download_document(project_id: ProjectId, document_id: DocumentId, db: Db, p: CurrentUser) -> FileResponse:
    doc, _ = docs.get_document(db, p, project_id, document_id)
    return FileResponse(docs.file_path(doc), filename=doc.filename,
                        media_type=doc.content_type or "application/octet-stream")


@router.put(
    "/projects/{project_id}/documents/{document_id}/metadata",
    response_model=DocumentOut,
    responses={**_403, **_404, 409: {"description": "Not a draft or rejected document"}},
)
@ProjectRoles("MAKER")
def update_metadata(project_id: ProjectId, document_id: DocumentId, body: MetadataUpdate, db: Db,
                    p: CurrentUser) -> DocumentOut:
    """Replace the document's metadata: base (overrides the project's), project fields, and extra
    fields the maker adds."""
    base = body.base.model_dump()
    base["valid_till"] = base["valid_till"].isoformat() if base["valid_till"] else None
    doc = docs.update_metadata(db, p, project_id, document_id,
                               docs.MetadataIn(base=base, fields=body.fields, extra=body.extra))
    _, access = docs.get_document(db, p, project_id, document_id)
    return _doc_out(db, doc, access, _caller_id(db, p))


@router.post("/projects/{project_id}/documents/submit", response_model=BulkOut, responses={**_403, **_404})
@ProjectRoles("MAKER")
def submit_documents(project_id: ProjectId, body: DocumentIds, db: Db, p: CurrentUser) -> BulkOut:
    """Send documents for review. Any that can't go are skipped, with the reason."""
    return _bulk_out(db, p, project_id, docs.submit(db, p, project_id, body.ids))


@router.post("/projects/{project_id}/documents/review", response_model=BulkOut, responses={**_403, **_404})
@ProjectRoles("CHECKER")
def review_documents(project_id: ProjectId, body: ReviewIn, db: Db, p: CurrentUser) -> BulkOut:
    """Approve, or reject with a reason, pending documents. Any that can't be decided are skipped."""
    if body.decision not in ("approve", "reject"):
        raise InvalidRequest("decision is approve or reject.")
    result = docs.review(db, p, project_id, body.ids, approve=body.decision == "approve", reason=body.reason)
    return _bulk_out(db, p, project_id, result)


@router.post("/projects/{project_id}/documents/delete", response_model=BulkOut, responses={**_403, **_404})
@ProjectRoles("MAKER")
def delete_documents(project_id: ProjectId, body: DocumentIds, db: Db, p: CurrentUser) -> BulkOut:
    """Delete drafts and rejected documents. Others are skipped."""
    return _bulk_out(db, p, project_id, docs.delete_documents(db, p, project_id, body.ids), deleted=True)
