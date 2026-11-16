"""The access model: who someone is and what each person may do where.

    hierarchy_node (app.sources: source systems and their trees)
          │
     user_group (named groups at a node: ADMINS and USERS at a root; at a repository its default
          │      group MEMBERS ("Users", holds the owner) and the CUSTOM ones its admins make;
          │      TEAM: e.g. COMPLIANCE, at the PLATFORM root)
                     app_user ── user_group_member ── user_group_member_role ── role ── permission

A group is just a name: each member holds their own roles in it (user_group_member_role), e.g.
Maker for one person and Checker for another in a repository's group "default".

Every role applies only at the node where it's granted: nothing is inherited down the tree.
Teams reach other nodes only through explicit node_team_grant rows (read-only roles), which
default_grant rows copy onto new child nodes.

Memberships, roles and grants are never deleted: they become INACTIVE, so history stays.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime, utcnow, uuid7
from app.sources.models import Hierarchy, HierarchyNode, NodeStatus, SourceSystem  # noqa: F401  (re-exported)


class Status(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class GroupType(StrEnum):
    ADMINS = "ADMINS"  # a system root's admins (ADMIN)
    USERS = "USERS"  # a system root's users (VIEWER); everyone joins at first sign-in
    MEMBERS = "MEMBERS"  # a repository's default user group ("Users"); it holds the owner
    CUSTOM = "CUSTOM"  # a repository's other user groups, made by its owner and admins
    TEAM = "TEAM"  # a team (COMPLIANCE, AUDIT) given read-only roles on other nodes by team grants


class AppUser(Base):
    """A person, keyed by LAN ID. Created at first sign-in and refreshed from the directory at
    every sign-in after. No passwords are stored: the directory checks them."""

    __tablename__ = "app_user"
    __table_args__ = (CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="ck_app_user_status"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    lan_id: Mapped[str] = mapped_column(String(64), unique=True)  # lower-case
    email: Mapped[str] = mapped_column(String(256))
    display_name: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(128), default="")
    directory_department: Mapped[str] = mapped_column(String(128), default="")  # profile text only
    status: Mapped[str] = mapped_column(String(16), default=Status.ACTIVE.value)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Role(Base):
    """Seeded from code (app.access.catalog)."""

    __tablename__ = "role"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(256), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)


class Permission(Base):
    """What a role lets someone do, as <system>.<object>.<action>. Seeded from code."""

    __tablename__ = "permission"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(256), default="")


class RolePermission(Base):
    __tablename__ = "role_permission"

    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("role.id", ondelete="CASCADE"), primary_key=True)
    permission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("permission.id", ondelete="CASCADE"), primary_key=True)


class UserGroup(Base):
    """People at a node: just a name. Each member holds their own roles in the group
    (user_group_member_role), e.g. Maker in a repository's "default" group.
    A node has at most one active group of each type, except CUSTOM (a repository's own groups) and
    TEAM (teams, at the PLATFORM root).
    `auto_join_role_id`: everyone is added with this role (at first sign-in, or when the group is created)."""

    __tablename__ = "user_group"
    __table_args__ = (
        CheckConstraint("group_type IN ('ADMINS', 'USERS', 'MEMBERS', 'CUSTOM', 'TEAM')",
                        name="ck_user_group_group_type"),
        Index("uq_user_group_one_per_type", "hierarchy_node_id", "group_type", unique=True,
              sqlite_where=text("group_type NOT IN ('TEAM', 'CUSTOM') AND status = 'ACTIVE'"),
              postgresql_where=text("group_type NOT IN ('TEAM', 'CUSTOM') AND status = 'ACTIVE'")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    hierarchy_node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hierarchy_node.id"), index=True)
    code: Mapped[str] = mapped_column(String(128), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    group_type: Mapped[str] = mapped_column(String(16))
    auto_join_role_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("role.id"))
    status: Mapped[str] = mapped_column(String(16), default=Status.ACTIVE.value)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    node: Mapped[HierarchyNode] = relationship()


class UserGroupMember(Base):
    __tablename__ = "user_group_member"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_user_group_member_group_id_user_id"),
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="ck_user_group_member_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_group.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default=Status.ACTIVE.value)
    added_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    added_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    group: Mapped[UserGroup] = relationship()
    user: Mapped[AppUser] = relationship(foreign_keys=[user_id])
    roles: Mapped[list["UserGroupMemberRole"]] = relationship(back_populates="member")


class UserGroupMemberRole(Base):
    """A role held by one member of a group: the individual grant (membership alone grants nothing)."""

    __tablename__ = "user_group_member_role"
    __table_args__ = (
        UniqueConstraint("group_member_id", "role_id", name="uq_user_group_member_role_group_member_id_role_id"),
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="ck_user_group_member_role_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    group_member_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_group_member.id"))
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("role.id"))
    status: Mapped[str] = mapped_column(String(16), default=Status.ACTIVE.value)
    granted_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    granted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    member: Mapped[UserGroupMember] = relationship(back_populates="roles")
    role: Mapped[Role] = relationship()


class NodeTeamGrant(Base):
    """A team holds a read-only role (VIEWER, AUDITOR) at one node: its current members get it there.
    Managed by platform admins only."""

    __tablename__ = "node_team_grant"
    __table_args__ = (
        UniqueConstraint("hierarchy_node_id", "team_group_id", "role_id",
                         name="uq_node_team_grant_hierarchy_node_id_team_group_id_role_id"),
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="ck_node_team_grant_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    hierarchy_node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hierarchy_node.id"), index=True)
    team_group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_group.id"))
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("role.id"))
    default_grant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("default_grant.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(16), default=Status.ACTIVE.value)
    granted_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    granted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    team: Mapped[UserGroup] = relationship()
    role: Mapped[Role] = relationship()


class DefaultGrant(Base):
    """Team grants every child node of a type gets, e.g. every DOC_REPO under the DOC_HUB root:
    AUDIT as AUDITOR. Applied to new children when created, and to existing ones when added."""

    __tablename__ = "default_grant"
    __table_args__ = (
        UniqueConstraint("parent_node_id", "child_node_type", "team_group_id", "role_id",
                         name="uq_default_grant_parent_node_id_child_node_type_team_group_id_role_id"),
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="ck_default_grant_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    parent_node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hierarchy_node.id"))
    child_node_type: Mapped[str] = mapped_column(String(32))
    team_group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_group.id"))
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("role.id"))
    status: Mapped[str] = mapped_column(String(16), default=Status.ACTIVE.value)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    team: Mapped[UserGroup] = relationship()
    role: Mapped[Role] = relationship()
