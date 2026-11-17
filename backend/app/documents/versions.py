"""Document versions: what each version is, what each person sees, and moving between versions.

A document is a place in a repository (folder + filename). Its row is the working copy of the
latest version; `document_version` keeps one row per version. Uploading to the same place again:

    latest is a draft or changes requested   the file is replaced in that version (resubmitting
                                              continues the same request)
    latest is approved or rejected           a new version, a draft, starting from the latest's
                                              metadata (repository values follow the repository again)
    latest is pending approval               refused

Who sees which version: the latest, if its status is one the person may see; otherwise the latest
approved version, if they may see approved documents (viewers keep seeing v1 while v2 is a draft).
Makers, checkers and auditors see every version (`versions`).

    discard   the maker throws away the latest unapproved version; the document falls back to the
              version before it (file, status, request and metadata as they were)
    restore   an earlier version's file and metadata become the latest again: in place over a draft
              or changes-requested version, else as a new version. It needs approval like any other.

Callers commit.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.access.catalog import P
from app.access.models import AppUser, HierarchyNode
from app.core.errors import Conflict, NotFound
from app.db.base import utcnow
from app.documents import metadata
from app.documents.models import Document, DocumentStatus, DocumentVersion, MetadataField, MetadataSource, MetadataValue
from app.documents.service import RepoAccess

S = DocumentStatus
IN_PLACE = {S.DRAFT.value, S.CHANGES_REQUESTED.value}  # a new file replaces the latest version's
NEW_VERSION = {S.APPROVED.value, S.REJECTED.value}  # a new file is a new version
DISCARDABLE = {S.DRAFT.value, S.CHANGES_REQUESTED.value, S.REJECTED.value}


# --------------------------------------------------------------------------- the latest version


def head(db: Session, doc: Document) -> DocumentVersion:
    v = db.scalar(select(DocumentVersion).where(DocumentVersion.document_id == doc.id,
                                                DocumentVersion.number == doc.version))
    if v is None:  # every document has its versions (migration 0014); this is a safety net
        v = DocumentVersion(document_id=doc.id, number=doc.version, filename=doc.filename,
                            uploaded_by_id=doc.maker_id, created_at=doc.created_at)
        db.add(v)
        sync_head(db, doc, v)
    return v


def sync_head(db: Session, doc: Document, v: DocumentVersion | None = None) -> DocumentVersion:
    """Copy the document's working state onto its latest version's row."""
    v = v or head(db, doc)
    v.filename, v.content_type, v.size_bytes = doc.filename, doc.content_type, doc.size_bytes
    v.storage_path, v.content_hash, v.status = doc.storage_path, doc.content_hash, doc.status
    v.approval_request_id, v.submitted_at = doc.latest_approval_request_id, doc.submitted_at
    return v


def next_number(db: Session, doc: Document) -> int:
    """After the highest ever used, discarded ones included, so numbers are never reused."""
    return (db.scalar(select(func.max(DocumentVersion.number)).where(DocumentVersion.document_id == doc.id)) or 0) + 1


def new_version(db: Session, doc: Document, uploader: AppUser, restored_from: int | None = None) -> DocumentVersion:
    """Start a new latest version (a draft) on top of an approved or rejected one. The caller sets
    the file on `doc` and then calls sync_head. Metadata carries on from the version before: the
    maker's own values stay, values inherited from the repository follow it again."""
    current = head(db, doc)
    current.metadata_snapshot = snapshot(db, doc)
    current.superseded_at = utcnow()
    doc.version = next_number(db, doc)
    doc.status, doc.latest_approval_request_id, doc.submitted_at = S.DRAFT.value, None, None
    doc.maker_id = uploader.id
    db.execute(update(MetadataValue).where(MetadataValue.document_id == doc.id).values(frozen=False))
    v = DocumentVersion(document_id=doc.id, number=doc.version, filename=doc.filename, uploaded_by_id=uploader.id,
                        restored_from=restored_from)
    db.add(v)
    return v


# --------------------------------------------------------------------------- metadata snapshots


def snapshot(db: Session, doc: Document) -> list[dict]:
    """The document's metadata now, enough to show it later and to put it back."""
    rows = db.execute(select(MetadataValue, MetadataField).join(MetadataField)
                      .where(MetadataValue.document_id == doc.id)).all()
    node = doc.doc_repo.node
    shown = {e.field_id: e for e in metadata.entries(db, [doc], node)[doc.id]}
    out = []
    for row, field in rows:
        e = shown.get(field.id)
        out.append({
            "field_id": str(field.id), "repository_field": field.hierarchy_node_id is not None,
            "key": field.key, "label": field.label, "position": field.position,
            "value": row.value, "source": row.source,
            "inherited_from_node_id": str(row.inherited_from_node_id) if row.inherited_from_node_id else None,
            "state": e.state if e else "own", "from_node": e.from_node if e else None,
            "overridable": field.overridable,
        })
    return sorted(out, key=lambda x: (not x["repository_field"], x["position"]))


def entries_from_snapshot(items: list[dict] | None) -> list[metadata.Entry]:
    return [metadata.Entry(field_id=uuid.UUID(i["field_id"]), label=i["label"], value=i["value"], state=i["state"],
                           inherited_value=None, from_node=i["from_node"], overridable=i["overridable"])
            for i in items or []]


def put_back(db: Session, doc: Document, items: list[dict], *, frozen: bool, actor: AppUser | None) -> None:
    """Make the document's metadata what the snapshot says. A repository field that's gone since
    comes back as the document's own field."""
    own_fields = db.scalars(select(MetadataField.id).where(MetadataField.document_id == doc.id)).all()
    db.execute(delete(MetadataValue).where(MetadataValue.document_id == doc.id))
    if own_fields:
        db.execute(delete(MetadataField).where(MetadataField.id.in_(own_fields)))
    db.flush()
    live = set(db.scalars(select(MetadataField.id).where(MetadataField.hierarchy_node_id.is_not(None))))
    taken: set[str] = set()
    for i in items:
        field_id = uuid.UUID(i["field_id"])
        source = i["source"]
        if not (i["repository_field"] and field_id in live):
            if i["key"] in taken or (i["repository_field"] and i["value"] is None):
                continue  # a removed repository field that no longer exists: nothing to keep
            field = MetadataField(document_id=doc.id, key=i["key"], label=i["label"], inheritable=False,
                                  position=i["position"] + (1000 if i["repository_field"] else 0),
                                  created_by_id=actor.id if actor else None)
            db.add(field)
            db.flush()
            field_id, source = field.id, MetadataSource.MAKER.value
        taken.add(i["key"])
        db.add(MetadataValue(
            metadata_field_id=field_id, document_id=doc.id, value=i["value"], source=source, frozen=frozen,
            inherited_from_node_id=uuid.UUID(i["inherited_from_node_id"]) if i["inherited_from_node_id"] and source == MetadataSource.INHERITED.value else None,
            set_by_id=actor.id if actor else None))
    db.flush()


# --------------------------------------------------------------------------- what each person sees


@dataclass(frozen=True)
class View:
    """A document as one person sees it: the latest version, or the latest approved one."""

    doc: Document
    version: int
    latest: bool  # the latest version (the working copy); else an earlier, approved one
    filename: str
    content_type: str | None
    size_bytes: int
    storage_path: str
    status: str
    maker_id: uuid.UUID | None
    approval_request_id: uuid.UUID | None
    submitted_at: datetime | None
    updated_at: datetime
    snapshot: list[dict] | None  # an earlier version's metadata


def sees_versions(a: RepoAccess) -> bool:
    """Makers, checkers and auditors see every version; viewers only the latest approved one."""
    return a.has(P.DOC_VIEW_ALL) or a.has(P.DOC_VIEW_SUBMITTED)


def visible_filter(a: RepoAccess):
    statuses = a.visible_statuses()
    cond = Document.status.in_(statuses)
    if S.APPROVED.value in statuses:
        cond = cond | Document.approved_version.is_not(None)
    return cond


def _head_view(d: Document) -> View:
    return View(d, d.version, True, d.filename, d.content_type, d.size_bytes, d.storage_path, d.status,
                d.maker_id, d.latest_approval_request_id, d.submitted_at, d.updated_at, None)


def _version_view(d: Document, v: DocumentVersion) -> View:
    return View(d, v.number, False, v.filename, v.content_type, v.size_bytes, v.storage_path, v.status,
                v.uploaded_by_id, v.approval_request_id, v.submitted_at, v.updated_at, v.metadata_snapshot or [])


def _approved_rows(db: Session, docs: list[Document]) -> dict[tuple[uuid.UUID, int], DocumentVersion]:
    """The approved version's row of each document whose approved version isn't its latest."""
    older = [d for d in docs if d.approved_version and d.approved_version != d.version]
    if not older:
        return {}
    return {(v.document_id, v.number): v for v in db.scalars(select(DocumentVersion).where(
        DocumentVersion.document_id.in_([d.id for d in older])))}


def views(db: Session, docs: list[Document], a: RepoAccess) -> list[View]:
    """What the person sees of each document (documents they can't see are left out)."""
    statuses = a.visible_statuses()
    approved = _approved_rows(db, [d for d in docs if d.status not in statuses]) if S.APPROVED.value in statuses else {}
    out = []
    for d in docs:
        if d.status in statuses:
            out.append(_head_view(d))
        elif (v := approved.get((d.id, d.approved_version))) is not None:
            out.append(_version_view(d, v))
    return out


# The Documents tab's two lists. Published: every document's latest approved version, for anyone
# who may see approved documents. In progress: the latest version of documents that aren't approved
# (drafts, pending, changes requested, rejected), for those who may see them.

def published_filter():
    return Document.approved_version.is_not(None)


def published_views(db: Session, docs: list[Document], a: RepoAccess) -> list[View]:
    if S.APPROVED.value not in a.visible_statuses():
        return []
    approved = _approved_rows(db, docs)
    out = []
    for d in docs:
        if not d.approved_version:
            continue
        if d.approved_version == d.version:
            out.append(_head_view(d))
        elif (v := approved.get((d.id, d.approved_version))) is not None:
            out.append(_version_view(d, v))
    return out


def in_progress_filter(a: RepoAccess):
    return Document.status.in_(a.visible_statuses() - {S.APPROVED.value})


def in_progress_views(docs: list[Document], a: RepoAccess) -> list[View]:
    statuses = a.visible_statuses() - {S.APPROVED.value}
    return [_head_view(d) for d in docs if d.status in statuses]


def list_versions(db: Session, doc: Document) -> list[DocumentVersion]:
    return list(db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == doc.id)
                           .order_by(DocumentVersion.number.desc())))


def get_version(db: Session, doc: Document, number: int) -> DocumentVersion:
    v = db.scalar(select(DocumentVersion).where(DocumentVersion.document_id == doc.id, DocumentVersion.number == number))
    if v is None:
        raise NotFound(f"{doc.filename} has no version {number}.")
    return v


# --------------------------------------------------------------------------- discard, restore


def can_discard(db: Session, doc: Document) -> bool:
    return doc.status in DISCARDABLE and _previous(db, doc) is not None


def _previous(db: Session, doc: Document) -> DocumentVersion | None:
    return db.scalar(select(DocumentVersion).where(
        DocumentVersion.document_id == doc.id, DocumentVersion.number < doc.version,
        DocumentVersion.discarded_at.is_(None)).order_by(DocumentVersion.number.desc()).limit(1))


def discard(db: Session, doc: Document, actor: AppUser) -> tuple[int, int]:
    """Throw the latest version away and fall back to the one before. The caller withdraws its
    approval request first if it has one. Returns (discarded, now latest)."""
    if doc.status not in DISCARDABLE:
        raise Conflict(f"Version {doc.version} of {doc.filename} is {doc.status.replace('_', ' ')}; it can't be discarded.")
    prev = _previous(db, doc)
    if prev is None:
        raise Conflict(f"{doc.filename} has no earlier version to go back to; delete the document instead.")
    gone = sync_head(db, doc)
    gone.discarded_at, gone.discarded_by_id = utcnow(), actor.id
    gone.metadata_snapshot = snapshot(db, doc)
    discarded = doc.version
    doc.version = prev.number
    doc.filename, doc.content_type, doc.size_bytes = prev.filename, prev.content_type, prev.size_bytes
    doc.storage_path, doc.content_hash, doc.status = prev.storage_path, prev.content_hash, prev.status
    doc.latest_approval_request_id, doc.submitted_at = prev.approval_request_id, prev.submitted_at
    doc.maker_id = prev.uploaded_by_id
    put_back(db, doc, prev.metadata_snapshot or [], frozen=prev.status == S.APPROVED.value, actor=actor)
    prev.superseded_at, prev.metadata_snapshot = None, None
    return discarded, prev.number


def restore(db: Session, doc: Document, source: DocumentVersion, actor: AppUser) -> DocumentVersion:
    """Make an earlier version's file and metadata the latest again, as a draft (or in place over a
    draft or changes-requested version). Returns the latest version."""
    if source.number == doc.version:
        raise Conflict(f"Version {source.number} is already the latest.")
    if source.discarded_at is not None:
        raise Conflict(f"Version {source.number} was discarded.")
    if doc.status == S.PENDING.value:
        raise Conflict(f"{doc.filename} is waiting for approval; restore a version after it's decided.")
    if doc.status in NEW_VERSION:
        v = new_version(db, doc, actor, restored_from=source.number)
    else:
        v = head(db, doc)
        v.restored_from, v.uploaded_by_id, v.created_at = source.number, actor.id, utcnow()
    doc.filename, doc.content_type, doc.size_bytes = source.filename, source.content_type, source.size_bytes
    doc.storage_path, doc.content_hash = source.storage_path, source.content_hash
    put_back(db, doc, source.metadata_snapshot or [], frozen=False, actor=actor)
    doc.updated_at = utcnow()
    return sync_head(db, doc, v)


def node_of(doc: Document) -> HierarchyNode:
    return doc.doc_repo.node
