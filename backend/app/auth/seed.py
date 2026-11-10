"""Demo users, seeded into an empty database on start-up and by `python -m app.db.reset`."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.security import hash_password

# (LAN ID, display name, email, password)
DEMO_USERS = [
    ("admin", "Data Hub Admin", "admin@datahub.local", "admin123"),
    ("analyst", "Alex Tan", "alex.tan@datahub.local", "datahub123"),
]


def seed_users(db: Session) -> None:
    """Add the demo users if there are no users yet."""
    if db.scalar(select(User.id).limit(1)) is not None:
        return
    db.add_all(
        User(lan_id=lan_id, display_name=name, email=email, password_hash=hash_password(password))
        for lan_id, name, email, password in DEMO_USERS
    )
    db.commit()
