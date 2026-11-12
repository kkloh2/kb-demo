"""Documents in a project: upload (files or folders), metadata, maker-checker review.

Status flow:  draft --submit (maker)--> pending_approval --approve (checker)--> approved
                ^                              |
                +----- rejected <--reject------+   (with a reason; the maker edits and resubmits)

Who sees which documents (project roles from the database; the department admin is a viewer):
    MAKER     every status (drafts included)
    CHECKER   pending_approval, approved, rejected
    VIEWER    approved

Metadata on a document:
    base     country, business unit, purpose, valid till: copied from the project at upload; the
             maker may override each one (base_overrides lists which)
    fields   values for the project's defined fields (ProjectField), consistent and searchable
    extra    fields the maker adds on top
    ai       phase 2: extracted from the file by an LLM in the background

Callers are endpoints guarded by @ProjectRoles: these functions enforce the document rules
(status, required fields, maker is never the checker), not who the caller is.
"""

import mimetypes
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, selectinload

from app.auth.identity import Principal
from app.core.config import get_settings
from app.core.errors import Conflict, InvalidRequest, NotFound
from app.db.base import utcnow
from app.documents.models import (
    BASE_FIELDS,
    Document,
    DocumentStatus,
    DocumentValue,
    FieldType,
    ProjectField,
)
from app.documents.service import ProjectAccess, access_to, get_project
from app.users.models import User
from app.users.service import get_by_lan_id

S = DocumentStatus
EDITABLE = {S.DRAFT.value, S.REJECTED.value}


# --------------------------------------------------------------------------- who sees what


def visible_statuses(access: ProjectAccess) -> set[str]:
    """Statuses the caller may see in the project (empty: none)."""
    statuses: set[str] = set()
    if "MAKER" in access.project_roles:
        statuses |= {s.value for s in S}
    if "CHECKER" in access.project_roles:
        statuses |= {S.PENDING.value, S.APPROVED.value, S.REJECTED.value}
    if "VIEWER" in access.project_roles or access.manage:  # the department admin is a viewer
        statuses.add(S.APPROVED.value)
    return statuses


@dataclass(frozen=True)
class DocumentActions:
    """What the caller can do with one document, for the UI (the server checks again)."""

    edit: bool  # metadata
    submit: bool
    review: bool  # approve or reject
    delete: bool


def actions_for(doc: Document, access: ProjectAccess, caller_id: int | None) -> DocumentActions:
    maker = access.upload
    editable = doc.status in EDITABLE
    return DocumentActions(
        edit=maker and editable,
        submit=maker and editable,
        review=access.review and doc.status == S.PENDING.value and doc.maker_id != caller_id,
        delete=maker and editable,
    )


def _caller(db: Session, principal: Principal) -> User | None:
    return get_by_lan_id(db, principal.lan_id)


# --------------------------------------------------------------------------- reading


def _query(project_id: int):
    return (
        select(Document)
        .where(Document.project_id == project_id)
        .options(selectinload(Document.values), selectinload(Document.maker), selectinload(Document.checker))
    )


def list_documents(db: Session, principal: Principal, project_id: int) -> tuple[list[Document], ProjectAccess]:
    """The project's documents the caller may see, by folder then name. The UI builds the folder
    tree from each document's folder."""
    project = get_project(db, project_id)
    access = access_to(db, principal, project)
    statuses = visible_statuses(access)
    docs = db.scalars(
        _query(project_id).where(Document.status.in_(statuses)).order_by(Document.folder, Document.filename)
    ).all()
    return list(docs), access


def get_document(db: Session, principal: Principal, project_id: int, document_id: int) -> tuple[Document, ProjectAccess]:
    """One document, if the caller may see it (NotFound otherwise, so hidden drafts stay hidden)."""
    project = get_project(db, project_id)
    access = access_to(db, principal, project)
    doc = db.scalar(_query(project_id).where(Document.id == document_id))
    if doc is None or doc.status not in visible_statuses(access):
        raise NotFound(f"No document {document_id} in this project.")
    return doc, access


def file_path(doc: Document) -> Path:
    path = get_settings().upload_dir / doc.storage_path
    if not path.is_file():
        raise NotFound("The file is missing from storage.")
    return path


# --------------------------------------------------------------------------- upload


@dataclass(frozen=True)
class IncomingFile:
    relative_path: str  # "report.pdf", or "Policies/2026/report.pdf" from a folder upload
    content_type: str | None
    data: bytes


def clean_relative_path(raw: str) -> tuple[str, str]:
    """("Policies/2026", "report.pdf") from a browser-supplied path, safe to use: no "..", no
    absolute paths, no empty segments, backslashes treated as separators."""
    parts = [p.strip() for p in raw.replace("\\", "/").split("/")]
    parts = [p for p in parts if p and p not in (".", "..")]
    if not parts:
        raise InvalidRequest("A file has no name.")
    name = re.sub(r"[\x00-\x1f]", "", parts[-1])[:200]
    folder = "/".join(re.sub(r"[\x00-\x1f]", "", p)[:100] for p in parts[:-1])[:500]
    if not name:
        raise InvalidRequest("A file has no name.")
    return folder, name


def upload(db: Session, principal: Principal, project_id: int, files: list[IncomingFile]) -> list[Document]:
    """Add the files to the project as drafts, with the project's base metadata copied onto each.
    All-or-nothing: one bad file (type, size) and nothing is stored."""
    s = get_settings()
    if not files:
        raise InvalidRequest("Choose at least one file.")
    if len(files) > s.max_files_per_upload:
        raise InvalidRequest(f"Upload at most {s.max_files_per_upload} files at a time.")
    allowed = {e.lower() for e in s.allowed_upload_extensions}
    limit = s.max_upload_mb * 1024 * 1024
    planned = []
    for f in files:
        folder, name = clean_relative_path(f.relative_path)
        ext = PurePosixPath(name).suffix.lower()
        if ext not in allowed:
            raise InvalidRequest(f"{name}: {ext or 'files without an extension'} can't be uploaded. "
                                 f"Allowed: {', '.join(sorted(allowed))}.")
        if len(f.data) > limit:
            raise InvalidRequest(f"{name} is larger than {s.max_upload_mb} MB.")
        if not f.data:
            raise InvalidRequest(f"{name} is empty.")
        planned.append((folder, name, f))

    project = get_project(db, project_id)
    maker = _caller(db, principal)
    batch = str(uuid.uuid4())
    taken = {(d.folder, d.filename) for d in db.scalars(select(Document).where(Document.project_id == project_id))}
    created: list[tuple[Document, bytes]] = []
    for folder, name, f in planned:
        name = _unique_name(taken, folder, name)
        taken.add((folder, name))
        doc = Document(
            project_id=project_id, folder=folder, filename=name, size_bytes=len(f.data),
            content_type=f.content_type or mimetypes.guess_type(name)[0], storage_path="", upload_batch=batch,
            status=S.DRAFT.value, maker_id=maker.id if maker else None,
            country=project.country, business_unit=project.business_unit, purpose=project.purpose,
            valid_till=project.valid_till, base_overrides=[], ai_metadata={},
        )
        db.add(doc)
        created.append((doc, f.data))
    db.flush()  # document ids for the storage paths

    written: list[Path] = []
    try:
        for doc, data in created:
            relative = PurePosixPath("projects", str(project_id), str(doc.id), doc.filename)
            target = s.upload_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            written.append(target)
            doc.storage_path = str(relative)
        db.commit()
    except Exception:
        db.rollback()
        for path in written:
            shutil.rmtree(path.parent, ignore_errors=True)
        raise
    return [d for d, _ in created]


def _unique_name(taken: set[tuple[str, str]], folder: str, name: str) -> str:
    """report.pdf, then report (2).pdf, report (3).pdf ... within the folder."""
    if (folder, name) not in taken:
        return name
    stem, suffix = PurePosixPath(name).stem, PurePosixPath(name).suffix
    n = 2
    while (folder, f"{stem} ({n}){suffix}") in taken:
        n += 1
    return f"{stem} ({n}){suffix}"


# --------------------------------------------------------------------------- metadata


@dataclass(frozen=True)
class MetadataIn:
    base: dict[str, str | None]  # any of BASE_FIELDS; "" or None clears
    fields: dict[str, str]  # project field key -> value
    extra: dict[str, str]  # maker's own key -> value


def update_metadata(db: Session, principal: Principal, project_id: int, document_id: int, m: MetadataIn) -> Document:
    """Replace the document's metadata. Only drafts and rejected documents can be edited."""
    doc, _ = get_document(db, principal, project_id, document_id)
    if doc.status not in EDITABLE:
        raise Conflict(f"{doc.filename} is {_status_label(doc.status)}; only drafts and rejected documents can be edited.")
    project = get_project(db, project_id)
    defined = {f.key: f for f in list_fields(db, project_id)}

    # base: set values, then record which differ from the project
    unknown = set(m.base) - set(BASE_FIELDS)
    if unknown:
        raise InvalidRequest(f"Base metadata is {', '.join(BASE_FIELDS)}, not {', '.join(sorted(unknown))}.")
    for key, value in m.base.items():
        if key == "valid_till":
            doc.valid_till = _parse_date(value, "Valid till") if value else None
        else:
            setattr(doc, key, (value or "").strip())
    doc.base_overrides = [k for k in BASE_FIELDS if getattr(doc, k) != getattr(project, k)]

    # project fields: validated against their definitions
    values: list[DocumentValue] = []
    for key, raw in m.fields.items():
        field = defined.get(key)
        if field is None:
            raise InvalidRequest(f"{key!r} isn't one of this project's fields.")
        value = (raw or "").strip()
        if value:
            _check_field_value(field, value)
            values.append(DocumentValue(source="field", key=key, value=value))
    # extra: the maker's own keys, which can't shadow a project field
    for raw_key, raw in m.extra.items():
        key = " ".join(raw_key.split())[:64]  # kept as typed, e.g. "Reviewed by legal"
        if not key:
            raise InvalidRequest("Give each additional field a name.")
        if _clean_key(key) in defined:
            raise InvalidRequest(f"{key!r} is one of this project's fields; fill it in there.")
        if (raw or "").strip():
            values.append(DocumentValue(source="extra", key=key, value=raw.strip()))
    keys = [(v.source, v.key) for v in values]
    if len(keys) != len(set(keys)):
        raise InvalidRequest("A field is given twice.")
    doc.values = values
    doc.updated_at = utcnow()
    db.commit()
    return get_document(db, principal, project_id, document_id)[0]


def missing_required(db: Session, doc: Document) -> list[str]:
    """Labels of the project's required fields the document hasn't filled in."""
    filled = {v.key for v in doc.values if v.source == "field" and v.value}
    return [f.label for f in list_fields(db, doc.project_id) if f.required and f.key not in filled]


# --------------------------------------------------------------------------- submit & review (bulk)


@dataclass(frozen=True)
class Skipped:
    document_id: int
    filename: str
    reason: str


@dataclass(frozen=True)
class BulkResult:
    done: list[Document]
    skipped: list[Skipped]


def submit(db: Session, principal: Principal, project_id: int, ids: list[int]) -> BulkResult:
    """Send drafts (or rejected documents) to the checkers. Each document that can't go (wrong
    status, a required field missing) is skipped with the reason; the others go."""
    docs = _load_many(db, principal, project_id, ids)
    done, skipped = [], []
    now = utcnow()
    for doc in docs:
        if doc.status not in EDITABLE:
            skipped.append(Skipped(doc.id, doc.filename, f"It's {_status_label(doc.status)}."))
            continue
        missing = missing_required(db, doc)
        if missing:
            skipped.append(Skipped(doc.id, doc.filename, f"Fill in {', '.join(missing)} first."))
            continue
        doc.status, doc.submitted_at = S.PENDING.value, now
        doc.checker, doc.decided_at, doc.rejection_reason = None, None, None
        done.append(doc)
    db.commit()
    return BulkResult(done, skipped)


def review(db: Session, principal: Principal, project_id: int, ids: list[int], approve: bool,
           reason: str | None) -> BulkResult:
    """Approve, or reject with a reason, pending documents. A checker never decides on a document
    they uploaded themselves."""
    reason = (reason or "").strip()
    if not approve and not reason:
        raise InvalidRequest("Give a reason for rejecting.")
    checker = _caller(db, principal)
    docs = _load_many(db, principal, project_id, ids)
    done, skipped = [], []
    now = utcnow()
    for doc in docs:
        if doc.status != S.PENDING.value:
            skipped.append(Skipped(doc.id, doc.filename, f"It's {_status_label(doc.status)}, not pending approval."))
            continue
        if checker is not None and doc.maker_id == checker.id:
            skipped.append(Skipped(doc.id, doc.filename, "You uploaded it; another checker has to decide."))
            continue
        doc.status = S.APPROVED.value if approve else S.REJECTED.value
        doc.checker = checker  # sets checker_id too, and keeps the loaded relationship current
        doc.decided_at = now
        doc.rejection_reason = None if approve else reason
        done.append(doc)
    db.commit()
    return BulkResult(done, skipped)


def delete_documents(db: Session, principal: Principal, project_id: int, ids: list[int]) -> BulkResult:
    """Delete drafts and rejected documents (and their files). Others are skipped."""
    docs = _load_many(db, principal, project_id, ids)
    done, skipped, paths = [], [], []
    for doc in docs:
        if doc.status not in EDITABLE:
            skipped.append(Skipped(doc.id, doc.filename, f"It's {_status_label(doc.status)}."))
            continue
        paths.append(get_settings().upload_dir / doc.storage_path)
        done.append(doc)
        db.delete(doc)
    db.commit()
    for path in paths:
        shutil.rmtree(path.parent, ignore_errors=True)
    return BulkResult(done, skipped)


def delete_project_files(project_id: int) -> None:
    """Remove the stored files of a deleted project."""
    shutil.rmtree(get_settings().upload_dir / "projects" / str(project_id), ignore_errors=True)


def _load_many(db: Session, principal: Principal, project_id: int, ids: list[int]) -> list[Document]:
    """The documents, all visible to the caller in this project; NotFound if any isn't."""
    if not ids:
        raise InvalidRequest("Choose at least one document.")
    if len(ids) > 500:
        raise InvalidRequest("Choose at most 500 documents at a time.")
    project = get_project(db, project_id)
    statuses = visible_statuses(access_to(db, principal, project))
    docs = {d.id: d for d in db.scalars(_query(project_id).where(Document.id.in_(set(ids))))}
    missing = [i for i in dict.fromkeys(ids) if i not in docs or docs[i].status not in statuses]
    if missing:
        raise NotFound(f"No document {', '.join(map(str, missing))} in this project.")
    return [docs[i] for i in dict.fromkeys(ids)]


# --------------------------------------------------------------------------- project fields


def list_fields(db: Session, project_id: int) -> list[ProjectField]:
    return list(db.scalars(
        select(ProjectField).where(ProjectField.project_id == project_id).order_by(ProjectField.position, ProjectField.id)
    ))


@dataclass(frozen=True)
class FieldIn:
    label: str
    key: str = ""  # derived from the label when empty
    type: str = FieldType.TEXT.value
    options: tuple[str, ...] = ()
    required: bool = False


def replace_fields(db: Session, project_id: int, fields: list[FieldIn]) -> list[ProjectField]:
    """Make the project's fields exactly `fields`, in this order. Values of a removed field stay on
    the documents as the maker's own (extra) fields, so nothing typed in is lost."""
    get_project(db, project_id)
    cleaned: list[ProjectField] = []
    seen: set[str] = set()
    for position, f in enumerate(fields):
        label = f.label.strip()
        if not label:
            raise InvalidRequest("Every field needs a label.")
        key = _clean_key(f.key or label)
        if key in seen:
            raise InvalidRequest(f"Two fields would both be called {key!r}.")
        if key in BASE_FIELDS:
            raise InvalidRequest(f"{label!r} is already base metadata.")
        seen.add(key)
        if f.type not in {t.value for t in FieldType}:
            raise InvalidRequest(f"Field types are text, date and select, not {f.type!r}.")
        options = [o.strip() for o in f.options if o.strip()]
        if f.type == FieldType.SELECT.value and not options:
            raise InvalidRequest(f"{label!r} is a select field; give it options.")
        cleaned.append(ProjectField(project_id=project_id, key=key, label=label, type=f.type,
                                    options=options if f.type == FieldType.SELECT.value else [],
                                    required=f.required, position=position))

    removed = {f.key for f in list_fields(db, project_id)} - seen
    if removed:  # keep what makers typed, as their own fields
        doc_ids = select(Document.id).where(Document.project_id == project_id)
        db.execute(
            update(DocumentValue)
            .where(DocumentValue.document_id.in_(doc_ids), DocumentValue.source == "field", DocumentValue.key.in_(removed))
            .values(source="extra")
        )
    db.execute(delete(ProjectField).where(ProjectField.project_id == project_id))
    db.flush()
    db.add_all(cleaned)
    db.commit()
    return list_fields(db, project_id)


# --------------------------------------------------------------------------- helpers


def _clean_key(raw: str) -> str:
    """"Product code" -> "product_code"."""
    key = re.sub(r"[^a-z0-9]+", "_", raw.strip().lower()).strip("_")[:64]
    if not key:
        raise InvalidRequest(f"{raw!r} can't be used as a field name.")
    return key


def _parse_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise InvalidRequest(f"{label}: use a date like 2027-12-31.") from None


def _check_field_value(field: ProjectField, value: str) -> None:
    if field.type == FieldType.DATE.value:
        _parse_date(value, field.label)
    elif field.type == FieldType.SELECT.value and value not in field.options:
        raise InvalidRequest(f"{field.label}: choose one of {', '.join(field.options)}.")


def _status_label(status: str) -> str:
    return {"draft": "a draft", "pending_approval": "pending approval", "approved": "approved",
            "rejected": "rejected"}.get(status, status)

