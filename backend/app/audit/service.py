"""Recording and reading the audit trail. Callers commit: an event is part of the change it describes."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, column, func, or_, select, table
from sqlalchemy.orm import Session

from app.audit import context
from app.audit.catalog import action as registered, actions
from app.audit.models import AuditAction, AuditEvent
from app.sources.models import Hierarchy, HierarchyNode, SourceSystem


def sync_actions(db: Session) -> None:
    """Make audit_action match the registered actions (at start-up). The caller commits."""
    for a in actions():
        row = db.get(AuditAction, a.code)
        if row is None:
            db.add(AuditAction(code=a.code, source_system=a.source_system, category=a.category, label=a.label,
                               description=a.description))
        else:
            row.source_system, row.category, row.label, row.description = (
                a.source_system, a.category, a.label, a.description)
    db.flush()


def _ensure_action(db: Session, code: str) -> None:
    if db.get(AuditAction, code) is None:  # registered after start-up (e.g. in tests)
        a = registered(code)
        db.add(AuditAction(code=a.code, source_system=a.source_system, category=a.category, label=a.label,
                           description=a.description))
        db.flush()


def record(db: Session, code: str, *, actor: Any = None, actor_lan_id: str | None = None,
           target: tuple[str, Any] = ("", ""), node_id: uuid.UUID | None = None,
           details: dict[str, Any] | None = None, source_system: str | None = None) -> AuditEvent:
    """Add an event to the caller's transaction. `actor` is a user (anything with .id and .lan_id) or
    None for the system. An event at a node belongs to the node's source system unless `source_system`
    says otherwise."""
    a = registered(code)
    _ensure_action(db, code)
    path = system = None
    if node_id is not None:
        found = db.execute(select(HierarchyNode.path, SourceSystem.code).select_from(HierarchyNode)
                           .join(Hierarchy, Hierarchy.id == HierarchyNode.hierarchy_id)
                           .join(SourceSystem, SourceSystem.id == Hierarchy.source_system_id)
                           .where(HierarchyNode.id == node_id)).first()
        if found:
            path, system = found
    actor_id = getattr(actor, "id", None)
    if actor_id is None and actor_lan_id:  # e.g. a sign-in: find the person, if Data Hub knows them
        users = table("app_user", column("id"), column("lan_id"))
        actor_id = db.scalar(select(users.c.id).where(users.c.lan_id == actor_lan_id.strip().lower()))
        actor_id = uuid.UUID(str(actor_id)) if actor_id else None
    event = AuditEvent(
        actor_id=actor_id, actor_lan_id=actor_lan_id or getattr(actor, "lan_id", None),
        action=code, source_system=source_system or system or a.source_system, category=a.category,
        target_type=target[0], target_id=str(target[1]), hierarchy_node_id=node_id, node_path=path,
        details=details or {}, request_id=context.request_id.get(), client_ip=context.client_ip.get())
    db.add(event)
    return event


def record_now(code: str, **kwargs: Any) -> None:
    """Record an event in its own transaction, committed at once: for events about something that is
    being refused (e.g. a failed sign-in), whose own transaction rolls back."""
    from app.db.session import new_session

    with new_session() as db:
        record(db, code, **kwargs)
        db.commit()


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """{"before": {...}, "after": {...}} with only the keys that changed."""
    keys = [k for k in {**before, **after} if before.get(k) != after.get(k)]
    return {"before": {k: before.get(k) for k in keys}, "after": {k: after.get(k) for k in keys}}


def query(db: Session, *, source_system: str | None = None, category: str | None = None, action: str | None = None,
          actor_id: uuid.UUID | None = None, actor_like: str | None = None, node_id: uuid.UUID | None = None, include_below: bool = False,
          target: tuple[str, str] | None = None, since: datetime | None = None, until: datetime | None = None,
          before: tuple[datetime, uuid.UUID] | None = None, offset: int = 0,
          limit: int = 100) -> tuple[list[AuditEvent], int]:
    """(one page, newest first; how many match in all). Page by `offset`, or by `before` (created_at, id)
    of the previous page's last event, which stays fast however deep the page."""
    q = select(AuditEvent)
    if source_system:
        q = q.where(AuditEvent.source_system == source_system)
    if category:
        q = q.where(AuditEvent.category == category)
    if action:
        q = q.where(AuditEvent.action == action)
    if actor_id:
        q = q.where(AuditEvent.actor_id == actor_id)
    if actor_like:  # part of a LAN ID, any case (LAN IDs are stored lower-case)
        q = q.where(AuditEvent.actor_lan_id.contains(actor_like.strip().lower(), autoescape=True))
    if node_id:
        if include_below:
            path = db.scalar(select(HierarchyNode.path).where(HierarchyNode.id == node_id))
            q = q.where(or_(AuditEvent.hierarchy_node_id == node_id, AuditEvent.node_path.like(f"{path}/%")))
        else:
            q = q.where(AuditEvent.hierarchy_node_id == node_id)
    if target:
        q = q.where(AuditEvent.target_type == target[0], AuditEvent.target_id == target[1])
    if since:
        q = q.where(AuditEvent.created_at >= since)
    if until:
        q = q.where(AuditEvent.created_at < until)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    if before:
        q = q.where(or_(AuditEvent.created_at < before[0],
                        and_(AuditEvent.created_at == before[0], AuditEvent.id < before[1])))
    page = db.scalars(q.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).offset(offset).limit(limit))
    return list(page), total
