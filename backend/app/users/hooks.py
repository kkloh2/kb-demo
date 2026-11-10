"""The users module's auth sign-in hooks. Registered in app.main, in this order:

    record_sign_in   create or refresh the user from the directory details
    add_roles_claim  put the person's roles in the access token as {"roles": [...]}

Both run inside auth's sign-in transaction (auth commits), after the directory has accepted
the password. A hook can refuse the sign-in by raising app.auth.errors.Unauthenticated;
that is where deactivated users will be refused.
"""

from typing import Any

from sqlalchemy.orm import Session

from app.auth.identity import Identity
from app.db.base import utcnow
from app.users import service
from app.users.models import User


def record_sign_in(db: Session, identity: Identity) -> None:
    """Create or refresh the user from the directory details. Adds no token claims."""
    user = service.get_by_lan_id(db, identity.lan_id)
    if user is None:
        user = User(lan_id=identity.lan_id)
        db.add(user)
    user.display_name = identity.display_name
    user.email = identity.email
    user.department = identity.department
    user.title = identity.title
    user.last_login_at = utcnow()


def add_roles_claim(db: Session, identity: Identity) -> dict[str, Any]:
    """Put the person's roles in the access token."""
    return {service.ROLES_CLAIM: sorted(set(service.lookup_roles(db, identity.lan_id)))}
