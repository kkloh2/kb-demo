"""Sign-in, sessions and the access token.

Token claims (besides the standard iss/aud/iat/exp):
    sub    LAN ID
    uid    user id
    jti    session id (row in auth_sessions; revoked on sign-out or role change)
    name   display name
    dept   {"id", "code", "name"} of the home department, or null for system admins
    roles  effective role codes, e.g. ["checker", "viewer"]
    perms  permission codes granted by those roles, e.g. ["documents:approve", ...]
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import jwt
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.permissions import Perm, RoleCode, effective_roles
from app.core.security import burn_password_check, decode_token, encode_token, verify_password
from app.db.models import AuthSession, Permission, Role, User, UserRole, utcnow
from app.services import audit
from app.services.errors import AccountLocked, Unauthenticated

INVALID_CREDENTIALS = "Incorrect LAN ID or password."


@dataclass(frozen=True)
class DepartmentRef:
    id: int
    code: str
    name: str


@dataclass(frozen=True)
class Principal:
    """The signed-in user, as described by their access token."""

    user_id: int
    lan_id: str
    display_name: str
    department: DepartmentRef | None
    roles: frozenset[RoleCode]
    permissions: frozenset[Perm]
    session_id: str

    @property
    def department_id(self) -> int | None:
        return self.department.id if self.department else None

    def has(self, perm: Perm) -> bool:
        return perm in self.permissions

    def has_role(self, role: RoleCode) -> bool:
        return role in self.roles


@dataclass(frozen=True)
class LoginResult:
    token: str
    expires_in: int
    user: User
    roles: list[str]
    permissions: list[str]


# --------------------------------------------------------------------------- roles → permissions


def assigned_roles(user: User) -> set[RoleCode]:
    return {RoleCode(link.role.code) for link in user.role_links}


def resolve_access(db: Session, user: User) -> tuple[list[str], list[str]]:
    """Effective roles (assigned + implicit viewer) and their permissions, read from the DB."""
    roles = effective_roles(assigned_roles(user), user.department_id is not None)
    codes = sorted(r.value for r in roles)
    perms = db.scalars(
        select(Permission.code)
        .join(Role.permissions)
        .where(Role.code.in_(codes))
        .distinct()
        .order_by(Permission.code)
    ).all()
    return codes, list(perms)


# --------------------------------------------------------------------------- sign-in


def _load_user(db: Session, lan_id: str) -> User | None:
    return db.scalar(
        select(User)
        .where(User.lan_id == lan_id.strip().lower())
        .options(selectinload(User.role_links).selectinload(UserRole.role), selectinload(User.department))
    )


def authenticate(
    db: Session, lan_id: str, password: str, *, ip: str | None = None, user_agent: str | None = None
) -> LoginResult:
    s = get_settings()
    now = utcnow()
    user = _load_user(db, lan_id)
    attempted = lan_id.strip().lower()[:64]

    if user is None or not user.is_active:
        burn_password_check(password)  # same cost as a real check: no LAN ID enumeration by timing
        audit.record(db, "auth.login", outcome="failure", actor_lan_id=attempted, ip_address=ip,
                     detail={"reason": "unknown_user" if user is None else "inactive"})
        db.commit()
        raise Unauthenticated(INVALID_CREDENTIALS)

    if user.locked_until and user.locked_until > now:
        burn_password_check(password)
        audit.record(db, "auth.login", outcome="failure", actor_id=user.id, actor_lan_id=user.lan_id,
                     ip_address=ip, detail={"reason": "locked"})
        db.commit()
        raise AccountLocked(_locked_message(user.locked_until, now))

    if not verify_password(password, user.password_hash):
        user.failed_login_count += 1
        detail = {"reason": "bad_password", "failed_count": user.failed_login_count}
        locked = user.failed_login_count >= s.max_failed_logins
        if locked:
            user.locked_until = now + timedelta(minutes=s.lockout_minutes)
            user.failed_login_count = 0
        audit.record(db, "auth.login", outcome="failure", actor_id=user.id, actor_lan_id=user.lan_id,
                     ip_address=ip, detail=detail)
        if locked:
            audit.record(db, "auth.lockout", actor_id=user.id, actor_lan_id=user.lan_id, ip_address=ip,
                         detail={"minutes": s.lockout_minutes})
        db.commit()
        if locked:
            raise AccountLocked(_locked_message(user.locked_until, now))
        raise Unauthenticated(INVALID_CREDENTIALS)

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    roles, perms = resolve_access(db, user)
    expires_at = now + timedelta(minutes=s.access_token_minutes)
    session = AuthSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
        issued_at=now,
        expires_at=expires_at,
        ip_address=ip,
        user_agent=(user_agent or "")[:256] or None,
    )
    db.add(session)
    token = encode_token(
        {
            "sub": user.lan_id,
            "uid": user.id,
            "jti": session.id,
            "name": user.display_name,
            "dept": (
                {"id": user.department.id, "code": user.department.code, "name": user.department.name}
                if user.department
                else None
            ),
            "roles": roles,
            "perms": perms,
        },
        issued_at=now,
        expires_at=expires_at,
    )
    audit.record(db, "auth.login", actor_id=user.id, actor_lan_id=user.lan_id, ip_address=ip,
                 target_type="session", target_id=session.id)
    db.commit()
    return LoginResult(token, s.access_token_minutes * 60, user, roles, perms)


def _locked_message(until: datetime, now: datetime) -> str:
    minutes = max(1, -(-int((until - now).total_seconds()) // 60))  # round up
    return f"Too many failed attempts. Try again in {minutes} minute{'s' if minutes != 1 else ''}."


# --------------------------------------------------------------------------- token → principal


def principal_from_token(db: Session, token: str) -> Principal:
    """Verify the token and its session. Raises Unauthenticated on any problem."""
    try:
        claims = decode_token(token)
    except jwt.ExpiredSignatureError:
        raise Unauthenticated("Session expired. Please sign in again.") from None
    except jwt.PyJWTError:
        raise Unauthenticated("Invalid session. Please sign in again.") from None

    session = db.get(AuthSession, claims["jti"])
    if session is None or session.revoked_at is not None or session.expires_at <= utcnow():
        raise Unauthenticated("Session ended. Please sign in again.")
    user = db.get(User, claims["uid"])
    if user is None or not user.is_active or user.lan_id != claims["sub"]:
        raise Unauthenticated("Invalid session. Please sign in again.")

    dept = claims.get("dept")
    try:
        return Principal(
            user_id=user.id,
            lan_id=user.lan_id,
            display_name=claims.get("name", user.display_name),
            department=DepartmentRef(dept["id"], dept["code"], dept["name"]) if dept else None,
            roles=frozenset(RoleCode(r) for r in claims.get("roles", [])),
            permissions=frozenset(Perm(p) for p in claims.get("perms", []) if p in Perm._value2member_map_),
            session_id=session.id,
        )
    except (KeyError, ValueError):
        raise Unauthenticated("Invalid session. Please sign in again.") from None


# --------------------------------------------------------------------------- sign-out & revocation


def logout(db: Session, principal: Principal, *, ip: str | None = None) -> None:
    session = db.get(AuthSession, principal.session_id)
    if session and session.revoked_at is None:
        session.revoked_at = utcnow()
        session.revoked_reason = "logout"
    audit.record(db, "auth.logout", actor_id=principal.user_id, actor_lan_id=principal.lan_id,
                 ip_address=ip, target_type="session", target_id=principal.session_id)
    db.commit()


def revoke_user_sessions(db: Session, user_id: int, reason: str) -> int:
    """End every active session of a user, e.g. after their roles change (claims are now stale).

    Adds to the caller's transaction; the caller commits.
    """
    result = db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow(), revoked_reason=reason)
    )
    return result.rowcount or 0
