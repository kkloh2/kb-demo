"""Source systems and their trees.

    source_system ── hierarchy (its levels, e.g. ROOT -> DOC_REPO) ── hierarchy_node (one root per hierarchy)

PLATFORM is seeded at start-up; platform admins create every other system, its hierarchy and its
root in Administration. A root gets two groups, admins and users (app.access).
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, String, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime, utcnow, uuid7


class Status(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class NodeStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DELETED = "DELETED"  # soft delete: kept with everything in it, restorable by a platform admin


class SourceSystem(Base):
    """An application with its own hierarchy. PLATFORM (Data Hub itself) is seeded; platform admins
    create the others (e.g. DOC_HUB) in Administration."""

    __tablename__ = "source_system"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default=Status.ACTIVE.value)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Hierarchy(Base):
    """The tree of one source system (exactly one per system for now), with its levels."""

    __tablename__ = "hierarchy"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    source_system_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_system.id"), unique=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    # The node type at each level, root first: e.g. ["ROOT", "DOC_REPO"] for Doc Hub (two levels).
    levels: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["ROOT"], server_default=text("'[\"ROOT\"]'"))
    status: Mapped[str] = mapped_column(String(16), default=Status.ACTIVE.value)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    source_system: Mapped[SourceSystem] = relationship()


class HierarchyNode(Base):
    """A place in a source system's tree: its root, or e.g. a document repository.

    `path` is the codes from the root down ("/DOC_HUB/LOAN_RISKS"), so a node's ancestors are
    found without a recursive query. A node's code never changes once created; its name can.
    """

    __tablename__ = "hierarchy_node"
    __table_args__ = (
        UniqueConstraint("hierarchy_id", "code", name="uq_hierarchy_node_hierarchy_id_code"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_hierarchy_node_not_own_parent"),
        CheckConstraint("status IN ('ACTIVE', 'DELETED')", name="ck_hierarchy_node_status"),
        Index("uq_hierarchy_node_one_root", "hierarchy_id", unique=True,
              sqlite_where=text("parent_id IS NULL"), postgresql_where=text("parent_id IS NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    hierarchy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hierarchy.id"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("hierarchy_node.id"), index=True)
    code: Mapped[str] = mapped_column(String(64))
    path: Mapped[str] = mapped_column(String(1024), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    node_type: Mapped[str] = mapped_column(String(32))  # ROOT, DOC_REPO, ...
    status: Mapped[str] = mapped_column(String(16), default=NodeStatus.ACTIVE.value)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    deleted_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    hierarchy: Mapped[Hierarchy] = relationship()

    @property
    def depth(self) -> int:
        """0 for a root, 1 for its children, ..."""
        return self.path.strip("/").count("/")

    @property
    def ancestor_paths(self) -> list[str]:
        """This node's path and every ancestor's: /A/B/C -> [/A, /A/B, /A/B/C]."""
        parts = self.path.strip("/").split("/")
        return ["/" + "/".join(parts[: i + 1]) for i in range(len(parts))]
