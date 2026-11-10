from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.identity import Identity
from app.db.base import utcnow
from app.users.models import User


def get_by_lan_id(db: Session, lan_id: str) -> User | None:
    return db.scalar(select(User).where(User.lan_id == lan_id.strip().lower()))


def record_sign_in(db: Session, identity: Identity) -> None:
    """Sign-in hook (registered in app.main): create or refresh the user from the directory.

    Runs inside auth's sign-in transaction; auth commits. This is also where a deactivated
    user will be refused, by raising app.auth.errors.Unauthenticated.
    """
    user = get_by_lan_id(db, identity.lan_id)
    if user is None:
        user = User(lan_id=identity.lan_id)
        db.add(user)
    user.display_name = identity.display_name
    user.email = identity.email
    user.department = identity.department
    user.title = identity.title
    user.last_login_at = utcnow()
