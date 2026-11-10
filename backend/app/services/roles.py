"""Assigning and removing roles.

Rules (see app.core.permissions):
- system admins manage department admins; department admins manage makers and checkers
  in their own department only
- department-scoped roles need a home department
- mutually exclusive roles can't be held together (maker/checker; department admin/maker;
  department admin/checker)
- a role change ends the user's sessions, because their token's roles are now out of date
"""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.permissions import MUTUALLY_EXCLUSIVE, ROLES, RoleCode
from app.db.models import Role, User, UserRole
from app.services import audit, authz
from app.services.auth import Principal, assigned_roles, revoke_user_sessions
from app.services.errors import Conflict, Forbidden, InvalidRequest, NotFound


def get_user(db: Session, lan_id: str) -> User:
    user = db.scalar(
        select(User)
        .where(User.lan_id == lan_id.strip().lower())
        .options(selectinload(User.role_links).selectinload(UserRole.role), selectinload(User.department))
    )
    if user is None:
        raise NotFound(f"User '{lan_id}' not found.")
    return user


def _parse_role(code: str) -> RoleCode:
    try:
        role = RoleCode(code)
    except ValueError:
        raise NotFound(f"Role '{code}' not found.") from None
    if not ROLES[role].assignable:
        raise InvalidRequest(f"The {ROLES[role].name.lower()} role can't be assigned.")
    return role


def assign_role(db: Session, actor: Principal, lan_id: str, role_code: str) -> User:
    target = get_user(db, lan_id)
    grant_role(db, actor, target, _parse_role(role_code))
    db.commit()
    return target


def grant_role(db: Session, actor: Principal, target: User, role: RoleCode) -> bool:
    """Assign a role within the caller's transaction (no commit). Returns False if already held."""
    if not authz.can_manage_role(actor, target, role):
        raise Forbidden(f"You can't assign the {ROLES[role].name.lower()} role to this user.")

    current = assigned_roles(target)
    if role in current:
        return False
    if RoleCode.SYSTEM_ADMIN in current:
        raise Conflict("System admins can't hold department roles.")
    if target.department_id is None:
        raise Conflict("This user has no home department.")
    for pair in MUTUALLY_EXCLUSIVE:
        if role in pair and (pair - {role}) & current:
            other = next(iter(pair - {role}))
            raise Conflict(
                f"{target.display_name} is already a {ROLES[other].name.lower()}; "
                f"a user can't be both {ROLES[role].name.lower()} and {ROLES[other].name.lower()}."
            )

    role_row = db.scalar(select(Role).where(Role.code == role.value))
    target.role_links.append(UserRole(role=role_row, assigned_by_id=actor.user_id))
    revoke_user_sessions(db, target.id, "roles_changed")
    audit.record(db, "role.assign", actor_id=actor.user_id, actor_lan_id=actor.lan_id,
                 target_type="user", target_id=target.lan_id, detail={"role": role.value})
    return True


def revoke_role(db: Session, actor: Principal, lan_id: str, role_code: str) -> User:
    role = _parse_role(role_code)
    target = get_user(db, lan_id)
    if not authz.can_manage_role(actor, target, role):
        raise Forbidden(f"You can't remove the {ROLES[role].name.lower()} role from this user.")
    link = next((link for link in target.role_links if link.role.code == role.value), None)
    if link is None:
        return target
    if target.id == actor.user_id:
        raise Conflict("You can't remove your own role.")
    target.role_links.remove(link)
    revoke_user_sessions(db, target.id, "roles_changed")
    audit.record(db, "role.revoke", actor_id=actor.user_id, actor_lan_id=actor.lan_id,
                 target_type="user", target_id=target.lan_id, detail={"role": role.value})
    db.commit()
    return target
