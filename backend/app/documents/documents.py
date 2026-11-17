"""Documents in a repository: upload, metadata, submit for approval, (soft) delete.

Status flow:
    draft ──submit──> pending_approval ──(Approvals page)──> approved          (metadata locked)
      ^                     │                       └──────> rejected          (resubmitting: a new request)
      │                     └──────────────────────────────> changes_requested (resubmitting: next round)
      └── makers edit drafts, rejected and changes-requested documents

Who sees which documents (permissions at the repository):
    docs.document.view_all        every status (MAKER, AUDITOR)
    docs.document.view_submitted  pending, changes requested, approved, rejected (CHECKER)
    docs.document.view_approved   approved (VIEWER, OWNER, ADMIN)
Hidden documents answer 404.
"""

import hashlib
import mimetypes
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.access.catalog import P, SystemCode
from app.access.models import AppUser
from app.approvals import service as approvals
from app.audit import service as audit
from app.approvals.hooks import ApprovalKind
from app.documents import workflow_steps
from app.approvals.models import ApprovalRequest, Decision
from app.core.config import get_settings
from app.core.errors import Conflict, InvalidRequest, NotFound
from app.db.base import utcnow
from app.documents import metadata
from app.documents import versions
from app.documents.models import DocRepo, Document, DocumentStatus, DocumentVersion
from app.documents.service import RESOURCE_TYPE, RepoAccess, access_to, get_repo

S = DocumentStatus
EDITABLE = {S.DRAFT.value, S.REJECTED.value, S.CHANGES_REQUESTED.value}
TYPE_CODE = "DOCUMENT_UPLOAD"
SUBJECT_TYPE = "DOCUMENT"


# --------------------------------------------------------------------------- reading


@dataclass(frozen=True)
class DocumentActions:
    edit: bool
    submit: bool
    delete: bool
    discard: bool  # throw away the latest version, back to the one before
    versions: bool  # may see every version (makers, checkers, auditors)


def actions_for(db: Session, view: versions.View, a: RepoAccess) -> DocumentActions:
    editable = view.latest and a.has(P.DOC_UPLOAD) and view.status in EDITABLE
    return DocumentActions(edit=editable, submit=editable, delete=editable,
                           discard=editable and view.doc.version > 1 and versions.can_discard(db, view.doc),
                           versions=versions.sees_versions(a))


def _query(repo_id: uuid.UUID):
    return (select(Document).where(Document.doc_repo_id == repo_id, Document.deleted_at.is_(None))
            .options(selectinload(Document.maker)))


VIEWS = ("all", "published", "in_progress")


def list_documents(db: Session, user: AppUser, repo_id: uuid.UUID,
                   view: str = "all") -> tuple[DocRepo, list[versions.View], RepoAccess]:
    """The documents the person may see, each as the version they see. `view`: "all" (each
    document's visible version, see versions.views), "published" (latest approved versions) or
    "in_progress" (latest versions that aren't approved)."""
    if view not in VIEWS:
        raise InvalidRequest("view is all, published or in_progress.")
    repo = get_repo(db, repo_id)
    a = access_to(db, user, repo)
    cond = {"all": versions.visible_filter(a), "published": versions.published_filter(),
            "in_progress": versions.in_progress_filter(a)}[view]
    docs = list(db.scalars(_query(repo_id).where(cond).order_by(Document.folder, Document.filename)))
    seen = (versions.published_views(db, docs, a) if view == "published"
            else versions.in_progress_views(docs, a) if view == "in_progress" else versions.views(db, docs, a))
    return repo, seen, a


def get_document(db: Session, user: AppUser, repo_id: uuid.UUID, document_id: uuid.UUID) -> tuple[DocRepo, Document, RepoAccess]:
    """The document, if the person may see some version of it (else 404)."""
    repo, view, a = get_view(db, user, repo_id, document_id)
    return repo, view.doc, a


def get_view(db: Session, user: AppUser, repo_id: uuid.UUID, document_id: uuid.UUID,
             published: bool = False) -> tuple[DocRepo, versions.View, RepoAccess]:
    """The document as the person sees it; `published`: its latest approved version (404 if none)."""
    repo = get_repo(db, repo_id)
    a = access_to(db, user, repo)
    doc = db.scalar(_query(repo_id).where(Document.id == document_id))
    seen = [] if doc is None else versions.published_views(db, [doc], a) if published else versions.views(db, [doc], a)
    if not seen:
        raise NotFound("No such document in this repository." if not published or doc is None
                       else f"{doc.filename} has no approved version yet.")
    return repo, seen[0], a


def file_path(doc: Document | versions.View | DocumentVersion) -> Path:
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
    """("Policies/2026", "report.pdf") from a browser-supplied path: no "..", no absolute paths."""
    parts = [p.strip() for p in raw.replace("\\", "/").split("/")]
    parts = [p for p in parts if p and p not in (".", "..")]
    if not parts:
        raise InvalidRequest("A file has no name.")
    name = re.sub(r"[\x00-\x1f]", "", parts[-1])[:200]
    folder = "/".join(re.sub(r"[\x00-\x1f]", "", p)[:100] for p in parts[:-1])[:500]
    if not name:
        raise InvalidRequest("A file has no name.")
    return folder, name


@dataclass(frozen=True)
class Uploaded:
    doc: Document
    outcome: str  # "new" (a new document), "replaced" (the latest draft's file) or "version" (a new version)


def upload(db: Session, user: AppUser, repo_id: uuid.UUID, files: list[IncomingFile]) -> list[Uploaded]:
    """Add the files. A new name in a folder is a new document (a draft with the repository's
    metadata); a name that's there already gets the file as its latest version (see versions.py).
    All or nothing: refused if any of them is waiting for approval."""
    s = get_settings()
    if not files:
        raise InvalidRequest("Choose at least one file.")
    if len(files) > s.max_files_per_upload:
        raise InvalidRequest(f"Upload at most {s.max_files_per_upload} files at a time.")
    allowed = {e.lower() for e in s.allowed_upload_extensions}
    limit = s.max_upload_mb * 1024 * 1024
    planned = []
    seen: set[tuple[str, str]] = set()
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
        if (folder, name) in seen:
            raise InvalidRequest(f"{_path(folder, name)} is given twice.")
        seen.add((folder, name))
        planned.append((folder, name, f))

    repo = get_repo(db, repo_id)
    existing = {(d.folder, d.filename): d for d in db.scalars(_query(repo_id))}
    waiting = [_path(fo, n) for fo, n, _ in planned
               if (d := existing.get((fo, n))) is not None and d.status == S.PENDING.value]
    if waiting:
        raise Conflict(f"Nothing was uploaded: {', '.join(waiting[:10])}{' and more' if len(waiting) > 10 else ''} "
                       f"{'is' if len(waiting) == 1 else 'are'} waiting for approval. Upload a new version after "
                       "the decision.")

    batch = str(uuid.uuid4())
    done: list[tuple[Uploaded, bytes]] = []
    for folder, name, f in planned:
        doc = existing.get((folder, name))
        if doc is None:
            doc = Document(doc_repo_id=repo_id, folder=folder, filename=name, maker_id=user.id)
            db.add(doc)
            db.flush()
            metadata.copy_inherited(db, doc, repo.node)
            v = DocumentVersion(document_id=doc.id, number=1, filename=name, uploaded_by_id=user.id)
            db.add(v)
            outcome = "new"
        elif doc.status in versions.NEW_VERSION:
            v = versions.new_version(db, doc, user)
            outcome = "version"
        else:  # a draft, or back for changes: the new file replaces this version's
            v = versions.head(db, doc)
            v.uploaded_by_id, v.restored_from, v.created_at = user.id, None, utcnow()
            doc.maker_id = user.id
            outcome = "replaced"
        doc.size_bytes, doc.content_hash = len(f.data), hashlib.sha256(f.data).hexdigest()
        doc.content_type = f.content_type or mimetypes.guess_type(name)[0]
        doc.upload_batch, doc.updated_at = batch, utcnow()
        done.append((Uploaded(doc, outcome), f.data))
    db.flush()
    if any(u.outcome != "new" for u, _ in done):
        metadata.refresh_documents_under(db, repo.node)  # new versions' repository values follow it again

    written: list[Path] = []
    try:
        for u, data in done:
            doc = u.doc
            # every upload has its own folder: earlier versions' files are kept
            relative = PurePosixPath("doc-repos", str(repo_id), str(doc.id), batch, doc.filename)
            target = s.upload_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            written.append(target)
            doc.storage_path = str(relative)
            versions.sync_head(db, doc)
        audit.record(db, "DOCUMENTS_UPLOADED", actor=user, target=("doc_repo", repo_id), node_id=repo.node.id,
                     details={"files": [{"name": _path(u.doc.folder, u.doc.filename), "size": u.doc.size_bytes,
                                         "version": u.doc.version, "outcome": u.outcome} for u, _ in done],
                              "batch": batch})
        db.commit()
    except Exception:
        db.rollback()
        for path in written:
            shutil.rmtree(path.parent, ignore_errors=True)
        raise
    return [u for u, _ in done]


def _path(folder: str, name: str) -> str:
    return "/".join(x for x in (folder, name) if x)


# --------------------------------------------------------------------------- metadata


def update_metadata(db: Session, user: AppUser, repo_id: uuid.UUID, document_id: uuid.UUID,
                    inherited: dict[uuid.UUID, tuple[str, str | None]], own: list[tuple[str, str]]) -> Document:
    repo, doc, _ = get_document(db, user, repo_id, document_id)
    if doc.status not in EDITABLE:
        raise Conflict(f"{doc.filename} is {_label(doc.status)}; its metadata can't be changed.")
    def values() -> dict[str, str | None]:
        return {e.label: e.value for e in metadata.entries(db, [doc], repo.node)[doc.id]}
    before = values()
    metadata.set_document_metadata(db, user, doc, repo.node, inherited, own)
    db.flush()
    after = values()
    doc.updated_at = utcnow()
    if before != after:
        audit.record(db, "DOCUMENT_METADATA_SET", actor=user, target=("document", doc.id), node_id=repo.node.id,
                     details={"filename": doc.filename, **audit.diff(before, after)})
    db.commit()
    return doc


# --------------------------------------------------------------------------- submit, delete


@dataclass(frozen=True)
class Skipped:
    document_id: uuid.UUID
    filename: str
    reason: str


@dataclass(frozen=True)
class BulkResult:
    done: list[Document]
    skipped: list[Skipped]


def _load_many(db: Session, user: AppUser, repo_id: uuid.UUID, ids: list[uuid.UUID]) -> tuple[DocRepo, list[Document]]:
    if not ids:
        raise InvalidRequest("Choose at least one document.")
    repo = get_repo(db, repo_id)
    statuses = access_to(db, user, repo).visible_statuses()
    docs = {d.id: d for d in db.scalars(_query(repo_id).where(Document.id.in_(set(ids))))}
    missing = [i for i in dict.fromkeys(ids) if i not in docs or docs[i].status not in statuses]
    if missing:
        raise NotFound(f"No document {', '.join(map(str, missing))} in this repository.")
    return repo, [docs[i] for i in dict.fromkeys(ids)]


def _size(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def summary_and_snapshot(db: Session, repo: DocRepo, doc: Document, maker: AppUser | None) -> tuple[dict, dict]:
    """What the checker is shown (payload), and exactly what's being approved (snapshot)."""
    items = metadata.entries(db, [doc], repo.node)[doc.id]
    shown = [{"label": e.label, "value": e.value or "",
              "note": {"overridden": "changed by the maker", "removed": "removed by the maker"}.get(e.state, "")}
             for e in items if e.state != "own"]
    own = [{"label": e.label, "value": e.value or "", "note": ""} for e in items if e.state == "own"]
    summary = {
        "subtitle": repo.node.name,
        "facts": [{"label": "Repository", "value": repo.node.name},
                  {"label": "Version", "value": _version_text(db, doc)},
                  {"label": "Folder", "value": doc.folder or "Top level"},
                  {"label": "Size", "value": _size(doc.size_bytes)},
                  {"label": "Uploaded by", "value": maker.display_name if maker else ""}],
        "sections": [s for s in (
            {"title": "Repository metadata", "items": shown},
            {"title": "Additional metadata", "items": own} if own else None,
        ) if s],
        "download": {"href": f"/doc-repos/{repo.id}/documents/{doc.id}/download", "filename": doc.filename},
        "link": {"label": "Open the repository", "href": f"#doc-repo/{repo.id}"},
    }
    snapshot = {"filename": doc.filename, "folder": doc.folder, "size_bytes": doc.size_bytes, "version": doc.version,
                "content_hash": doc.content_hash,
                "metadata": [{"label": e.label, "value": e.value, "state": e.state} for e in items]}
    return summary, snapshot


def _version_text(db: Session, doc: Document) -> str:
    v = versions.head(db, doc)
    parts = [str(doc.version)]
    if v.restored_from:
        parts.append(f"restored from version {v.restored_from}")
    if doc.approved_version and doc.approved_version != doc.version:
        parts.append(f"version {doc.approved_version} is the approved one")
    return " · ".join(parts)


def _listing(doc: Document) -> dict:
    """What the Approvals list shows about a document, on top of approvals' own fields."""
    return {"document": {"folder": doc.folder, "version": doc.version, "size_bytes": doc.size_bytes,
                         "content_type": doc.content_type,
                         "uploaded_by": {"lan_id": doc.maker.lan_id, "display_name": doc.maker.display_name}
                         if doc.maker else None}}


def _problems_message(problems: list[str], verb: str) -> str:
    n = len(problems)
    shown = "; ".join(problems[:10]) + (f"; and {n - 10} more" if n > 10 else "")
    return f"Nothing was {verb}: {shown}. Refresh and try again."


def submit(db: Session, user: AppUser, repo_id: uuid.UUID, ids: list[uuid.UUID],
           expected: dict[uuid.UUID, str] | None = None) -> BulkResult:
    """Send documents for approval, all or none. `expected`: the status each document had when the
    maker chose it. If any has changed since (another maker submitted or deleted it, a checker decided
    it), or the flow refuses any, nothing is submitted: Conflict, naming each. Commits."""
    if not ids:
        raise InvalidRequest("Choose at least one document.")
    ids = list(dict.fromkeys(ids))
    expected = expected or {}
    repo = get_repo(db, repo_id)
    statuses = access_to(db, user, repo).visible_statuses()
    found = {d.id: d for d in db.scalars(
        select(Document).where(Document.doc_repo_id == repo_id, Document.id.in_(ids))
        .options(selectinload(Document.maker)))}
    missing = [i for i in ids if i not in found or (found[i].deleted_at is None and found[i].status not in statuses)]
    if missing:
        raise NotFound(f"No document {', '.join(map(str, missing))} in this repository.")
    docs = [found[i] for i in ids]

    problems = []
    for doc in docs:
        if doc.deleted_at is not None:
            problems.append(f"{doc.filename} was deleted")
        elif doc.status not in EDITABLE:
            problems.append(f"{doc.filename} is now {_label(doc.status)}")
        elif doc.id in expected and expected[doc.id] != doc.status:
            problems.append(f"{doc.filename} is now {_label(doc.status)}")
    if problems:
        raise Conflict(_problems_message(problems, "submitted"))

    refused: list[tuple[Document, str]] = []
    try:
        for doc in docs:
            # Claim the document: only if its status is still what was read. Another maker's submit or
            # delete, or a decision, in between makes this match nothing, and the whole batch rolls back.
            claimed = db.execute(
                update(Document).where(Document.id == doc.id, Document.status == doc.status,
                                       Document.deleted_at.is_(None))
                .values(status=S.PENDING.value, submitted_at=utcnow()))  # also updates `doc` in the session
            if claimed.rowcount != 1:
                raise Conflict(_problems_message([f"{doc.filename} changed while submitting"], "submitted"))
            summary, snapshot = summary_and_snapshot(db, repo, doc, doc.maker)
            try:
                with db.begin_nested():  # a refused document leaves nothing of its own behind
                    request = approvals.request_approval(
                        db, TYPE_CODE, resource_id=str(repo.id), subject_id=str(doc.id), title=doc.filename,
                        payload=summary, snapshot=snapshot, requester=user, maker=doc.maker, listing=_listing(doc))
            except approvals.Refused as e:
                refused.append((doc, str(e)))
                continue
            doc.latest_approval_request_id = request.id
            versions.sync_head(db, doc)
        if refused:
            raise Conflict(_problems_message([f"{d.filename}: {why}" for d, why in refused], "submitted"))
        db.commit()
    except Exception:
        db.rollback()
        if refused:  # the refusals are kept on record though the batch isn't
            for d, why in refused:
                audit.record(db, "APPROVAL_REFUSED", actor=user, target=("document", d.id), node_id=repo.node.id,
                             details={"filename": d.filename, "reason": why}, source_system="APPROVALS")
            db.commit()
        raise
    for doc in docs:
        db.refresh(doc)
    return BulkResult(docs, [])


def delete_documents(db: Session, user: AppUser, repo_id: uuid.UUID, ids: list[uuid.UUID]) -> BulkResult:
    """Soft-delete drafts, rejected and changes-requested documents (kept, hidden). Commits."""
    _, docs = _load_many(db, user, repo_id, ids)
    done, skipped = [], []
    for doc in docs:
        if doc.status not in EDITABLE:
            skipped.append(Skipped(doc.id, doc.filename, f"It's {_label(doc.status)}."))
            continue
        approvals.cancel_subject(db, SUBJECT_TYPE, str(doc.id), user, "The document was deleted.")
        doc.deleted_at, doc.deleted_by_id = utcnow(), user.id
        done.append(doc)
    if done:
        repo = get_repo(db, repo_id)
        audit.record(db, "DOCUMENTS_DELETED", actor=user, target=("doc_repo", repo_id), node_id=repo.node.id,
                     details={"files": [d.filename for d in done]})
    db.commit()
    return BulkResult(done, skipped)


def discard_version(db: Session, user: AppUser, repo_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    """Throw away the latest (unapproved) version; the document goes back to the version before it.
    Its approval request, if still open (changes requested), is withdrawn. Commits."""
    repo, doc, _ = get_document(db, user, repo_id, document_id)
    if doc.status in versions.DISCARDABLE:
        approvals.cancel_subject(db, SUBJECT_TYPE, str(doc.id), user, f"Version {doc.version} was discarded.")
    gone, now = versions.discard(db, doc, user)
    metadata.refresh_documents_under(db, repo.node)
    doc.updated_at = utcnow()
    audit.record(db, "DOCUMENT_VERSION_DISCARDED", actor=user, target=("document", doc.id), node_id=repo.node.id,
                 details={"filename": doc.filename, "discarded": gone, "now_latest": now})
    db.commit()
    return doc


def restore_version(db: Session, user: AppUser, repo_id: uuid.UUID, document_id: uuid.UUID, number: int) -> Document:
    """An earlier version's file and metadata become the latest again, as a draft to submit. Commits."""
    repo, doc, _ = get_document(db, user, repo_id, document_id)
    source = versions.get_version(db, doc, number)
    v = versions.restore(db, doc, source, user)
    metadata.refresh_documents_under(db, repo.node)
    audit.record(db, "DOCUMENT_VERSION_RESTORED", actor=user, target=("document", doc.id), node_id=repo.node.id,
                 details={"filename": doc.filename, "restored": number, "as_version": v.number})
    db.commit()
    return doc


def history(db: Session, doc: Document) -> list[approvals.RequestHistory]:
    return approvals.history(db, SUBJECT_TYPE, str(doc.id))


def decisions_for(db: Session, items: list[versions.View]) -> dict[uuid.UUID, approvals.DecisionView]:
    """The latest decision on each version shown (by document id)."""
    by_request = approvals.latest_decisions(db, {v.approval_request_id for v in items if v.approval_request_id})
    return {v.doc.id: by_request[v.approval_request_id] for v in items if v.approval_request_id in by_request}


def version_decisions(db: Session, items: list[DocumentVersion]) -> dict[uuid.UUID, approvals.DecisionView]:
    """The latest decision on each version (by version id)."""
    by_request = approvals.latest_decisions(db, {v.approval_request_id for v in items if v.approval_request_id})
    return {v.id: by_request[v.approval_request_id] for v in items if v.approval_request_id in by_request}


# --------------------------------------------------------------------------- the approvals hook


def on_decided(db: Session, request: ApprovalRequest, decision: str, checker: AppUser, comment: str | None) -> None:
    """Approvals decided: move the document on. Approval locks its metadata."""
    doc = db.get(Document, uuid.UUID(request.subject_id))
    if doc is None or doc.deleted_at is not None or doc.status != S.PENDING.value:
        raise Conflict("The document is no longer waiting for approval.")
    doc.status = {Decision.APPROVED.value: S.APPROVED.value, Decision.REJECTED.value: S.REJECTED.value,
                  Decision.CHANGES_REQUESTED.value: S.CHANGES_REQUESTED.value}[decision]
    if doc.status == S.APPROVED.value:
        metadata.freeze(db, doc)
        doc.approved_version = doc.version
    versions.sync_head(db, doc)


KIND = ApprovalKind(system=SystemCode.DOC_HUB, type_code=TYPE_CODE, name="Document upload", label="Document",
                    resource_type=RESOURCE_TYPE, subject_type=SUBJECT_TYPE, on_decided=on_decided,
                    workflow_kind=workflow_steps.KIND)


def _label(status: str) -> str:
    return {"draft": "a draft", "pending_approval": "pending approval", "approved": "approved",
            "rejected": "rejected", "changes_requested": "back for changes"}.get(status, status)
