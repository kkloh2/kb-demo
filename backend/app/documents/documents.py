"""Documents in a doc-repo: upload (files or folders), metadata, maker-checker review.

Status flow:  draft --submit (maker)--> pending_approval --approve (checker)--> approved
                ^                              |
                +----- rejected <--reject------+   (with a reason; the maker edits and resubmits)

Who sees which documents (doc-repo roles from the database; the department admin is a viewer):
    MAKER     every status (drafts included)
    CHECKER   pending_approval, approved, rejected
    VIEWER    approved

Metadata on a document:
    department  department, business unit, country (one JSON value): copied from the doc-repo
                at upload; the maker may override each one (department_overrides lists which)
    repository  values for the doc-repo's repository metadata keys (text), consistent and searchable
    extra    fields the maker adds on top
    ai       phase 2: extracted from the file by an LLM in the background

Callers are endpoints guarded by @DocRepoRoles: these functions enforce the document rules
(status, required fields, maker is never the checker), not who the caller is.
"""

import mimetypes
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.auth.identity import Principal
from app.core.config import get_settings
from app.core.errors import Conflict, InvalidRequest, NotFound
from app.db.base import utcnow
from app.documents.models import (
    DEPARTMENT_METADATA_KEYS,
    Document,
    DocumentStatus,
    DocumentValue,
)
from app.documents.service import DocRepoAccess, access_to, clean_department_metadata, get_doc_repo
from app.users.models import User
from app.users.service import get_by_lan_id

S = DocumentStatus
EDITABLE = {S.DRAFT.value, S.REJECTED.value}


# --------------------------------------------------------------------------- who sees what


def visible_statuses(access: DocRepoAccess) -> set[str]:
    """Statuses the caller may see in the doc-repo (empty: none)."""
    statuses: set[str] = set()
    if "MAKER" in access.doc_repo_roles:
        statuses |= {s.value for s in S}
    if "CHECKER" in access.doc_repo_roles:
        statuses |= {S.PENDING.value, S.APPROVED.value, S.REJECTED.value}
    if "VIEWER" in access.doc_repo_roles or access.manage:  # the department admin is a viewer
        statuses.add(S.APPROVED.value)
    return statuses


def visible_counts(db: Session, items: list[tuple[int, DocRepoAccess]]) -> dict[int, int]:
    """For each (doc-repo id, the caller's access), how many of its documents the caller may see."""
    if not items:
        return {}
    by_status: dict[int, dict[str, int]] = {}
    for doc_repo_id, status, n in db.execute(
        select(Document.doc_repo_id, Document.status, func.count())
        .where(Document.doc_repo_id.in_([i for i, _ in items]))
        .group_by(Document.doc_repo_id, Document.status)
    ):
        by_status.setdefault(doc_repo_id, {})[status] = n
    return {
        i: sum(n for s, n in by_status.get(i, {}).items() if s in visible_statuses(access))
        for i, access in items
    }


@dataclass(frozen=True)
class DocumentActions:
    """What the caller can do with one document, for the UI (the server checks again)."""

    edit: bool  # metadata
    submit: bool
    review: bool  # approve or reject
    delete: bool


def actions_for(doc: Document, access: DocRepoAccess, caller_id: int | None) -> DocumentActions:
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


def _query(doc_repo_id: int):
    return (
        select(Document)
        .where(Document.doc_repo_id == doc_repo_id)
        .options(selectinload(Document.values), selectinload(Document.maker), selectinload(Document.checker),
                 selectinload(Document.doc_repo))
    )


def list_documents(db: Session, principal: Principal, doc_repo_id: int) -> tuple[list[Document], DocRepoAccess]:
    """The doc-repo's documents the caller may see, by folder then name. The UI builds the folder
    tree from each document's folder."""
    doc_repo = get_doc_repo(db, doc_repo_id)
    access = access_to(db, principal, doc_repo)
    statuses = visible_statuses(access)
    docs = db.scalars(
        _query(doc_repo_id).where(Document.status.in_(statuses)).order_by(Document.folder, Document.filename)
    ).all()
    return list(docs), access


def get_document(db: Session, principal: Principal, doc_repo_id: int, document_id: int) -> tuple[Document, DocRepoAccess]:
    """One document, if the caller may see it (NotFound otherwise, so hidden drafts stay hidden)."""
    doc_repo = get_doc_repo(db, doc_repo_id)
    access = access_to(db, principal, doc_repo)
    doc = db.scalar(_query(doc_repo_id).where(Document.id == document_id))
    if doc is None or doc.status not in visible_statuses(access):
        raise NotFound(f"No document {document_id} in this repository.")
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


def upload(db: Session, principal: Principal, doc_repo_id: int, files: list[IncomingFile]) -> list[Document]:
    """Add the files to the doc-repo as drafts, with the doc-repo's department metadata copied onto each.
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

    doc_repo = get_doc_repo(db, doc_repo_id)
    maker = _caller(db, principal)
    batch = str(uuid.uuid4())
    taken = {(d.folder, d.filename) for d in db.scalars(select(Document).where(Document.doc_repo_id == doc_repo_id))}
    created: list[tuple[Document, bytes]] = []
    for folder, name, f in planned:
        name = _unique_name(taken, folder, name)
        taken.add((folder, name))
        doc = Document(
            doc_repo_id=doc_repo_id, folder=folder, filename=name, size_bytes=len(f.data),
            content_type=f.content_type or mimetypes.guess_type(name)[0], storage_path="", upload_batch=batch,
            status=S.DRAFT.value, maker_id=maker.id if maker else None,
            department_metadata=dict(doc_repo.department_metadata), department_overrides=[], ai_metadata={},
            values=[DocumentValue(source="field", key=p["key"], value=p["value"])
                    for p in doc_repo.repository_metadata if p["value"]],
        )
        db.add(doc)
        created.append((doc, f.data))
    db.flush()  # document ids for the storage paths

    written: list[Path] = []
    try:
        for doc, data in created:
            relative = PurePosixPath("doc-repos", str(doc_repo_id), str(doc.id), doc.filename)
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
    department_metadata: dict[str, str | None]  # any of DEPARTMENT_METADATA_KEYS; "" or None clears
    repository_metadata: dict[str, str]  # repository metadata key -> value
    extra: dict[str, str]  # maker's own key -> value


def update_metadata(db: Session, principal: Principal, doc_repo_id: int, document_id: int, m: MetadataIn) -> Document:
    """Replace the document's metadata. Only drafts and rejected documents can be edited."""
    doc, _ = get_document(db, principal, doc_repo_id, document_id)
    if doc.status not in EDITABLE:
        raise Conflict(f"{doc.filename} is {_status_label(doc.status)}; only drafts and rejected documents can be edited.")
    doc_repo = get_doc_repo(db, doc_repo_id)
    defined = {p["key"] for p in doc_repo.repository_metadata}

    # department metadata: set values, then record which differ from the doc-repo
    given = clean_department_metadata(m.department_metadata)
    doc.department_metadata = {k: given[k] if k in m.department_metadata else doc.department_metadata.get(k, "")
                               for k in DEPARTMENT_METADATA_KEYS}
    defaults = doc_repo.department_metadata
    doc.department_overrides = [k for k in DEPARTMENT_METADATA_KEYS
                                if doc.department_metadata[k] != defaults.get(k, "")]

    # repository metadata: only the doc-repo's keys, plain text
    values: list[DocumentValue] = []
    for key, raw in m.repository_metadata.items():
        if key not in defined:
            raise InvalidRequest(f"{key!r} isn't one of this repository's metadata keys.")
        value = (raw or "").strip()
        if value:
            values.append(DocumentValue(source="field", key=key, value=value))
    # extra: the maker's own keys, which can't shadow a repository metadata key
    for raw_key, raw in m.extra.items():
        key = " ".join(raw_key.split())[:64]  # kept as typed, e.g. "Reviewed by legal"
        if not key:
            raise InvalidRequest("Give each additional field a name.")
        if key.casefold() in {k.casefold() for k in defined}:
            raise InvalidRequest(f"{key!r} is repository metadata; fill it in there.")
        if (raw or "").strip():
            values.append(DocumentValue(source="extra", key=key, value=raw.strip()))
    keys = [(v.source, v.key) for v in values]
    if len(keys) != len(set(keys)):
        raise InvalidRequest("A field is given twice.")
    doc.values = values
    doc.updated_at = utcnow()
    db.commit()
    return get_document(db, principal, doc_repo_id, document_id)[0]


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


def submit(db: Session, principal: Principal, doc_repo_id: int, ids: list[int]) -> BulkResult:
    """Send drafts (or rejected documents) to the checkers. Each document that can't go (wrong
    status) is skipped with the reason; the others go."""
    docs = _load_many(db, principal, doc_repo_id, ids)
    done, skipped = [], []
    now = utcnow()
    for doc in docs:
        if doc.status not in EDITABLE:
            skipped.append(Skipped(doc.id, doc.filename, f"It's {_status_label(doc.status)}."))
            continue
        doc.status, doc.submitted_at = S.PENDING.value, now
        doc.checker, doc.decided_at, doc.rejection_reason = None, None, None
        done.append(doc)
    db.commit()
    return BulkResult(done, skipped)


def review(db: Session, principal: Principal, doc_repo_id: int, ids: list[int], approve: bool,
           reason: str | None) -> BulkResult:
    """Approve, or reject with a reason, pending documents. A checker never decides on a document
    they uploaded themselves."""
    reason = (reason or "").strip()
    if not approve and not reason:
        raise InvalidRequest("Give a reason for rejecting.")
    checker = _caller(db, principal)
    docs = _load_many(db, principal, doc_repo_id, ids)
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


def delete_documents(db: Session, principal: Principal, doc_repo_id: int, ids: list[int]) -> BulkResult:
    """Delete drafts and rejected documents (and their files). Others are skipped."""
    docs = _load_many(db, principal, doc_repo_id, ids)
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


def delete_doc_repo_files(doc_repo_id: int) -> None:
    """Remove the stored files of a deleted doc-repo."""
    shutil.rmtree(get_settings().upload_dir / "doc-repos" / str(doc_repo_id), ignore_errors=True)


def _load_many(db: Session, principal: Principal, doc_repo_id: int, ids: list[int]) -> list[Document]:
    """The documents, all visible to the caller in this doc-repo; NotFound if any isn't."""
    if not ids:
        raise InvalidRequest("Choose at least one document.")
    if len(ids) > 500:
        raise InvalidRequest("Choose at most 500 documents at a time.")
    doc_repo = get_doc_repo(db, doc_repo_id)
    statuses = visible_statuses(access_to(db, principal, doc_repo))
    docs = {d.id: d for d in db.scalars(_query(doc_repo_id).where(Document.id.in_(set(ids))))}
    missing = [i for i in dict.fromkeys(ids) if i not in docs or docs[i].status not in statuses]
    if missing:
        raise NotFound(f"No document {', '.join(map(str, missing))} in this repository.")
    return [docs[i] for i in dict.fromkeys(ids)]


# --------------------------------------------------------------------------- repository metadata


def repository_overrides(doc: Document, doc_repo_metadata: list[dict[str, str]]) -> list[str]:
    """Repository metadata keys whose value on the document differs from the doc-repo's."""
    mine = {v.key: v.value for v in doc.values if v.source == "field"}
    return [p["key"] for p in doc_repo_metadata if mine.get(p["key"], "") != p["value"]]


def replace_repository_metadata(db: Session, doc_repo_id: int, pairs: list[tuple[str, str]]) -> list[dict[str, str]]:
    """Make the doc-repo's repository metadata exactly `pairs` (key, value), in this order. Existing
    documents keep their values; a removed key's values stay on them as the maker's own fields."""
    doc_repo = get_doc_repo(db, doc_repo_id)
    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw_key, raw_value in pairs:
        key = " ".join(raw_key.split())[:64]  # kept as typed, e.g. "Product code"
        if not key:
            raise InvalidRequest("Give every repository metadata entry a key.")
        if key.casefold() in seen:
            raise InvalidRequest(f"{key!r} is given twice.")
        if key.casefold() in DEPARTMENT_METADATA_NAMES:
            raise InvalidRequest(f"{key!r} is already department metadata.")
        seen.add(key.casefold())
        cleaned.append({"key": key, "value": (raw_value or "").strip()})

    removed = {p["key"] for p in doc_repo.repository_metadata} - {p["key"] for p in cleaned}
    if removed:  # keep what makers typed, as their own fields
        doc_ids = select(Document.id).where(Document.doc_repo_id == doc_repo_id)
        db.execute(
            update(DocumentValue)
            .where(DocumentValue.document_id.in_(doc_ids), DocumentValue.source == "field", DocumentValue.key.in_(removed))
            .values(source="extra")
        )
    doc_repo.repository_metadata = cleaned
    db.commit()
    return cleaned


# Names a repository metadata key can't take (department metadata has them).
DEPARTMENT_METADATA_NAMES = {k.casefold() for k in DEPARTMENT_METADATA_KEYS} | {
    k.replace("_", " ").casefold() for k in DEPARTMENT_METADATA_KEYS}


# --------------------------------------------------------------------------- helpers


def _status_label(status: str) -> str:
    return {"draft": "a draft", "pending_approval": "pending approval", "approved": "approved",
            "rejected": "rejected"}.get(status, status)

