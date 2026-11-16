import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime, utcnow, uuid7


class AuditAction(Base):
    """A kind of event, registered in code (app.audit.catalog) and synced here at start-up."""

    __tablename__ = "audit_action"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)  # e.g. DOCUMENTS_UPLOADED
    source_system: Mapped[str] = mapped_column(String(32))  # the area it belongs to by default, e.g. DOC_HUB
    category: Mapped[str] = mapped_column(String(16))  # access, configuration, content, approval, security
    label: Mapped[str] = mapped_column(String(128))  # e.g. "Documents uploaded"
    description: Mapped[str] = mapped_column(String(255), default="")


class AuditEvent(Base):
    """Who did what, where, when and from where. Written with the change it describes; never changed."""

    __tablename__ = "audit_event"
    __table_args__ = (
        Index("ix_audit_event_source_system_created_at", "source_system", "created_at"),
        Index("ix_audit_event_node_created_at", "hierarchy_node_id", "created_at"),
        Index("ix_audit_event_actor_created_at", "actor_id", "created_at"),
        Index("ix_audit_event_target", "target_type", "target_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    actor_lan_id: Mapped[str | None] = mapped_column(String(64))  # kept even if the user changes; tried LAN ID on failures
    action: Mapped[str] = mapped_column(ForeignKey("audit_action.code"))
    source_system: Mapped[str] = mapped_column(String(32))  # PLATFORM, WORKFLOWS, DOC_HUB, APPROVALS ...
    category: Mapped[str] = mapped_column(String(16))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(String(64))
    hierarchy_node_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)  # logical
    node_path: Mapped[str | None] = mapped_column(String(1024))  # e.g. /DOC_HUB/RISK_POLICIES, for "this and below"
    details: Mapped[dict[str, Any]] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), default=dict)
    request_id: Mapped[str | None] = mapped_column(String(36))
    client_ip: Mapped[str | None] = mapped_column(String(45))
