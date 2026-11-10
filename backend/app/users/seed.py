"""Demo departments, added to a database that has none."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.users.models import Department

DEMO_DEPARTMENTS = [("RISK", "Risk Management"), ("HR", "Human Resources")]


def seed_departments(db: Session) -> None:
    """The caller commits."""
    if db.scalar(select(Department.id).limit(1)) is not None:
        return
    db.add_all(Department(code=code, name=name) for code, name in DEMO_DEPARTMENTS)
