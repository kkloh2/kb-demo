"""CAMS, first version: approval types and resources, requests, one task per round, assignments,
decisions and the request's event history. Workflow tables come later (see docs/cams-spec-addendum.md).

References into the access model (source systems, nodes, groups, roles, users) are plain UUIDs,
not foreign keys ("logical"), so approvals can become a separate service later. Each request runs a
standalone workflow instance (app.workflows); a task belongs to one of its step instances.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, BigInteger, CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime, utcnow, uuid7
from app.workflows.models import StepInstance

TASK_METADATA_TYPE = JSON().with_variant(JSONB(), "postgresql")


class RequestStatus(StrEnum):
    PENDING = "PENDING"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"  # back with the maker; resubmitting continues this request
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"  # final; a later resubmission is a new request
    CANCELLED = "CANCELLED"


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Decision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


class ApprovalType(Base):
    __tablename__ = "approval_type"
    __table_args__ = (UniqueConstraint("source_system_id", "code", name="uq_approval_type_source_system_id_code"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    source_system_id: Mapped[uuid.UUID] = mapped_column(Uuid)  # logical
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")


class Resource(Base):
    """What approvals happen in: e.g. a document repository (resource_id = its id in Doc Hub), and the
    hierarchy node it sits at (where its workflow is bound and its reviewers hold their roles).
    INACTIVE when the thing is deleted: its open requests are cancelled."""

    __tablename__ = "resource"
    __table_args__ = (UniqueConstraint("source_system_id", "resource_type", "resource_id",
                                       name="uq_resource_source_system_id_resource_type_resource_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    source_system_id: Mapped[uuid.UUID] = mapped_column(Uuid)  # logical
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str] = mapped_column(String(255))  # the source system's own id
    name: Mapped[str] = mapped_column(String(255))
    hierarchy_node_id: Mapped[uuid.UUID] = mapped_column(Uuid)  # logical: the node it sits at
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class ApprovalRequest(Base):
    __tablename__ = "approval_request"
    __table_args__ = (
        UniqueConstraint("source_system_id", "external_reference_id",
                         name="uq_approval_request_source_system_id_external_reference_id"),
        CheckConstraint("status IN ('PENDING', 'CHANGES_REQUESTED', 'APPROVED', 'REJECTED', 'CANCELLED')",
                        name="ck_approval_request_status"),
        Index("ix_approval_request_subject", "subject_type", "subject_id"),
        Index("ix_approval_request_resource_status", "resource_pk", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    source_system_id: Mapped[uuid.UUID] = mapped_column(Uuid)  # logical
    approval_type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approval_type.id"))
    resource_pk: Mapped[uuid.UUID] = mapped_column(ForeignKey("resource.id"))
    external_reference_id: Mapped[str] = mapped_column(String(255))  # e.g. document:<id>:<n>
    subject_type: Mapped[str] = mapped_column(String(64))  # e.g. DOCUMENT
    subject_id: Mapped[str] = mapped_column(String(64))  # logical
    title: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # what the reviewer is shown
    status: Mapped[str] = mapped_column(String(24), default=RequestStatus.PENDING.value)
    current_round: Mapped[int] = mapped_column(Integer, default=1)
    last_event_sequence: Mapped[int] = mapped_column(BigInteger, default=0)
    requested_by: Mapped[uuid.UUID] = mapped_column(Uuid)  # logical (app_user)
    maker_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # logical (app_user): made the subject; never decides it
    workflow_instance_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflow_instance.id"))  # its flow's run
    submitted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    approval_type: Mapped[ApprovalType] = relationship()
    resource: Mapped[Resource] = relationship()
    tasks: Mapped[list["ApprovalTask"]] = relationship(back_populates="request", order_by="(ApprovalTask.round, ApprovalTask.created_at)")


class ApprovalTask(Base):
    """The people's part of a review step: one per step instance (so per step, per round)."""

    __tablename__ = "approval_task"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING', 'COMPLETED', 'CANCELLED')", name="ck_approval_task_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    approval_request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approval_request.id"))
    step_instance_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("step_instance.id"), unique=True)
    round: Mapped[int] = mapped_column(Integer)
    # Exactly what this round reviews (a document: file, fingerprint, every metadata value), kept as
    # evidence and never changed. For review and audit only; lists don't read it.
    subject_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Additional information, e.g. for lists, written when the task is created: type,
    # type_label, title, round, submitted_by {lan_id, display_name}, submitted_at, resource {type, id,
    # name}, subject {type, id}, plus what the asking module adds (a document: folder, size, uploader).
    # JSONB on PostgreSQL. The attribute isn't called `metadata`: SQLAlchemy reserves that name.
    task_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", TASK_METADATA_TYPE, default=dict)
    status: Mapped[str] = mapped_column(String(16), default=TaskStatus.PENDING.value)
    completion_rule: Mapped[str] = mapped_column(String(8), default="ANY")
    outcome: Mapped[str | None] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    request: Mapped[ApprovalRequest] = relationship(back_populates="tasks")
    step: Mapped[StepInstance] = relationship()
    assignment: Mapped["ApprovalTaskAssignment"] = relationship(back_populates="task", uselist=False)
    decisions: Mapped[list["ApprovalDecision"]] = relationship(back_populates="task", order_by="ApprovalDecision.decided_at")


class AssignmentStatus(StrEnum):
    ACTIVE = "ACTIVE"  # the task is waiting: it's in the inbox of whoever holds the role at the node
    CLOSED = "CLOSED"  # decided or cancelled


class ApprovalTaskAssignment(Base):
    """Who may decide the task: people holding `required_role_id` at `hierarchy_node_id`, through
    any of the node's groups (checked when deciding). `group_id` is the group it was first sent to.
    Snapshotted when the task is created. The inbox reads only ACTIVE ones (a partial index)."""

    __tablename__ = "approval_task_assignment"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'CLOSED')", name="ck_approval_task_assignment_status"),
        Index("ix_approval_task_assignment_open", "hierarchy_node_id", "required_role_id",
              sqlite_where=text("status = 'ACTIVE'"), postgresql_where=text("status = 'ACTIVE'")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    approval_task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approval_task.id"), unique=True)
    group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # logical (user_group): the node's default group, if any
    hierarchy_node_id: Mapped[uuid.UUID] = mapped_column(Uuid)  # logical
    required_role_id: Mapped[uuid.UUID] = mapped_column(Uuid)  # logical (role)
    assignment_strategy: Mapped[str] = mapped_column(String(32), default="RESOURCE_NODE")
    status: Mapped[str] = mapped_column(String(16), default=AssignmentStatus.ACTIVE.value)
    assigned_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    task: Mapped[ApprovalTask] = relationship(back_populates="assignment")


class ApprovalTaskAssignee(Base):
    """One person who may decide the task: everyone holding the assignment's role at its node, except
    whoever made or submitted the subject. Written when the task is created, kept current when roles
    change (access.on_roles_changed), closed when the task is decided or cancelled. The inbox reads a
    person's ACTIVE rows directly (a partial index on user_id)."""

    __tablename__ = "approval_task_assignee"
    __table_args__ = (
        UniqueConstraint("approval_task_id", "user_id", name="uq_approval_task_assignee_approval_task_id_user_id"),
        CheckConstraint("status IN ('ACTIVE', 'CLOSED')", name="ck_approval_task_assignee_status"),
        Index("ix_approval_task_assignee_inbox", "user_id",
              sqlite_where=text("status = 'ACTIVE'"), postgresql_where=text("status = 'ACTIVE'")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    approval_task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approval_task.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)  # logical (app_user)
    status: Mapped[str] = mapped_column(String(16), default=AssignmentStatus.ACTIVE.value)
    assigned_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class ApprovalDecision(Base):
    __tablename__ = "approval_decision"
    __table_args__ = (
        UniqueConstraint("approval_task_id", "decided_by", name="uq_approval_decision_approval_task_id_decided_by"),
        CheckConstraint("decision IN ('APPROVED', 'REJECTED', 'CHANGES_REQUESTED')", name="ck_approval_decision_decision"),
        CheckConstraint("decision = 'APPROVED' OR (comment IS NOT NULL AND trim(comment) <> '')",
                        name="ck_approval_decision_comment_required"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    approval_task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approval_task.id"))
    decided_by: Mapped[uuid.UUID] = mapped_column(Uuid)  # logical (app_user)
    decision: Mapped[str] = mapped_column(String(24))
    comment: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    task: Mapped[ApprovalTask] = relationship(back_populates="decisions")


class ApprovalEvent(Base):
    """The request's history, append-only, numbered per request."""

    __tablename__ = "approval_event"
    __table_args__ = (UniqueConstraint("approval_request_id", "event_sequence",
                                       name="uq_approval_event_approval_request_id_event_sequence"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    approval_request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approval_request.id"))
    approval_task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("approval_task.id"))
    event_type: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # logical
    event_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    event_sequence: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
