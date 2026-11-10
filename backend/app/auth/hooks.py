"""Extension point: other modules take part in sign-in without auth knowing about them.

A sign-in hook runs after the directory has accepted the password and before the session is
created, inside the same database transaction. It may:
  - record the sign-in (the users module creates or refreshes the user's record),
  - add claims to the access token by returning them as a dict (the users module adds its role claims),
  - refuse the sign-in by raising a DomainError, e.g. Unauthenticated (nothing is saved then).

Added claims come back on every request as Principal.claims. They are a snapshot taken at
sign-in, so keep them small (codes, not lists of records).

Hooks are registered once at start-up, in app.main.
"""

from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy.orm import Session

from app.auth.identity import Identity

SignInHook = Callable[[Session, Identity], Mapping[str, Any] | None]

# Claims auth sets itself (app.auth.service) plus the registered JWT ones. Hooks can't use them.
RESERVED_CLAIMS = frozenset(
    {"sub", "jti", "name", "email", "department", "title", "iss", "aud", "iat", "exp", "nbf"}
)

_sign_in_hooks: list[SignInHook] = []


def on_sign_in(hook: SignInHook) -> SignInHook:
    """Register a hook. Registering the same function twice has no effect."""
    if hook not in _sign_in_hooks:
        _sign_in_hooks.append(hook)
    return hook


def run_sign_in_hooks(db: Session, identity: Identity) -> dict[str, Any]:
    """Run every hook; return the extra token claims they added."""
    extra: dict[str, Any] = {}
    for hook in list(_sign_in_hooks):
        claims = hook(db, identity) or {}
        taken = (RESERVED_CLAIMS | extra.keys()) & claims.keys()
        if taken:  # a programming error, not a user error
            raise RuntimeError(f"Sign-in hook {hook.__qualname__} adds claims already in use: {sorted(taken)}")
        extra.update(claims)
    return extra
