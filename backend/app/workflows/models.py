"""Workflow tables. Generic: an instance runs for a subject (subject_type, subject_id) at a hierarchy
node; nothing here refers to approvals or any source system's tables."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime, utcnow, uuid7

JSONX = JSON().with_variant(JSONB(), "postgresql")


class VersionStatus(StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"  # never changed again
    RETIRED = "RETIRED"


class WorkflowDefinition(Base):
    """A flow, e.g. DOC_HUB.DOCUMENT_APPROVAL. `kind` is what its steps work on (from its step types),
    e.g. DOC_HUB.DOCUMENT: a node can only be bound to a flow of the kind it needs."""

    __tablename__ = "workflow_definition"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    code: Mapped[str] = mapped_column(String(128), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class WorkflowVersion(Base):
    """One version of a flow: the JSON. Published versions never change; an instance runs on the
    version it started with."""

    __tablename__ = "workflow_version"
    __table_args__ = (
        UniqueConstraint("workflow_definition_id", "version", name="uq_workflow_version_workflow_definition_id_version"),
        CheckConstraint("status IN ('DRAFT', 'PUBLISHED', 'RETIRED')", name="ck_workflow_version_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    workflow_definition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_definition.id"))
    version: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONX)
    status: Mapped[str] = mapped_column(String(16), default=VersionStatus.DRAFT.value)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    workflow: Mapped[WorkflowDefinition] = relationship()


class WorkflowBinding(Base):
    """Which flow a node uses for subjects of a kind (e.g. a repository's documents). New instances
    start on the flow's latest published version."""

    __tablename__ = "workflow_binding"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="ck_workflow_binding_status"),
        Index("uq_workflow_binding_one_per_node_kind", "hierarchy_node_id", "kind", unique=True,
              sqlite_where=text("status = 'ACTIVE'"), postgresql_where=text("status = 'ACTIVE'")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    hierarchy_node_id: Mapped[uuid.UUID] = mapped_column(Uuid)  # logical
    kind: Mapped[str] = mapped_column(String(64))
    workflow_definition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_definition.id"))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    bound_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # logical (app_user)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class InstanceStatus(StrEnum):
    RUNNING = "RUNNING"  # a step is active (working, or waiting for someone)
    COMPLETED = "COMPLETED"  # reached an END; `outcome` says which
    CANCELLED = "CANCELLED"


class WorkflowInstance(Base):
    """One run of a flow for a subject (e.g. an approval request), at a node, on a pinned version."""

    __tablename__ = "workflow_instance"
    __table_args__ = (
        CheckConstraint("status IN ('RUNNING', 'COMPLETED', 'CANCELLED')", name="ck_workflow_instance_status"),
        Index("ix_workflow_instance_subject", "subject_type", "subject_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    workflow_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_version.id"))
    subject_type: Mapped[str] = mapped_column(String(64))  # e.g. APPROVAL_REQUEST
    subject_id: Mapped[str] = mapped_column(String(64))
    hierarchy_node_id: Mapped[uuid.UUID] = mapped_column(Uuid)  # logical: where it runs
    round: Mapped[int] = mapped_column(Integer, default=1)  # goes up when the flow comes back to a step
    current_step: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default=InstanceStatus.RUNNING.value)
    outcome: Mapped[str | None] = mapped_column(String(32))  # the END reached, e.g. APPROVED
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    version: Mapped[WorkflowVersion] = relationship()


class StepStatus(StrEnum):
    ACTIVE = "ACTIVE"  # working, or waiting (for a decision, a resubmission ...)
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class StepInstance(Base):
    """One step reached in one round, and how it ended."""

    __tablename__ = "step_instance"
    __table_args__ = (
        UniqueConstraint("workflow_instance_id", "round", "step_id",
                         name="uq_step_instance_workflow_instance_id_round_step_id"),
        CheckConstraint("status IN ('ACTIVE', 'COMPLETED', 'CANCELLED')", name="ck_step_instance_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    workflow_instance_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_instance.id"))
    round: Mapped[int] = mapped_column(Integer)
    step_id: Mapped[str] = mapped_column(String(64))
    step_type: Mapped[str] = mapped_column(String(64))  # a registered step type, e.g. DOCUMENT_REVIEW
    status: Mapped[str] = mapped_column(String(16), default=StepStatus.ACTIVE.value)
    outcome: Mapped[str | None] = mapped_column(String(32))  # one of the step type's outcomes
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # e.g. why a check failed
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    instance: Mapped[WorkflowInstance] = relationship()
