"""Password hashing (stdlib PBKDF2) and JWT encoding/decoding (PyJWT)."""

import hashlib
import hmac
import secrets
from datetime import datetime
from functools import lru_cache
from typing import Any

import jwt

from app.core.config import get_settings

_ALGO = "pbkdf2_sha256"


def hash_password(password: str, *, iterations: int | None = None, salt: str | None = None) -> str:
    """Return 'pbkdf2_sha256$<iterations>$<salt>$<hex digest>'."""
    iterations = iterations or get_settings().password_hash_iterations
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
    return f"{_ALGO}${iterations}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt, _ = stored.split("$")
    except ValueError:
        return False
    if algo != _ALGO:
        return False
    candidate = hash_password(password, iterations=int(iterations), salt=salt)
    return hmac.compare_digest(candidate, stored)


@lru_cache
def _dummy_hash() -> str:
    return hash_password(secrets.token_hex(16))


def burn_password_check(password: str) -> None:
    """Spend the same time as a real check, so unknown LAN IDs can't be detected by timing."""
    verify_password(password, _dummy_hash())


def warm_up() -> None:
    """Pre-compute the dummy hash at start-up so the first unknown-user login isn't slower."""
    _dummy_hash()


def encode_token(claims: dict[str, Any], *, issued_at: datetime, expires_at: datetime) -> str:
    s = get_settings()
    payload = {
        **claims,
        "iss": s.jwt_issuer,
        "aud": s.jwt_audience,
        "iat": issued_at,
        "exp": expires_at,
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    """Verify signature, expiry, issuer and audience. Raises jwt.PyJWTError on any failure."""
    s = get_settings()
    return jwt.decode(
        token,
        s.jwt_secret,
        algorithms=[s.jwt_algorithm],
        audience=s.jwt_audience,
        issuer=s.jwt_issuer,
        options={"require": ["exp", "iat", "sub", "jti", "iss", "aud"]},
    )
