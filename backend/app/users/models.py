"""Users, departments (org units) and roles.

A users row is created the first time someone signs in and refreshed from the directory every
time after (see app.users.hooks.record_sign_in). No passwords are stored.

Roles come in two scopes, enforced by the tables themselves:
    system     not tied to a department      user_system_roles     (SYSTEM_ADMIN, PUBLIC)
    org_unit   held in one department        user_org_unit_roles   (DEPARTMENT_ADMIN, MAKER, CHECKER, VIEWER)

Each assignment table carries a constant `scope` column and a composite foreign key to
roles(code, scope), so a system role can't be stored as an org unit role or the other way round.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime, utcnow


class RoleScope(StrEnum):
    SYSTEM = "system"
    ORG_UNIT = "org_unit"


class RoleCode(StrEnum):
    # system roles
    SYSTEM_ADMIN = "SYSTEM_ADMIN"
    PUBLIC = "PUBLIC"  # every signed-in user; given at first sign-in
    # org unit roles
    DEPARTMENT_ADMIN = "DEPARTMENT_ADMIN"
    MAKER = "MAKER"
    CHECKER = "CHECKER"
    VIEWER = "VIEWER"


# code -> (scope, display name, description). Synced into the roles table at start-up.
ROLE_DEFINITIONS: dict[RoleCode, tuple[RoleScope, str, str]] = {
    RoleCode.SYSTEM_ADMIN: (
        RoleScope.SYSTEM, "System admin", "Manages departments, users and every role in any department.",
    ),
    RoleCode.PUBLIC: (RoleScope.SYSTEM, "Public", "Every signed-in user. Sees what is open to everyone."),
    RoleCode.DEPARTMENT_ADMIN: (
        RoleScope.ORG_UNIT, "Department admin", "Gives makers, checkers and viewers access to the department.",
    ),
    RoleCode.MAKER: (RoleScope.ORG_UNIT, "Maker", "Submits items for the department."),
    RoleCode.CHECKER: (RoleScope.ORG_UNIT, "Checker", "Approves or rejects what makers submit."),
    RoleCode.VIEWER: (RoleScope.ORG_UNIT, "Viewer", "Sees the department's approved items."),
}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    lan_id: Mapped[str] = mapped_column(String(64), unique=True)  # stored lower-case
    # Copied from the directory at every sign-in (the directory is the source of truth).
    display_name: Mapped[str] = mapped_column(String(128))
    email: Mapped[str] = mapped_column(String(256), unique=True)
    department: Mapped[str] = mapped_column(String(128), default="")  # directory text, not an org unit
    title: Mapped[str] = mapped_column(String(128), default="")
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    system_roles: Mapped[list["UserSystemRole"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", foreign_keys="UserSystemRole.user_id"
    )
    org_unit_roles: Mapped[list["UserOrgUnitRole"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", foreign_keys="UserOrgUnitRole.user_id"
    )


class Department(Base):
    """An org unit. Its code is the key in the token's org_unit_roles claim, e.g. "RISK"."""

    __tablename__ = "departments"
    __table_args__ = (CheckConstraint("code = upper(code) AND length(code) > 0", name="ck_departments_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Role(Base):
    """Reference table of the roles above (ROLE_DEFINITIONS is the source)."""

    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("code", "scope", name="uq_roles_code_scope"),  # target of the composite FKs
        CheckConstraint("scope IN ('system', 'org_unit')", name="ck_roles_scope"),
    )

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    scope: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(256), default="")


class UserSystemRole(Base):
    """A system role held by a user."""

    __tablename__ = "user_system_roles"
    __table_args__ = (
        ForeignKeyConstraint(["role_code", "scope"], ["roles.code", "roles.scope"]),
        CheckConstraint("scope = 'system'", name="ck_user_system_roles_scope"),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    scope: Mapped[str] = mapped_column(String(16), default=RoleScope.SYSTEM.value)
    granted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))  # NULL = system
    granted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    user: Mapped[User] = relationship(back_populates="system_roles", foreign_keys=[user_id])


class UserOrgUnitRole(Base):
    """An org unit role held by a user in one department."""

    __tablename__ = "user_org_unit_roles"
    __table_args__ = (
        ForeignKeyConstraint(["role_code", "scope"], ["roles.code", "roles.scope"]),
        CheckConstraint("scope = 'org_unit'", name="ck_user_org_unit_roles_scope"),
        Index("ix_user_org_unit_roles_department", "department_id", "role_code"),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="CASCADE"), primary_key=True)
    role_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    scope: Mapped[str] = mapped_column(String(16), default=RoleScope.ORG_UNIT.value)
    granted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    granted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    user: Mapped[User] = relationship(back_populates="org_unit_roles", foreign_keys=[user_id])
    department: Mapped[Department] = relationship()
