"""Sign-in, sessions and the access token.

Token claims (besides the standard iss/aud/iat/exp):
    sub         LAN ID
    jti         session id (row in auth_sessions; revoked on sign-out)
    name        display name   \
    email       email           | from the directory at sign-in
    department  department      |
    title       job title      /
    ...         any claims added by sign-in hooks (e.g. "roles" from app.users)

Auth knows nothing about Data Hub's own user records, roles or access: other modules take part
in sign-in through app.auth.hooks and look people up by LAN ID (Principal.lan_id).
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from types import MappingProxyType

import jwt
from sqlalchemy.orm import Session

from app.auth import hooks, ldap
from app.auth.errors import Unauthenticated
from app.auth.identity import Identity, Principal
from app.auth.models import AuthSession
from app.auth.security import decode_token, encode_token
from app.core.config import get_settings
from app.db.base import utcnow

INVALID_CREDENTIALS = "Incorrect LAN ID or password."


@dataclass(frozen=True)
class LoginResult:
    token: str
    expires_in: int
    identity: Identity


# --------------------------------------------------------------------------- sign-in


def authenticate(
    db: Session, lan_id: str, password: str, *, ip: str | None = None, user_agent: str | None = None
) -> LoginResult:
    """Check the LAN ID and password with the directory, then start a session.

    The directory (app.auth.ldap) decides whether the password is right, enforces password and
    lockout policy, and supplies the person's details. Sign-in hooks (app.auth.hooks) then let
    other modules record the sign-in or refuse it.
    """
    s = get_settings()
    lan_id = lan_id.strip().lower()

    entry = ldap.authenticate(lan_id, password)  # DirectoryUnavailable (503) passes through
    if entry is None:  # wrong password, unknown LAN ID, or locked/disabled in the directory
        raise Unauthenticated(INVALID_CREDENTIALS)
    identity = Identity(
        lan_id=lan_id,
        display_name=entry.display_name,
        email=entry.email,
        department=entry.department,
        title=entry.title,
    )
    extra_claims = hooks.run_sign_in_hooks(db, identity)

    now = utcnow()
    expires_at = now + timedelta(minutes=s.access_token_minutes)
    session = AuthSession(
        id=str(uuid.uuid4()),
        lan_id=lan_id,
        issued_at=now,
        expires_at=expires_at,
        ip_address=ip,
        user_agent=(user_agent or "")[:256] or None,
    )
    db.add(session)
    token = encode_token(
        {
            **extra_claims,
            "sub": lan_id,
            "jti": session.id,
            "name": identity.display_name,
            "email": identity.email,
            "department": identity.department,
            "title": identity.title,
        },
        issued_at=now,
        expires_at=expires_at,
    )
    db.commit()
    return LoginResult(token, s.access_token_minutes * 60, identity)


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
    if session.lan_id != claims["sub"]:
        raise Unauthenticated("Invalid session. Please sign in again.")

    return Principal(
        lan_id=session.lan_id,
        display_name=str(claims.get("name", "")),
        email=str(claims.get("email", "")),
        department=str(claims.get("department", "")),
        title=str(claims.get("title", "")),
        session_id=session.id,
        claims=MappingProxyType({k: v for k, v in claims.items() if k not in hooks.RESERVED_CLAIMS}),
    )


# --------------------------------------------------------------------------- sign-out


def logout(db: Session, principal: Principal) -> None:
    session = db.get(AuthSession, principal.session_id)
    if session and session.revoked_at is None:
        session.revoked_at = utcnow()
        session.revoked_reason = "logout"
    db.commit()
