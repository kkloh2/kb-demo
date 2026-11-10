"""User lookups and roles.

Roles say what each person may do in Data Hub. They travel in the access token as a "roles"
claim, added at sign-in by hooks.add_roles_claim and read back with roles_of.

PLACEHOLDER: which roles exist and how they are assigned isn't decided yet, so lookup_roles
returns no roles for everyone. Only lookup_roles needs to change when that is decided.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.identity import Principal
from app.users.models import User

ROLES_CLAIM = "roles"


# --------------------------------------------------------------------------- users


def get_by_lan_id(db: Session, lan_id: str) -> User | None:
    return db.scalar(select(User).where(User.lan_id == lan_id.strip().lower()))


# --------------------------------------------------------------------------- roles


def lookup_roles(db: Session, lan_id: str) -> list[str]:
    """The person's role codes, e.g. ["CHECKER"].

    PLACEHOLDER: roles aren't designed yet, so nobody has any. Replace this lookup (a roles
    table, a directory group mapping, ...) when they are; the token and roles_of stay as they are.
    """
    return []


def roles_of(principal: Principal) -> frozenset[str]:
    """The signed-in caller's roles, as recorded in their token at sign-in."""
    roles = principal.claims.get(ROLES_CLAIM, [])
    return frozenset(r for r in roles if isinstance(r, str)) if isinstance(roles, list) else frozenset()
