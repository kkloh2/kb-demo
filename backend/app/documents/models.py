"""Doc Hub: document repositories, their documents, and metadata.

A repository is a DOC_REPO node in the DOC_HUB tree (its name, members and deletion live there);
doc_repo holds what only repositories have.

Metadata is one model for every level. A field is defined at a node (and applies to the
documents below it) or on one document. A value is set at a node or on a document. Each document
carries its own copy of every inherited value (source INHERITED), kept up to date while the
document isn't approved and frozen once it is, so a search is one simple query and an approved
document's record matches what was checked.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.access.models import AppUser, HierarchyNode
from app.db.base import Base, UTCDateTime, utcnow, uuid7


class DocRepo(Base):
    __tablename__ = "doc_repo"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    hierarchy_node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hierarchy_node.id"), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    node: Mapped[HierarchyNode] = relationship()
    created_by: Mapped[AppUser | None] = relationship()


class DocumentStatus(StrEnum):
    DRAFT = "draft"
    PENDING = "pending_approval"
    CHANGES_REQUESTED = "changes_requested"  # back with the maker; resubmitting continues the request
    APPROVED = "approved"  # metadata locked
    REJECTED = "rejected"  # back with the maker; resubmitting is a new request


STATUS_CHECK = "status IN ('draft', 'pending_approval', 'changes_requested', 'approved', 'rejected')"


class Document(Base):
    """A file at a place in a repository: `folder` ("Policies/2026") + `filename`. Uploading the same
    name to the same folder again gives it a new version (DocumentVersion) instead of a second
    document.

    The row is the working copy of the latest version (`version`): its file, status, approval
    request and, through metadata_value, its metadata. `approved_version` is the number of the
    latest approved version, which is what viewers see (from that version's row and snapshot when
    a newer version is being worked on)."""

    __tablename__ = "document"
    __table_args__ = (
        CheckConstraint(STATUS_CHECK, name="ck_document_status"),
        Index("ix_document_doc_repo_id_status", "doc_repo_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    doc_repo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("doc_repo.id"))
    folder: Mapped[str] = mapped_column(String(512), default="")
    filename: Mapped[str] = mapped_column(String(256))
    content_type: Mapped[str | None] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    storage_path: Mapped[str] = mapped_column(String(512), default="")  # relative to settings.upload_dir
    content_hash: Mapped[str] = mapped_column(String(64), default="")  # sha256 of the file
    upload_batch: Mapped[str | None] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(24), default=DocumentStatus.DRAFT.value)
    maker_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    latest_approval_request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # logical (approvals)
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")  # the latest version's number
    approved_version: Mapped[int | None] = mapped_column(Integer)  # the latest approved version's number
    deleted_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    doc_repo: Mapped[DocRepo] = relationship()
    maker: Mapped[AppUser | None] = relationship(foreign_keys=[maker_id])


class DocumentVersion(Base):
    """One version of a document: its file, who uploaded it, and how far it got. The latest version
    mirrors the document row (kept in step when it changes); an earlier one is fixed once a newer
    version replaces it, with `metadata_snapshot` holding its metadata from that moment (used to
    show an approved version while a newer one is worked on, to fall back to it, or to restore it).

    Every version's file is kept (`storage_path`); retiring old versions is for a later lifecycle
    policy."""

    __tablename__ = "document_version"
    __table_args__ = (
        UniqueConstraint("document_id", "number", name="uq_document_version_document_id_number"),
        CheckConstraint(STATUS_CHECK, name="ck_document_version_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document.id"))
    number: Mapped[int] = mapped_column(Integer)  # 1, 2, 3 ...
    filename: Mapped[str] = mapped_column(String(256))
    content_type: Mapped[str | None] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    storage_path: Mapped[str] = mapped_column(String(512), default="")  # relative to settings.upload_dir
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(24), default=DocumentStatus.DRAFT.value)
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # logical (approvals)
    restored_from: Mapped[int | None] = mapped_column(Integer)  # the version it was copied from, if restored
    metadata_snapshot: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)  # set when it stops being latest
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    superseded_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # a newer version replaced it
    discarded_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # the maker threw it away
    discarded_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    uploaded_by: Mapped[AppUser | None] = relationship(foreign_keys=[uploaded_by_id])


class MetadataSource(StrEnum):
    ADMIN = "ADMIN"  # set at a node by its owner or admin
    MAKER = "MAKER"  # set on a document by a maker (an override, a removal, or their own field)
    LLM = "LLM"  # phase 2: extracted from the file
    INHERITED = "INHERITED"  # a document's copy of a value set above it


class MetadataField(Base):
    """A metadata field, defined at a node (applies to the documents below it) or on one document."""

    __tablename__ = "metadata_field"
    __table_args__ = (
        CheckConstraint("(hierarchy_node_id IS NULL) <> (document_id IS NULL)", name="ck_metadata_field_one_target"),
        UniqueConstraint("hierarchy_node_id", "key", name="uq_metadata_field_hierarchy_node_id_key"),
        UniqueConstraint("document_id", "key", name="uq_metadata_field_document_id_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    hierarchy_node_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("hierarchy_node.id"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("document.id"))
    key: Mapped[str] = mapped_column(String(64))  # the label, case-folded and trimmed
    label: Mapped[str] = mapped_column(String(64))
    inheritable: Mapped[bool] = mapped_column(Boolean, default=True)
    overridable: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class MetadataValue(Base):
    """A field's value at a node or on a document. On a document, a null value means the maker
    removed the field there."""

    __tablename__ = "metadata_value"
    __table_args__ = (
        CheckConstraint("(hierarchy_node_id IS NULL) <> (document_id IS NULL)", name="ck_metadata_value_one_target"),
        CheckConstraint("source IN ('ADMIN', 'MAKER', 'LLM', 'INHERITED')", name="ck_metadata_value_source"),
        UniqueConstraint("metadata_field_id", "hierarchy_node_id", name="uq_metadata_value_metadata_field_id_hierarchy_node_id"),
        UniqueConstraint("metadata_field_id", "document_id", name="uq_metadata_value_metadata_field_id_document_id"),
        Index("ix_metadata_value_field_value", "metadata_field_id", "value"),
        Index("ix_metadata_value_document_id", "document_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    metadata_field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("metadata_field.id"))
    hierarchy_node_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("hierarchy_node.id"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("document.id"))
    value: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16))
    inherited_from_node_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("hierarchy_node.id"))
    frozen: Mapped[bool] = mapped_column(Boolean, default=False)  # the document is approved: locked
    set_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    set_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    field: Mapped[MetadataField] = relationship()
