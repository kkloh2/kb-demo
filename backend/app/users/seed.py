"""Seed data for the users module.

    seed_system_admins   every start-up, every database: the LAN IDs in
                         settings.bootstrap_system_admins exist and hold SYSTEM_ADMIN
    seed_departments     demo only: RISK and HR, added to a database that has no departments
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.users.models import Department, RoleCode, User
from app.users.service import ensure_system_role, get_by_lan_id

DEMO_DEPARTMENTS = [("RISK", "Risk Management"), ("HR", "Human Resources")]


def seed_system_admins(db: Session) -> list[str]:
    """Make sure the bootstrap system admins exist and hold SYSTEM_ADMIN. The caller commits.

    A missing user is created with placeholder details (the LAN ID as name, an unroutable
    @pending.invalid email) and PUBLIC, like anyone new; the directory fills in their real details
    at their first sign-in. SYSTEM_ADMIN is restored on every start-up, so a bootstrap admin can't
    be locked out by removing it. Returns the LAN IDs that were created.
    """
    created = []
    for lan_id in sorted({x.strip().lower() for x in get_settings().bootstrap_system_admins if x.strip()}):
        user = get_by_lan_id(db, lan_id)
        if user is None:
            user = User(lan_id=lan_id, display_name=lan_id, email=f"{lan_id}@pending.invalid")
            db.add(user)
            db.flush()
            ensure_system_role(db, user, RoleCode.PUBLIC)
            created.append(lan_id)
        ensure_system_role(db, user, RoleCode.SYSTEM_ADMIN)
    return created


def seed_departments(db: Session) -> None:
    """The caller commits."""
    if db.scalar(select(Department.id).limit(1)) is not None:
        return
    db.add_all(Department(code=code, name=name) for code, name in DEMO_DEPARTMENTS)
