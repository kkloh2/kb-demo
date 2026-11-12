"""Projects, their members and metadata fields, and their documents."""

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime, utcnow
from app.users.models import Department, User


class ProjectRole(StrEnum):
    MAKER = "MAKER"  # uploads documents
    CHECKER = "CHECKER"  # approves or rejects them
    VIEWER = "VIEWER"  # sees approved documents


PROJECT_ROLE_ORDER = [ProjectRole.MAKER, ProjectRole.CHECKER, ProjectRole.VIEWER]


class Project(Base):
    """A department's logical group of documents, with the base metadata its documents share."""

    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("department_id", "name", name="uq_projects_department_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # RESTRICT: a department with projects can't be deleted until its projects are.
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    # Base metadata, copied onto each document (a maker can override it per document).
    country: Mapped[str] = mapped_column(String(64), default="")
    business_unit: Mapped[str] = mapped_column(String(128), default="")
    purpose: Mapped[str] = mapped_column(String(128), default="")  # e.g. "Credit card", "Loan"
    valid_till: Mapped[date | None] = mapped_column(Date)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    department: Mapped[Department] = relationship()
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    members: Mapped[list["ProjectMember"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class ProjectMember(Base):
    """A project role held by a user, given by the department's admin."""

    __tablename__ = "project_members"
    __table_args__ = (CheckConstraint("role IN ('MAKER', 'CHECKER', 'VIEWER')", name="ck_project_members_role"),)

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), primary_key=True)
    granted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    granted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    project: Mapped[Project] = relationship(back_populates="members")
    user: Mapped[User] = relationship(foreign_keys=[user_id])


# --------------------------------------------------------------------------- metadata fields


class FieldType(StrEnum):
    TEXT = "text"
    DATE = "date"  # YYYY-MM-DD
    SELECT = "select"  # one of `options`


class ProjectField(Base):
    """A metadata field the project's documents fill in (defined by the department admin), so
    makers enter consistent, searchable values. Makers may add their own fields on top."""

    __tablename__ = "project_fields"
    __table_args__ = (
        UniqueConstraint("project_id", "key", name="uq_project_fields_key"),
        CheckConstraint("type IN ('text', 'date', 'select')", name="ck_project_fields_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64))  # e.g. "product_code"
    label: Mapped[str] = mapped_column(String(128))  # e.g. "Product code"
    type: Mapped[str] = mapped_column(String(16), default=FieldType.TEXT.value)
    options: Mapped[list[str]] = mapped_column(JSON, default=list)  # for "select"
    required: Mapped[bool] = mapped_column(Boolean, default=False)  # needed before submitting
    position: Mapped[int] = mapped_column(Integer, default=0)


# --------------------------------------------------------------------------- documents


class DocumentStatus(StrEnum):
    DRAFT = "draft"  # uploaded; the maker is filling in metadata
    PENDING = "pending_approval"  # submitted; waiting for a checker
    APPROVED = "approved"  # viewable by the project's viewers
    REJECTED = "rejected"  # back with the maker, with the checker's reason


BASE_FIELDS = ("country", "business_unit", "purpose", "valid_till")  # copied from the project


class Document(Base):
    """An uploaded file in a project, its metadata and its maker-checker state.

    The folder is a logical path inside the project ("Policies/2026"), kept from folder uploads
    so the project can be browsed like a drive. The file itself is stored by document id
    (upload_dir/projects/<project>/<document>/<filename>), independent of the folder.
    """

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'pending_approval', 'approved', 'rejected')", name="ck_documents_status"
        ),
        CheckConstraint("checker_id IS NULL OR checker_id <> maker_id", name="ck_documents_maker_checker"),
        Index("ix_documents_project_folder", "project_id", "folder"),
        Index("ix_documents_project_status", "project_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    folder: Mapped[str] = mapped_column(String(512), default="")  # "" = the project's top level
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

    # Base metadata: copied from the project at upload; the maker may override each field.
    country: Mapped[str] = mapped_column(String(64), default="")
    business_unit: Mapped[str] = mapped_column(String(128), default="")
    purpose: Mapped[str] = mapped_column(String(128), default="")
    valid_till: Mapped[date | None] = mapped_column(Date)
    base_overrides: Mapped[list[str]] = mapped_column(JSON, default=list)  # base fields the maker changed

    # Phase 2: metadata an LLM extracts from the file in the background.
    ai_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    project: Mapped[Project] = relationship()
    maker: Mapped[User | None] = relationship(foreign_keys=[maker_id])
    checker: Mapped[User | None] = relationship(foreign_keys=[checker_id])
    values: Mapped[list["DocumentValue"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentValue.key"
    )


class DocumentValue(Base):
    """One metadata value of a document, one row per key, so documents can be found by metadata
    (e.g. product_code = "VISA-PLAT"). `source` says where the key comes from: a project field
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
