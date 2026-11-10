"""Data Hub's own record of each person who has signed in.

A row is created the first time someone signs in and refreshed from the directory every time
after (see app.users.hooks.record_sign_in). No passwords are stored.
"""

from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime, utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    lan_id: Mapped[str] = mapped_column(String(64), unique=True)  # stored lower-case
    # Copied from the directory at every sign-in (the directory is the source of truth).
    display_name: Mapped[str] = mapped_column(String(128))
    email: Mapped[str] = mapped_column(String(256), unique=True)
    department: Mapped[str] = mapped_column(String(128), default="")
    title: Mapped[str] = mapped_column(String(128), default="")
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
