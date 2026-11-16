"""Metadata: one model for repository fields and a document's own fields.

    set_node_metadata       the repository owner's fields and values (in order); documents not yet
                            approved get the new values at once
    copy_inherited          a new document gets a copy of every inherited value
    set_document_metadata   a maker keeps, overrides or removes each inherited field, and sets
                            their own fields
    freeze                  approval locks the document's values
    entries                 what a document's metadata looks like now, field by field

Callers commit.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.access.models import AppUser, HierarchyNode
from app.core.errors import InvalidRequest
from app.db.base import utcnow
from app.documents.models import Document, DocumentStatus, MetadataField, MetadataSource, MetadataValue

MAX_VALUE = 512
DEFAULT_REPOSITORY_FIELDS: tuple[str, ...] = ()  # fields a new repository starts with (none for now)


def clean_label(label: str) -> str:
    return " ".join((label or "").split())[:64]


def key_of(label: str) -> str:
    return clean_label(label).casefold()


def _clean_value(value: str | None) -> str:
    value = (value or "").strip()
    if len(value) > MAX_VALUE:
        raise InvalidRequest(f"Keep values under {MAX_VALUE} characters.")
    return value


# --------------------------------------------------------------------------- at a node


@dataclass(frozen=True)
class NodeEntry:
    field: MetadataField
    value: str


def node_entries(db: Session, node_id: uuid.UUID) -> list[NodeEntry]:
    fields = db.scalars(select(MetadataField).where(MetadataField.hierarchy_node_id == node_id)
                        .order_by(MetadataField.position)).all()
    values = dict(db.execute(select(MetadataValue.metadata_field_id, MetadataValue.value).where(
        MetadataValue.hierarchy_node_id == node_id)).all())
    return [NodeEntry(f, values.get(f.id) or "") for f in fields]


def set_node_metadata(db: Session, actor: AppUser, node: HierarchyNode, pairs: list[tuple[str, str]]) -> None:
    """Make the node's fields exactly `pairs` (label, value), in this order. A removed field's values
    stay on documents that changed it or are approved, as their own fields."""
    existing = {f.key: f for f in db.scalars(select(MetadataField).where(MetadataField.hierarchy_node_id == node.id))}
    seen: set[str] = set()
    for position, (raw_label, raw_value) in enumerate(pairs):
        label, value = clean_label(raw_label), _clean_value(raw_value)
        if not label:
            raise InvalidRequest("Give every metadata field a name.")
        key = key_of(label)
        if key in seen:
            raise InvalidRequest(f"{label!r} is given twice.")
        seen.add(key)
        field = existing.pop(key, None)
        if field is None:
            field = MetadataField(hierarchy_node_id=node.id, key=key, label=label, created_by_id=actor.id)
            db.add(field)
            db.flush()
        field.label, field.position = label, position
        row = db.scalar(select(MetadataValue).where(MetadataValue.metadata_field_id == field.id,
                                                    MetadataValue.hierarchy_node_id == node.id))
        if row is None:
            db.add(MetadataValue(metadata_field_id=field.id, hierarchy_node_id=node.id, value=value,
                                 source=MetadataSource.ADMIN.value, set_by_id=actor.id))
        elif row.value != value:
            row.value, row.set_by_id, row.set_at = value, actor.id, utcnow()
    for field in existing.values():
        _detach_field(db, field)
    db.flush()
    refresh_documents_under(db, node)


def _detach_field(db: Session, field: MetadataField) -> None:
    """Remove a node's field. Document values that matter (an override, or a frozen copy on an
    approved document) move to a field of that document; the rest go."""
    for row in db.scalars(select(MetadataValue).where(MetadataValue.metadata_field_id == field.id,
                                                      MetadataValue.document_id.is_not(None))).all():
        keep = row.frozen or (row.source == MetadataSource.MAKER.value and row.value is not None)
        if not keep:
            db.delete(row)
            continue
        own = db.scalar(select(MetadataField).where(MetadataField.document_id == row.document_id,
                                                    MetadataField.key == field.key))
        if own is not None:  # the document already has its own field with that name: it wins
            db.delete(row)
            continue
        own = MetadataField(document_id=row.document_id, key=field.key, label=field.label, inheritable=False,
                            position=1000 + field.position)
        db.add(own)
        db.flush()
        row.metadata_field_id = own.id
    db.execute(delete(MetadataValue).where(MetadataValue.metadata_field_id == field.id,
                                           MetadataValue.hierarchy_node_id.is_not(None)))
    db.flush()
    db.delete(field)


# --------------------------------------------------------------------------- inheritance


@dataclass(frozen=True)
class Inherited:
    field: MetadataField
    value: str
    from_node: HierarchyNode


def inherited_for(db: Session, node: HierarchyNode) -> list[Inherited]:
    """The inheritable fields defined at `node` or above it, each with its nearest value
    (a value set lower down wins). Root's fields first, then by position."""
    ancestors = db.scalars(select(HierarchyNode).where(HierarchyNode.path.in_(node.ancestor_paths))).all()
    ancestors = sorted(ancestors, key=lambda n: len(n.path), reverse=True)  # nearest first
    ids = [a.id for a in ancestors]
    fields = db.scalars(select(MetadataField).where(MetadataField.hierarchy_node_id.in_(ids),
                                                    MetadataField.inheritable.is_(True))).all()
    values = {(field_id, node_id): value for field_id, node_id, value in db.execute(
        select(MetadataValue.metadata_field_id, MetadataValue.hierarchy_node_id, MetadataValue.value)
        .where(MetadataValue.hierarchy_node_id.in_(ids)))}
    depth = {a.id: len(a.path) for a in ancestors}
    out = []
    for f in sorted(fields, key=lambda f: (depth[f.hierarchy_node_id], f.position)):
        defined_at = depth[f.hierarchy_node_id]
        for a in ancestors:  # nearest node at or below where the field is defined that sets a value
            if len(a.path) >= defined_at and (f.id, a.id) in values:
                out.append(Inherited(f, values[(f.id, a.id)] or "", a))
                break
        else:
            out.append(Inherited(f, "", next(a for a in ancestors if a.id == f.hierarchy_node_id)))
    return out


def copy_inherited(db: Session, doc: Document, node: HierarchyNode) -> None:
    for i in inherited_for(db, node):
        db.add(MetadataValue(metadata_field_id=i.field.id, document_id=doc.id, value=i.value,
                             source=MetadataSource.INHERITED.value, inherited_from_node_id=i.from_node.id))


def refresh_documents_under(db: Session, node: HierarchyNode) -> None:
    """Bring the inherited copies of every unapproved document under `node` up to date.
    Approved documents (frozen values) and makers' overrides are left alone."""
    from app.documents.models import DocRepo

    repos = db.scalars(select(DocRepo).join(HierarchyNode, HierarchyNode.id == DocRepo.hierarchy_node_id)
                       .where((HierarchyNode.id == node.id) | HierarchyNode.path.startswith(node.path + "/", autoescape=True))).all()
    for repo in repos:
        inherited = inherited_for(db, repo.node)
        docs = db.scalars(select(Document.id).where(
            Document.doc_repo_id == repo.id, Document.deleted_at.is_(None),
            Document.status != DocumentStatus.APPROVED.value)).all()
        if not docs:
            continue
        rows = {(r.document_id, r.metadata_field_id): r for r in db.scalars(
            select(MetadataValue).where(MetadataValue.document_id.in_(docs)))}
        for doc_id in docs:
            for i in inherited:
                row = rows.get((doc_id, i.field.id))
                if row is None:
                    db.add(MetadataValue(metadata_field_id=i.field.id, document_id=doc_id, value=i.value,
                                         source=MetadataSource.INHERITED.value, inherited_from_node_id=i.from_node.id))
                elif row.source == MetadataSource.INHERITED.value and not row.frozen:
                    row.value, row.inherited_from_node_id = i.value, i.from_node.id
    db.flush()


def freeze(db: Session, doc: Document) -> None:
    db.execute(update(MetadataValue).where(MetadataValue.document_id == doc.id).values(frozen=True))


# --------------------------------------------------------------------------- on a document


@dataclass(frozen=True)
class Entry:
    field_id: uuid.UUID
    label: str
    value: str | None
    state: str  # inherited | overridden | removed | own | suggested
    inherited_value: str | None  # for overridden / removed: the repository's current value
    from_node: str | None  # name of the node the value (or field) comes from
    overridable: bool


def entries(db: Session, docs: Iterable[Document], node: HierarchyNode) -> dict[uuid.UUID, list[Entry]]:
    """Each document's metadata, field by field: repository fields first (in their order), then
    the document's own."""
    docs = list(docs)
    if not docs:
        return {}
    current = {i.field.id: i for i in inherited_for(db, node)}
    rows = db.execute(select(MetadataValue, MetadataField).join(MetadataField)
                      .where(MetadataValue.document_id.in_([d.id for d in docs]))).all()
    names = dict(db.execute(select(HierarchyNode.id, HierarchyNode.name).where(
        HierarchyNode.id.in_({r.inherited_from_node_id for r, _ in rows if r.inherited_from_node_id} |
                             {f.hierarchy_node_id for _, f in rows if f.hierarchy_node_id}))).all())
    out: dict[uuid.UUID, list[tuple[tuple, Entry]]] = {d.id: [] for d in docs}
    for row, field in rows:
        if field.document_id is not None:
            state = "own"
        elif row.source == MetadataSource.INHERITED.value:
            state = "inherited"
        elif row.source == MetadataSource.LLM.value:
            state = "suggested"
        else:
            state = "removed" if row.value is None else "overridden"
        live = current.get(field.id)
        entry = Entry(
            field_id=field.id, label=field.label, value=row.value, state=state,
            inherited_value=live.value if live and state in ("overridden", "removed") else None,
            from_node=names.get(row.inherited_from_node_id or field.hierarchy_node_id) if field.hierarchy_node_id else None,
            overridable=field.overridable,
        )
        order = (0, field.position) if field.hierarchy_node_id else (1, field.position)
        out[row.document_id].append((order, entry))
    return {doc_id: [e for _, e in sorted(items, key=lambda x: x[0])] for doc_id, items in out.items()}


def set_document_metadata(db: Session, actor: AppUser, doc: Document, node: HierarchyNode,
                          inherited: dict[uuid.UUID, tuple[str, str | None]], own: list[tuple[str, str]]) -> None:
    """`inherited`: field id -> ("inherit" | "override" | "remove", value). Fields not mentioned
    stay as they are. `own`: the document's own fields, exactly these (label, value), in order."""
    available = {i.field.id: i for i in inherited_for(db, node)}
    rows = {r.metadata_field_id: r for r in db.scalars(select(MetadataValue).where(MetadataValue.document_id == doc.id))}
    for field_id, (state, value) in inherited.items():
        i = available.get(field_id)
        if i is None:
            raise InvalidRequest("That field isn't one of this repository's.")
        if state != "inherit" and not i.field.overridable:
            raise InvalidRequest(f"{i.field.label} can't be changed on a document.")
        row = rows.get(field_id)
        if row is None:
            row = MetadataValue(metadata_field_id=field_id, document_id=doc.id, source=MetadataSource.INHERITED.value)
            db.add(row)
        if state == "inherit":
            row.source, row.value, row.inherited_from_node_id = MetadataSource.INHERITED.value, i.value, i.from_node.id
        elif state == "override":
            row.source, row.value, row.inherited_from_node_id = MetadataSource.MAKER.value, _clean_value(value), None
        elif state == "remove":
            row.source, row.value, row.inherited_from_node_id = MetadataSource.MAKER.value, None, None
        else:
            raise InvalidRequest("Each repository field is inherit, override or remove.")
        row.set_by_id, row.set_at = actor.id, utcnow()

    taken = {i.field.key for i in available.values()}
    existing = {f.key: f for f in db.scalars(select(MetadataField).where(MetadataField.document_id == doc.id))}
    seen: set[str] = set()
    for position, (raw_label, raw_value) in enumerate(own):
        label, value = clean_label(raw_label), _clean_value(raw_value)
        if not label:
            raise InvalidRequest("Give each additional field a name.")
        key = key_of(label)
        if key in taken:
            raise InvalidRequest(f"{label!r} is already a repository field; change it there.")
        if key in seen:
            raise InvalidRequest(f"{label!r} is given twice.")
        seen.add(key)
        field = existing.pop(key, None)
        if field is None:
            field = MetadataField(document_id=doc.id, key=key, label=label, inheritable=False, created_by_id=actor.id)
            db.add(field)
            db.flush()
        field.label, field.position = label, position
        row = db.scalar(select(MetadataValue).where(MetadataValue.metadata_field_id == field.id,
                                                    MetadataValue.document_id == doc.id))
        if row is None:
            db.add(MetadataValue(metadata_field_id=field.id, document_id=doc.id, value=value,
                                 source=MetadataSource.MAKER.value, set_by_id=actor.id))
        else:
            row.value, row.set_by_id, row.set_at = value, actor.id, utcnow()
    for field in existing.values():
        db.execute(delete(MetadataValue).where(MetadataValue.metadata_field_id == field.id))
        db.delete(field)
    db.flush()
