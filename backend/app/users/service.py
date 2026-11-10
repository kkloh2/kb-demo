"""Users, departments and roles.

Who may grant what:
    SYSTEM_ADMIN       creates departments; grants and revokes DEPARTMENT_ADMIN in any department
    DEPARTMENT_ADMIN   grants and revokes MAKER, CHECKER and VIEWER in their own department(s)
    PUBLIC             given to everyone at first sign-in (hooks.record_sign_in)
    SYSTEM_ADMIN       given at sign-in to the LAN IDs in settings.bootstrap_system_admins

Rules: roles go only to people who have signed in at least once (they have a users row);
MAKER and CHECKER can't both be held in the same department; VIEWER is never implied.

Roles travel in the access token as two claims (see roles_claims), a snapshot taken at
sign-in. Granting or revoking a role ends the person's sessions, so their next token is current.
The grantor's own rights are always checked against the database, not their token.
"""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.identity import Principal
from app.auth.service import revoke_sessions
from app.core.errors import Conflict, Forbidden, InvalidRequest, NotFound
from app.users.models import (
    ROLE_DEFINITIONS,
    Department,
    Role,
    RoleCode,
    RoleScope,
    User,
    UserOrgUnitRole,
    UserSystemRole,
)

SYSTEM_ROLES_CLAIM = "system_roles"
ORG_UNIT_ROLES_CLAIM = "org_unit_roles"

GRANTABLE_BY_DEPARTMENT_ADMIN = frozenset({RoleCode.MAKER, RoleCode.CHECKER, RoleCode.VIEWER})
MUTUALLY_EXCLUSIVE = {RoleCode.MAKER: RoleCode.CHECKER, RoleCode.CHECKER: RoleCode.MAKER}


# --------------------------------------------------------------------------- reference data


def sync_roles(db: Session) -> None:
    """Make the roles table match ROLE_DEFINITIONS. Runs at start-up; the caller commits."""
    existing = {r.code: r for r in db.scalars(select(Role))}
    for code, (scope, name, description) in ROLE_DEFINITIONS.items():
        role = existing.get(code) or Role(code=code.value)
        role.scope, role.name, role.description = scope.value, name, description
        db.add(role)


# --------------------------------------------------------------------------- lookups


def get_by_lan_id(db: Session, lan_id: str) -> User | None:
    return db.scalar(select(User).where(User.lan_id == lan_id.strip().lower()))


def get_department(db: Session, code: str) -> Department | None:
    return db.scalar(select(Department).where(Department.code == code.strip().upper()))


def system_roles(db: Session, user: User) -> set[RoleCode]:
    return {RoleCode(r) for r in db.scalars(select(UserSystemRole.role_code).where(UserSystemRole.user_id == user.id))}


def org_unit_roles(db: Session, user: User) -> dict[str, set[RoleCode]]:
    """Department code -> roles held there."""
    rows = db.execute(
        select(Department.code, UserOrgUnitRole.role_code)
        .join(Department, Department.id == UserOrgUnitRole.department_id)
        .where(UserOrgUnitRole.user_id == user.id)
    )
    held: dict[str, set[RoleCode]] = {}
    for code, role in rows:
        held.setdefault(code, set()).add(RoleCode(role))
    return held


# --------------------------------------------------------------------------- token claims


def roles_claims(db: Session, user: User | None) -> dict[str, Any]:
    """{"system_roles": [...], "org_unit_roles": {"RISK": [...], ...}}, sorted, for the token."""
    if user is None:
        return {SYSTEM_ROLES_CLAIM: [], ORG_UNIT_ROLES_CLAIM: {}}
    return {
        SYSTEM_ROLES_CLAIM: sorted(r.value for r in system_roles(db, user)),
        ORG_UNIT_ROLES_CLAIM: {
            code: sorted(r.value for r in roles) for code, roles in sorted(org_unit_roles(db, user).items())
        },
    }


def system_roles_of(principal: Principal) -> frozenset[str]:
    """The signed-in caller's system roles, from their token."""
    roles = principal.claims.get(SYSTEM_ROLES_CLAIM, [])
    return frozenset(r for r in roles if isinstance(r, str)) if isinstance(roles, list) else frozenset()


def org_unit_roles_of(principal: Principal) -> dict[str, frozenset[str]]:
    """The signed-in caller's org unit roles (department code -> roles), from their token."""
    claim = principal.claims.get(ORG_UNIT_ROLES_CLAIM, {})
    if not isinstance(claim, Mapping):
        return {}
    return {
        str(code): frozenset(r for r in roles if isinstance(r, str))
        for code, roles in claim.items()
        if isinstance(roles, list)
    }


def has_system_role(principal: Principal, role: RoleCode) -> bool:
    return role.value in system_roles_of(principal)


def has_org_unit_role(principal: Principal, department_code: str, role: RoleCode) -> bool:
    return role.value in org_unit_roles_of(principal).get(department_code.strip().upper(), frozenset())


# --------------------------------------------------------------------------- system roles


def ensure_system_role(db: Session, user: User, role: RoleCode, granted_by: User | None = None) -> bool:
    """Give a system role if not held. Returns True when added. The caller commits."""
    _require_scope(role, RoleScope.SYSTEM)
    if db.get(UserSystemRole, (user.id, role.value)) is not None:
        return False
    db.add(UserSystemRole(user_id=user.id, role_code=role.value, granted_by_id=granted_by.id if granted_by else None))
    return True


# --------------------------------------------------------------------------- departments


def create_department(db: Session, actor_lan_id: str, code: str, name: str) -> Department:
    """System admins only. Code is stored upper-case, e.g. "RISK"."""
    actor = _require_system_admin(db, actor_lan_id)
    code, name = code.strip().upper(), name.strip()
    if not code or not name:
        raise InvalidRequest("Enter a department code and name.")
    if get_department(db, code) is not None:
        raise Conflict(f"Department {code} already exists.")
    department = Department(code=code, name=name, created_by_id=actor.id)
    db.add(department)
    db.commit()
    return department


# --------------------------------------------------------------------------- org unit roles


def grant_org_unit_role(
    db: Session, actor_lan_id: str, lan_id: str, department_code: str, role: RoleCode
) -> UserOrgUnitRole:
    """Give `lan_id` the role in the department. Idempotent. Ends the person's sessions."""
    actor, user, department = _authorize_org_unit_change(db, actor_lan_id, lan_id, department_code, role)
    existing = db.get(UserOrgUnitRole, (user.id, department.id, role.value))
    if existing is not None:
        return existing
    other = MUTUALLY_EXCLUSIVE.get(role)
    if other and db.get(UserOrgUnitRole, (user.id, department.id, other.value)) is not None:
        raise Conflict(f"{user.display_name} is a {other.value.lower()} in {department.code}; "
                       f"one person can't be both maker and checker in a department.")
    assignment = UserOrgUnitRole(user_id=user.id, department_id=department.id, role_code=role.value,
                                 granted_by_id=actor.id)
    db.add(assignment)
    revoke_sessions(db, user.lan_id, reason="roles_changed")
    db.commit()
    return assignment


def revoke_org_unit_role(db: Session, actor_lan_id: str, lan_id: str, department_code: str, role: RoleCode) -> bool:
    """Take the role away. Returns False when it wasn't held. Ends the person's sessions."""
    _, user, department = _authorize_org_unit_change(db, actor_lan_id, lan_id, department_code, role)
    assignment = db.get(UserOrgUnitRole, (user.id, department.id, role.value))
    if assignment is None:
        return False
    db.delete(assignment)
    revoke_sessions(db, user.lan_id, reason="roles_changed")
    db.commit()
    return True


# --------------------------------------------------------------------------- authorization helpers


def _require_scope(role: RoleCode, scope: RoleScope) -> None:
    if ROLE_DEFINITIONS[role][0] is not scope:
        raise InvalidRequest(f"{role.value} is not a {scope.value.replace('_', ' ')} role.")


def _require_user(db: Session, lan_id: str) -> User:
    user = get_by_lan_id(db, lan_id)
    if user is None:
        raise NotFound(f"No user with LAN ID {lan_id.strip().lower()!r}. They need to sign in to Data Hub once first.")
    return user


def _require_system_admin(db: Session, actor_lan_id: str) -> User:
    actor = _require_user(db, actor_lan_id)
    if RoleCode.SYSTEM_ADMIN not in system_roles(db, actor):
        raise Forbidden("Only system admins can do this.")
    return actor


def _authorize_org_unit_change(
    db: Session, actor_lan_id: str, lan_id: str, department_code: str, role: RoleCode
) -> tuple[User, User, Department]:
    _require_scope(role, RoleScope.ORG_UNIT)
    actor = _require_user(db, actor_lan_id)
    department = get_department(db, department_code)
    if department is None:
        raise NotFound(f"No department {department_code.strip().upper()!r}.")
    if role is RoleCode.DEPARTMENT_ADMIN:
        if RoleCode.SYSTEM_ADMIN not in system_roles(db, actor):
            raise Forbidden("Only system admins can manage department admins.")
    elif RoleCode.DEPARTMENT_ADMIN not in org_unit_roles(db, actor).get(department.code, set()):
        raise Forbidden(f"Only department admins of {department.code} can manage its makers, checkers and viewers.")
    return actor, _require_user(db, lan_id), department
