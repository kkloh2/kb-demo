"""Doc-repos, their members, and their documents."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime, utcnow
from app.users.models import Department, User


class DocRepoRole(StrEnum):
    MAKER = "MAKER"  # uploads documents
    CHECKER = "CHECKER"  # approves or rejects them
    VIEWER = "VIEWER"  # sees approved documents


DOC_REPO_ROLE_ORDER = [DocRepoRole.MAKER, DocRepoRole.CHECKER, DocRepoRole.VIEWER]


class DocRepo(Base):
    """A department's logical group of documents, with the department metadata its documents share."""

    __tablename__ = "doc_repos"
    __table_args__ = (UniqueConstraint("department_id", "name", name="uq_doc_repos_department_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # RESTRICT: a department with doc-repos can't be deleted until its doc-repos are.
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    # Department metadata ({key: value} for DEPARTMENT_METADATA_KEYS), copied onto each document;
    # a maker can override it per document.
    department_metadata: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    # Repository metadata: [{"key": ..., "value": ...}] in order, plain text, set by the department
    # admin. Each document starts with these values; a maker can change them per document.
    repository_metadata: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    department: Mapped[Department] = relationship()
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    members: Mapped[list["DocRepoMember"]] = relationship(back_populates="doc_repo", cascade="all, delete-orphan")


class DocRepoMember(Base):
    """A doc-repo role held by a user, given by the department's admin."""

    __tablename__ = "doc_repo_members"
    __table_args__ = (CheckConstraint("role IN ('MAKER', 'CHECKER', 'VIEWER')", name="ck_doc_repo_members_role"),)

    doc_repo_id: Mapped[int] = mapped_column(ForeignKey("doc_repos.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), primary_key=True)
    granted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    granted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    doc_repo: Mapped[DocRepo] = relationship(back_populates="members")
    user: Mapped[User] = relationship(foreign_keys=[user_id])


# --------------------------------------------------------------------------- documents


class DocumentStatus(StrEnum):
    DRAFT = "draft"  # uploaded; the maker is filling in metadata
    PENDING = "pending_approval"  # submitted; waiting for a checker
    APPROVED = "approved"  # viewable by the doc-repo's viewers
    REJECTED = "rejected"  # back with the maker, with the checker's reason


DEPARTMENT_METADATA_KEYS = ("department", "business_unit", "country")  # copied from the doc-repo


class Document(Base):
    """An uploaded file in a doc-repo, its metadata and its maker-checker state.

    The folder is a logical path inside the doc-repo ("Policies/2026"), kept from folder uploads
    so the doc-repo can be browsed like a drive. The file itself is stored by document id
    (upload_dir/doc-repos/<doc-repo>/<document>/<filename>), independent of the folder.
    """

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'pending_approval', 'approved', 'rejected')", name="ck_documents_status"
        ),
        CheckConstraint("checker_id IS NULL OR checker_id <> maker_id", name="ck_documents_maker_checker"),
        Index("ix_documents_doc_repo_folder", "doc_repo_id", "folder"),
        Index("ix_documents_doc_repo_status", "doc_repo_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    doc_repo_id: Mapped[int] = mapped_column(ForeignKey("doc_repos.id", ondelete="CASCADE"))
    folder: Mapped[str] = mapped_column(String(512), default="")  # "" = the doc-repo's top level
    filename: Mapped[str] = mapped_column(String(256))
    content_type: Mapped[str | None] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    storage_path: Mapped[str] = mapped_column(String(512))  # relative to settings.upload_dir
    upload_batch: Mapped[str | None] = mapped_column(String(36), index=True)  # one bulk upload

    status: Mapped[str] = mapped_column(String(24), default=DocumentStatus.DRAFT.value)
    maker_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    checker_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    rejection_reason: Mapped[str | None] = mapped_column(Text)

    # Department metadata: copied from the doc-repo at upload; the maker may override each key.
    department_metadata: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    department_overrides: Mapped[list[str]] = mapped_column(JSON, default=list)  # keys the maker changed

    # Phase 2: metadata an LLM extracts from the file in the background.
    ai_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    doc_repo: Mapped[DocRepo] = relationship()
    maker: Mapped[User | None] = relationship(foreign_keys=[maker_id])
    checker: Mapped[User | None] = relationship(foreign_keys=[checker_id])
    values: Mapped[list["DocumentValue"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentValue.key"
    )


class DocumentValue(Base):
    """One metadata value of a document, one row per key, so documents can be found by metadata
    (e.g. product_code = "VISA-PLAT"). `source` says where the key comes from: a doc-repo field
    ("field") or one the maker added ("extra")."""

    __tablename__ = "document_values"
    __table_args__ = (
        CheckConstraint("source IN ('field', 'extra')", name="ck_document_values_source"),
        Index("ix_document_values_key_value", "key", "value"),
    )

    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    source: Mapped[str] = mapped_column(String(8), primary_key=True)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")

    document: Mapped[Document] = relationship(back_populates="values")
