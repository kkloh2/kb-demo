"""Sign-in, sessions and the access token.

Token claims (besides the standard iss/aud/iat/exp):
    sub    LAN ID
    uid    user id
    jti    session id (row in auth_sessions; revoked on sign-out)
    name   display name

Roles and access are not decided yet, so the token says who the user is and nothing more.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.errors import AccountLocked, Unauthenticated
from app.auth.models import AuthSession, User
from app.auth.security import burn_password_check, decode_token, encode_token, verify_password
from app.core.config import get_settings
from app.db.base import utcnow

INVALID_CREDENTIALS = "Incorrect LAN ID or password."


@dataclass(frozen=True)
class Principal:
    """The signed-in user, as described by their access token."""

    user_id: int
    lan_id: str
    display_name: str
    session_id: str


@dataclass(frozen=True)
class LoginResult:
    token: str
    expires_in: int
    user: User


# --------------------------------------------------------------------------- sign-in


def authenticate(
    db: Session, lan_id: str, password: str, *, ip: str | None = None, user_agent: str | None = None
) -> LoginResult:
    s = get_settings()
    now = utcnow()
    user = db.scalar(select(User).where(User.lan_id == lan_id.strip().lower()))

    if user is None or not user.is_active:
        burn_password_check(password)  # same cost as a real check: no LAN ID enumeration by timing
        raise Unauthenticated(INVALID_CREDENTIALS)

    if user.locked_until and user.locked_until > now:
        burn_password_check(password)
        raise AccountLocked(_locked_message(user.locked_until, now))

    if not verify_password(password, user.password_hash):
        user.failed_login_count += 1
        locked = user.failed_login_count >= s.max_failed_logins
        if locked:
            user.locked_until = now + timedelta(minutes=s.lockout_minutes)
            user.failed_login_count = 0
        db.commit()
        if locked:
            raise AccountLocked(_locked_message(user.locked_until, now))
        raise Unauthenticated(INVALID_CREDENTIALS)

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
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
        {"sub": user.lan_id, "uid": user.id, "jti": session.id, "name": user.display_name},
        issued_at=now,
        expires_at=expires_at,
    )
    db.commit()
    return LoginResult(token, s.access_token_minutes * 60, user)


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
    user = db.get(User, claims.get("uid"))
    if user is None or not user.is_active or user.lan_id != claims["sub"]:
        raise Unauthenticated("Invalid session. Please sign in again.")

    return Principal(
        user_id=user.id,
        lan_id=user.lan_id,
        display_name=claims.get("name", user.display_name),
        session_id=session.id,
    )


# --------------------------------------------------------------------------- sign-out


def logout(db: Session, principal: Principal) -> None:
    session = db.get(AuthSession, principal.session_id)
    if session and session.revoked_at is None:
        session.revoked_at = utcnow()
        session.revoked_reason = "logout"
    db.commit()
