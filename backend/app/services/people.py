"""Adding users and departments.

- System admins add users to any department; every user they add is a department admin.
- Department admins add users to their own department as viewer, maker or checker.
- Only system admins create departments.
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.permissions import Perm, RoleCode
from app.core.security import hash_password
from app.db.models import Department, Role, User, UserRole
from app.services import audit
from app.services.auth import Principal
from app.services.errors import Conflict, Forbidden, InvalidRequest

LAN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DEPT_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,15}$")
MIN_PASSWORD_LENGTH = 8

DEPARTMENT_ADMIN_CAN_ADD = {RoleCode.VIEWER, RoleCode.MAKER, RoleCode.CHECKER}


def create_user(
    db: Session,
    actor: Principal,
    *,
    lan_id: str,
    display_name: str,
    email: str,
    title: str,
    password: str,
    department_code: str | None,
    role: str | None,
) -> User:
    if not actor.has(Perm.USERS_CREATE):
        raise Forbidden("You can't add users.")

    # Who may add whom, and where
    if actor.has_role(RoleCode.SYSTEM_ADMIN):
        if not department_code:
            raise InvalidRequest("Choose a department.")
        if role not in (None, RoleCode.DEPARTMENT_ADMIN.value):
            raise InvalidRequest("Users added by a system admin are department admins.")
        new_role: RoleCode | None = RoleCode.DEPARTMENT_ADMIN
        dept = db.scalar(select(Department).where(Department.code == department_code.strip().upper()))
        if dept is None:
            raise InvalidRequest(f"Department '{department_code}' not found.")
    else:  # department admin
        if actor.department is None:
            raise Forbidden("You can't add users.")
        if department_code and department_code.strip().upper() != actor.department.code:
            raise Forbidden("You can only add users to your own department.")
        try:
            chosen = RoleCode(role or RoleCode.VIEWER.value)
        except ValueError:
            raise InvalidRequest(f"Unknown role '{role}'.") from None
        if chosen not in DEPARTMENT_ADMIN_CAN_ADD:
            raise Forbidden("Department admins can add viewers, makers and checkers only.")
        new_role = None if chosen is RoleCode.VIEWER else chosen  # viewer is implicit
        dept = db.get(Department, actor.department.id)

    # Field rules
    lan_id = lan_id.strip().lower()
    email = email.strip().lower()
    if not LAN_ID_RE.match(lan_id):
        raise InvalidRequest("LAN ID must be 2–64 characters: letters, numbers, dots, dashes or underscores.")
    if not display_name.strip():
        raise InvalidRequest("Name is required.")
    if not EMAIL_RE.match(email):
        raise InvalidRequest("Enter a valid email address.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise InvalidRequest(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if db.scalar(select(User.id).where(User.lan_id == lan_id)):
        raise Conflict(f"LAN ID '{lan_id}' is already in use.")
    if db.scalar(select(User.id).where(User.email == email)):
        raise Conflict(f"Email '{email}' is already in use.")

    user = User(
        lan_id=lan_id,
        display_name=display_name.strip(),
        title=title.strip(),
        email=email,
        password_hash=hash_password(password),
        department_id=dept.id,
    )
    if new_role:
        role_row = db.scalar(select(Role).where(Role.code == new_role.value))
        user.role_links = [UserRole(role=role_row, assigned_by_id=actor.user_id)]
    db.add(user)
    db.flush()
    audit.record(db, "user.create", actor_id=actor.user_id, actor_lan_id=actor.lan_id, target_type="user",
                 target_id=lan_id, detail={"department": dept.code, "role": (new_role or RoleCode.VIEWER).value})
    db.commit()
    return db.scalar(
        select(User)
        .where(User.id == user.id)
        .options(selectinload(User.department), selectinload(User.role_links).selectinload(UserRole.role))
    )


def create_department(db: Session, actor: Principal, code: str, name: str) -> Department:
    if not actor.has(Perm.DEPARTMENTS_MANAGE):
        raise Forbidden("Only system admins can create departments.")
    code = code.strip().upper()
    name = name.strip()
    if not DEPT_CODE_RE.match(code):
        raise InvalidRequest("Code must be 2–16 characters: letters, numbers or underscores, starting with a letter.")
    if not name:
        raise InvalidRequest("Name is required.")
    if db.scalar(select(Department.id).where(Department.code == code)):
        raise Conflict(f"Department code '{code}' is already in use.")
    if db.scalar(select(Department.id).where(Department.name == name)):
        raise Conflict(f"A department named '{name}' already exists.")
    dept = Department(code=code, name=name)
    db.add(dept)
    db.flush()
    audit.record(db, "department.create", actor_id=actor.user_id, actor_lan_id=actor.lan_id,
                 target_type="department", target_id=code, detail={"name": name})
    db.commit()
    return dept
