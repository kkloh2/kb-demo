"""Extension point: other modules react to a sign-in without auth knowing about them.

A sign-in hook runs after the directory has accepted the password and before the session is
created, inside the same database transaction. It may:
  - record the sign-in (the users module creates or refreshes the user's record), or
  - refuse it by raising a DomainError, e.g. Unauthenticated (nothing is saved then).

Hooks are registered once at start-up, in app.main.
"""

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.auth.identity import Identity

SignInHook = Callable[[Session, Identity], None]

_sign_in_hooks: list[SignInHook] = []


def on_sign_in(hook: SignInHook) -> SignInHook:
    """Register a hook. Registering the same function twice has no effect."""
    if hook not in _sign_in_hooks:
        _sign_in_hooks.append(hook)
    return hook


def run_sign_in_hooks(db: Session, identity: Identity) -> None:
    for hook in list(_sign_in_hooks):
        hook(db, identity)
