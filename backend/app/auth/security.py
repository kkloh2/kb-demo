"""JWT encoding/decoding (PyJWT). Passwords are checked by the directory (app.auth.ldap)."""

from datetime import datetime
from typing import Any

import jwt

from app.core.config import get_settings


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
