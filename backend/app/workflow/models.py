"""Workflow tables: definitions (what the flow is), instances (one per subject) and tasks
(the work waiting for people). Engine state lives in workflow_instances.state as JSON;
workflow_tasks mirrors the engine's ready tasks so inboxes can be queried with SQL."""

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models import Base, UTCDateTime, utcnow


class WorkflowDefinition(Base):
    """A versioned flow. New instances use the active version of a key; running instances keep
    the version they started with."""

    __tablename__ = "workflow_definitions"
    __table_args__ = (
        UniqueConstraint("key", "version", name="uq_workflow_definitions_key_version"),
        Index("uq_workflow_definitions_one_active", "key", unique=True, sqlite_where=text("is_active = 1")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64))  # e.g. "document_approval"
    version: Mapped[int]
    engine: Mapped[str] = mapped_column(String(64))  # e.g. "builtin.single_review", later "spiff.bpmn"
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str | None] = mapped_column(Text)  # BPMN XML for file-based engines; NULL for built-in
    source_filename: Mapped[str | None] = mapped_column(String(256))
    is_active: Mapped[bool] = mapped_column(default=False)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class WorkflowInstance(Base):
    __tablename__ = "workflow_instances"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'completed', 'cancelled')", name="ck_workflow_instances_status"),
        Index("ix_workflow_instances_subject", "subject_type", "subject_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    definition_id: Mapped[int] = mapped_column(ForeignKey("workflow_definitions.id"))
    subject_type: Mapped[str] = mapped_column(String(32))  # e.g. "document"
    subject_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="running")
    state: Mapped[str] = mapped_column(Text)  # engine state, JSON
    outcome: Mapped[str | None] = mapped_column(Text)  # JSON, when completed
    started_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    definition: Mapped[WorkflowDefinition] = relationship()
    tasks: Mapped[list["WorkflowTask"]] = relationship(
        back_populates="instance", cascade="all, delete-orphan", order_by="WorkflowTask.id"
    )


class WorkflowTask(Base):
    __tablename__ = "workflow_tasks"
    __table_args__ = (
        CheckConstraint("status IN ('ready', 'completed', 'cancelled')", name="ck_workflow_tasks_status"),
        Index("ix_workflow_tasks_inbox", "status", "lane"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instance_id: Mapped[int] = mapped_column(ForeignKey("workflow_instances.id", ondelete="CASCADE"), index=True)
    engine_task_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(128))
    lane: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="ready")
    data: Mapped[str | None] = mapped_column(Text)  # JSON submitted on completion
    completed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    instance: Mapped[WorkflowInstance] = relationship(back_populates="tasks")
