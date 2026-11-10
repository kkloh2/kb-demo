"""The users module's auth sign-in hooks. Registered in app.main, in this order:

    record_sign_in   create or refresh the user from the directory details; a new user gets
                     PUBLIC, and LAN IDs in settings.bootstrap_system_admins get SYSTEM_ADMIN
    add_roles_claim  put the person's roles in the access token:
                     {"system_roles": [...], "org_unit_roles": {"RISK": [...], ...}}

Both run inside auth's sign-in transaction (auth commits), after the directory has accepted
the password. A hook can refuse the sign-in by raising app.auth.errors.Unauthenticated;
that is where deactivated users will be refused.
"""

from typing import Any

from sqlalchemy.orm import Session

from app.auth.identity import Identity
from app.core.config import get_settings
from app.db.base import utcnow
from app.users import service
from app.users.models import RoleCode, User


def record_sign_in(db: Session, identity: Identity) -> None:
    """Create or refresh the user from the directory details. Adds no token claims."""
    user = service.get_by_lan_id(db, identity.lan_id)
    is_new = user is None
    if user is None:
        user = User(lan_id=identity.lan_id)
        db.add(user)
    user.display_name = identity.display_name
    user.email = identity.email
    user.department = identity.department
    user.title = identity.title
    user.last_login_at = utcnow()
    db.flush()  # user.id for the role rows below

    if is_new:
        service.ensure_system_role(db, user, RoleCode.PUBLIC)
    if identity.lan_id in {x.strip().lower() for x in get_settings().bootstrap_system_admins}:
        service.ensure_system_role(db, user, RoleCode.SYSTEM_ADMIN)


def add_roles_claim(db: Session, identity: Identity) -> dict[str, Any]:
    """Put the person's system and org unit roles in the access token."""
    return service.roles_claims(db, service.get_by_lan_id(db, identity.lan_id))
