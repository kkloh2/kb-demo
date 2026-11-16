"""Shared SQLAlchemy base and column types. Each feature package defines its own models on Base.

Ids are UUIDv7 (time-ordered, so indexes stay compact and ids sort by creation), stored with
SQLAlchemy's `Uuid` type: CHAR(32) on SQLite, the native uuid type on PostgreSQL.
"""

import os
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData, TypeDecorator
from sqlalchemy.orm import DeclarativeBase

# Every constraint gets a predictable name, so a migration can find it to change or drop it later
# (SQLite leaves them unnamed otherwise). Check constraints are named in the models themselves.
NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ix": "ix_%(column_0_label)s",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def uuid7() -> uuid.UUID:
    """A UUIDv7 (RFC 9562): 48 bits of Unix milliseconds, then random bits. Python 3.13 has no
    uuid.uuid7(); 3.14 does."""
    millis = time.time_ns() // 1_000_000
    value = (millis & ((1 << 48) - 1)) << 80 | int.from_bytes(os.urandom(10), "big")
    value = (value & ~(0xF << 76)) | (0x7 << 76)  # version 7
    value = (value & ~(0x3 << 62)) | (0x2 << 62)  # RFC 4122 variant
    return uuid.UUID(int=value)


class UTCDateTime(TypeDecorator[datetime]):
    """Stores UTC; always returns timezone-aware datetimes (SQLite has no timezone type)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetimes are not allowed; use timezone-aware UTC.")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
