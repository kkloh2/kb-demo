import json
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AuditEvent


def record(
    db: Session,
    action: str,
    *,
    outcome: str = "success",
    actor_id: int | None = None,
    actor_lan_id: str | None = None,
    target_type: str | None = None,
    target_id: str | int | None = None,
    detail: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """Add an audit event to the current transaction (committed with the change it describes)."""
    db.add(
        AuditEvent(
            action=action,
            outcome=outcome,
            actor_id=actor_id,
            actor_lan_id=actor_lan_id,
            target_type=target_type,
            target_id=None if target_id is None else str(target_id),
            detail=json.dumps(detail) if detail else None,
            ip_address=ip_address,
        )
    )
