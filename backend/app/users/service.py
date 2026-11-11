"""Users, departments and roles.

Who may do what (enforced by the endpoint decorators in authorization.py):
    SYSTEM_ADMIN       creates, updates and deletes departments; creates, updates and deletes users
                       and all their roles (system roles, and any org unit role in any department)
    DEPARTMENT_ADMIN   sets MAKER, CHECKER and VIEWER in their own department(s)
    PUBLIC             given to everyone at first sign-in (hooks.record_sign_in)
    SYSTEM_ADMIN       seeded at start-up for settings.bootstrap_system_admins, when nobody holds it

Rules: MAKER and CHECKER can't both be held in the same department; VIEWER is never implied;
nobody can remove their own SYSTEM_ADMIN role or delete themselves.

Roles travel in the access token as two claims (see roles_claims), a snapshot taken at
sign-in. Granting or revoking a role ends the person's sessions, so their next token is current.

Authorization happens at the endpoint, from the caller's token: @SystemRole for system admin
actions, @OrgUnitRoles("DEPARTMENT_ADMIN", department=...) for department admin actions.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth.identity import Principal
from app.auth.service import revoke_sessions
from app.core.errors import Conflict, InvalidRequest, NotFound
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


# For functions whose `system_roles` / `org_unit_roles` parameters hide the lookups above.
_held_system_roles = system_roles
_held_org_unit_roles = org_unit_roles


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
#
# Authorization for the functions in this section is the endpoint's job: they are only called
# from endpoints guarded by @SystemRole("SYSTEM_ADMIN") (see router.py).


def _department_fields(code: str, name: str) -> tuple[str, str]:
    code, name = code.strip().upper(), name.strip()
    if not code or not name:
        raise InvalidRequest("Enter a department code and name.")
    return code, name


def create_department(db: Session, actor_lan_id: str, code: str, name: str) -> Department:
    """Create a department. Code is stored upper-case, e.g. "RISK". Callers must be system admins."""
    actor = _require_user(db, actor_lan_id)
    code, name = _department_fields(code, name)
    if get_department(db, code) is not None:
        raise Conflict(f"Department {code} already exists.")
    department = Department(code=code, name=name, created_by_id=actor.id)
    db.add(department)
    db.commit()
    return department


def update_department(db: Session, code: str, new_code: str, name: str) -> Department:
    """Replace the department's code and name. Callers must be system admins.

    Tokens name departments by code, so a code change ends the sessions of everyone holding a
    role there; their roles stay and show the new code at their next sign-in.
    """
    department = _require_department(db, code)
    new_code, name = _department_fields(new_code, name)
    department.name = name
    if new_code != department.code:
        if get_department(db, new_code) is not None:
            raise Conflict(f"Department {new_code} already exists.")
        department.code = new_code
        for lan_id in _role_holders(db, department):
            revoke_sessions(db, lan_id, reason="roles_changed")
    db.commit()
    return department


def delete_department(db: Session, code: str) -> None:
    """Delete the department and every role held in it. Callers must be system admins.

    Everyone who held a role there has their sessions ended (their token names the department).
    """
    department = _require_department(db, code)
    holders = _role_holders(db, department)
    db.execute(delete(UserOrgUnitRole).where(UserOrgUnitRole.department_id == department.id))
    db.delete(department)
    for lan_id in holders:
        revoke_sessions(db, lan_id, reason="roles_changed")
    db.commit()


# --------------------------------------------------------------------------- users
#
# upsert_user / delete_user are called from endpoints guarded by @SystemRole("SYSTEM_ADMIN");
# set_department_roles from endpoints guarded by @OrgUnitRoles("DEPARTMENT_ADMIN", department=...).
# Authorization is the endpoint's job; these enforce the rules about the roles themselves.


@dataclass(frozen=True)
class UserResult:
    user: User
    created: bool


def user_roles(db: Session, user: User) -> dict[str, Any]:
    """The user's roles in the token's shape (see roles_claims)."""
    return roles_claims(db, user)


def upsert_user(
    db: Session,
    actor_lan_id: str,
    lan_id: str,
    *,
    display_name: str,
    email: str,
    department: str = "",
    title: str = "",
    system_roles: list[str],
    org_unit_roles: Mapping[str, list[str]],
) -> UserResult:
    """Create or update a user, and set all their roles.

    `system_roles` (e.g. ["PUBLIC"]) and `org_unit_roles` (e.g. {"RISK": ["CHECKER", "VIEWER"]})
    are complete, in the token's shape: roles not in them are removed, and a department left out
    loses all the user's roles there. A new user always gets PUBLIC, listed or not (as people who
    first sign in do); on later updates PUBLIC is like any other role. The profile fields are
    refreshed from the directory whenever the user signs in. Validated before anything changes.
    """
    actor = _require_user(db, actor_lan_id)
    lan_id, email = lan_id.strip().lower(), email.strip().lower()
    if not lan_id or not display_name.strip() or not email:
        raise InvalidRequest("Enter a LAN ID, display name and email.")
    wanted_system = _parse_roles(system_roles, RoleScope.SYSTEM)
    wanted_org = _parse_org_unit_roles(db, org_unit_roles)  # department -> roles, validated
    if lan_id == actor.lan_id and RoleCode.SYSTEM_ADMIN not in wanted_system:
        raise Conflict("You can't remove your own SYSTEM_ADMIN role.")

    user = get_by_lan_id(db, lan_id)
    other = db.scalar(select(User).where(User.email == email, User.lan_id != lan_id))
    if other is not None:
        raise Conflict(f"{email} is already the email of {other.lan_id}.")
    created = user is None
    if user is None:
        user = User(lan_id=lan_id)
        db.add(user)
        wanted_system.add(RoleCode.PUBLIC)  # everyone starts with PUBLIC, as at a first sign-in
    user.display_name, user.email = display_name.strip(), email
    user.department, user.title = department.strip(), title.strip()
    db.flush()

    current_system = _held_system_roles(db, user)
    for role in sorted(wanted_system - current_system):
        db.add(UserSystemRole(user_id=user.id, role_code=role.value, granted_by_id=actor.id))
    for role in sorted(current_system - wanted_system):
        db.delete(db.get(UserSystemRole, (user.id, role.value)))
    if wanted_system != current_system and not created:
        revoke_sessions(db, user.lan_id, reason="roles_changed")

    departments = {d.code: d for d in wanted_org}
    wanted_pairs = {(d.code, r) for d, roles in wanted_org.items() for r in roles}
    current_pairs = {(code, r) for code, roles in _held_org_unit_roles(db, user).items() for r in roles}
    for code, role in sorted(current_pairs - wanted_pairs):
        _revoke(db, user, departments.get(code) or _require_department(db, code), role)
    db.flush()  # so swaps such as MAKER -> CHECKER don't trip the exclusivity check
    for code, role in sorted(wanted_pairs - current_pairs):
        _grant(db, actor, user, departments[code], role)
    db.commit()
    return UserResult(user, created)


def delete_user(db: Session, actor_lan_id: str, lan_id: str) -> None:
    """Delete the user and all their roles, and end their sessions.

    They can still sign in through the directory afterwards; they come back as a new user with
    PUBLIC only. Blocking someone altogether is deactivation (not built yet).
    """
    actor = _require_user(db, actor_lan_id)
    user = _require_user(db, lan_id)
    if user.id == actor.id:
        raise Conflict("You can't delete yourself.")
    revoke_sessions(db, user.lan_id, reason="user_deleted")
    db.delete(user)
    db.commit()


def set_department_roles(db: Session, actor_lan_id: str, lan_id: str, department_code: str, roles: list[str]) -> User:
    """Make the user's MAKER, CHECKER and VIEWER roles in the department exactly `roles`.

    [] removes them all. DEPARTMENT_ADMIN is left alone (system admins set it). MAKER and CHECKER
    can't be held together in one department.
    """
    wanted = _parse_roles(roles, RoleScope.ORG_UNIT)
    not_allowed = wanted - GRANTABLE_BY_DEPARTMENT_ADMIN
    if not_allowed:
        raise InvalidRequest(
            f"Roles here are {', '.join(sorted(r.value for r in GRANTABLE_BY_DEPARTMENT_ADMIN))}; "
            f"{', '.join(sorted(r.value for r in not_allowed))} is set by a system admin."
        )
    if {RoleCode.MAKER, RoleCode.CHECKER} <= wanted:
        raise Conflict("One person can't be both maker and checker in a department.")
    actor = _require_user(db, actor_lan_id)
    department = _require_department(db, department_code)
    user = _require_user(db, lan_id)

    current = org_unit_roles(db, user).get(department.code, set()) & GRANTABLE_BY_DEPARTMENT_ADMIN
    for role in sorted(current - wanted):
        _revoke(db, user, department, role)
    db.flush()  # so a MAKER -> CHECKER swap doesn't trip the exclusivity check
    for role in sorted(wanted - current):
        _grant(db, actor, user, department, role)
    db.commit()
    return user


# --------------------------------------------------------------------------- shared


def _grant(db: Session, actor: User, user: User, department: Department, role: RoleCode) -> UserOrgUnitRole:
    """Add the assignment and end the person's sessions (their token's roles are now stale).
    The caller commits."""
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
    return assignment


def _revoke(db: Session, user: User, department: Department, role: RoleCode) -> bool:
    """Remove the assignment and end the person's sessions. The caller commits."""
    assignment = db.get(UserOrgUnitRole, (user.id, department.id, role.value))
    if assignment is None:
        return False
    db.delete(assignment)
    revoke_sessions(db, user.lan_id, reason="roles_changed")
    return True


def _parse_roles(names: list[str], scope: RoleScope) -> set[RoleCode]:
    """Role names from a request -> RoleCodes, all of the given scope (InvalidRequest otherwise)."""
    roles = set()
    for name in names:
        try:
            role = RoleCode(name.strip().upper())
        except ValueError:
            raise InvalidRequest(f"Unknown role {name!r}.") from None
        _require_scope(role, scope)
        roles.add(role)
    return roles


def _parse_org_unit_roles(db: Session, requested: Mapping[str, list[str]]) -> dict[Department, set[RoleCode]]:
    """{"RISK": ["CHECKER"]} from a request -> {Department: {RoleCode}}, validated:
    every department exists (NotFound), every role is an org unit role (InvalidRequest), and
    MAKER and CHECKER aren't asked for together in one department (Conflict)."""
    by_code: dict[str, set[RoleCode]] = {}
    for code, roles in requested.items():
        by_code.setdefault(code.strip().upper(), set()).update(_parse_roles(roles, RoleScope.ORG_UNIT))
    departments = {code: get_department(db, code) for code in by_code}
    missing = sorted(code for code, d in departments.items() if d is None)
    if missing:
        raise NotFound(f"No department {', '.join(missing)}.")
    for code, roles in by_code.items():
        if {RoleCode.MAKER, RoleCode.CHECKER} <= roles:
            raise Conflict(f"One person can't be both maker and checker in a department ({code}).")
    return {departments[code]: roles for code, roles in by_code.items() if roles}


def _require_scope(role: RoleCode, scope: RoleScope) -> None:
    if ROLE_DEFINITIONS[role][0] is not scope:
        raise InvalidRequest(f"{role.value} is not a {scope.value.replace('_', ' ')} role.")


def _role_holders(db: Session, department: Department) -> set[str]:
    """LAN IDs of everyone holding any role in the department."""
    return set(db.scalars(
        select(User.lan_id)
        .join(UserOrgUnitRole, UserOrgUnitRole.user_id == User.id)
        .where(UserOrgUnitRole.department_id == department.id)
    ))


def _require_user(db: Session, lan_id: str) -> User:
    user = get_by_lan_id(db, lan_id)
    if user is None:
        raise NotFound(f"No user with LAN ID {lan_id.strip().lower()!r}. "
                       f"They get one when they first sign in, or a system admin can add them.")
    return user


def _require_department(db: Session, code: str) -> Department:
    department = get_department(db, code)
    if department is None:
        raise NotFound(f"No department {code.strip().upper()!r}.")
    return department
