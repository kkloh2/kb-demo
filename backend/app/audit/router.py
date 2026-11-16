"""Audit endpoints (platform admins).

    GET /api/audit                   platform admins: the whole trail, newest first, with filters (source_system,
                                     category, action, actor LAN ID, node_id + include_below, target_type +
                                     target_id, since, until), one page at a time (offset + limit, or before_id:
                                     the previous page's last) with the total that match
    GET /api/audit/nodes/{node_id}   audit.trail.view at the node (owner, admins, auditors): its activity and
                                     below it
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.access import service as access
from app.access.authorization import Can, Param, PlatformAdmin
from app.access.catalog import P
from app.access.models import AppUser
from app.audit import service
from app.audit.models import AuditAction, AuditEvent
from app.core.errors import NotFound
from app.db.session import Db

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditEventOut(BaseModel):
    id: uuid.UUID
    at: datetime
    actor: str | None = Field(description="LAN ID (the one tried, for a failed sign-in); null: Data Hub itself")
    actor_name: str | None
    action: str = Field(description='e.g. "DOCUMENTS_UPLOADED"')
    label: str = Field(description='e.g. "Documents uploaded"')
    source_system: str = Field(description="PLATFORM, WORKFLOWS, DOC_HUB, APPROVALS ...")
    category: str = Field(description="access, configuration, content, approval or security")
    target_type: str
    target_id: str
    node_id: uuid.UUID | None
    node_path: str | None
    details: dict[str, Any]
    request_id: str | None
    client_ip: str | None


class AuditPageOut(BaseModel):
    items: list[AuditEventOut] = Field(description="This page, newest first")
    total: int = Field(description="How many events match the filters in all")


def _trail(db: Db, *, source_system: str | None, category: str | None, action: str | None, actor: str | None,
           node_id: uuid.UUID | None, include_below: bool, target_type: str | None, target_id: str | None,
           since: datetime | None, until: datetime | None, before_id: uuid.UUID | None, offset: int,
           limit: int) -> AuditPageOut:
    before = None
    if before_id:
        last = db.get(AuditEvent, before_id)
        if last is None:
            raise NotFound("No such audit event.")
        before = (last.created_at, last.id)
    events, total = service.query(
        db, source_system=source_system and source_system.upper(), category=category, action=action,
        actor_like=actor, node_id=node_id, include_below=include_below,
        target=(target_type, target_id) if target_type and target_id else None,
        since=since, until=until, before=before, offset=offset, limit=limit)
    labels = dict(db.execute(select(AuditAction.code, AuditAction.label)).all())
    names = dict(db.execute(select(AppUser.id, AppUser.display_name).where(
        AppUser.id.in_({e.actor_id for e in events if e.actor_id}))).all())
    return AuditPageOut(total=total, items=[AuditEventOut(id=e.id, at=e.created_at, actor=e.actor_lan_id, actor_name=names.get(e.actor_id),
                          action=e.action, label=labels.get(e.action, e.action), source_system=e.source_system,
                          category=e.category, target_type=e.target_type, target_id=e.target_id,
                          node_id=e.hierarchy_node_id, node_path=e.node_path, details=e.details,
                          request_id=e.request_id, client_ip=e.client_ip) for e in events])


@router.get("", response_model=AuditPageOut, responses={403: {"description": "Not a platform admin"}})
@PlatformAdmin
def audit_trail(
    db: Db,
    source_system: str | None = None,
    category: str | None = None,
    action: str | None = None,
    actor: Annotated[str | None, Query(description="All or part of a LAN ID, any case")] = None,
    node_id: uuid.UUID | None = None,
    include_below: bool = False,
    target_type: str | None = None,
    target_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    before_id: Annotated[uuid.UUID | None, Query(description="Continue after this event (the previous page's last)")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> AuditPageOut:
    """Everything, for platform admins."""
    return _trail(db, source_system=source_system, category=category, action=action, actor=actor, node_id=node_id,
                  include_below=include_below, target_type=target_type, target_id=target_id, since=since,
                  until=until, before_id=before_id, offset=offset, limit=limit)


def _node(db, node_id: uuid.UUID) -> uuid.UUID:
    return access.get_node(db, node_id).id


@router.get("/nodes/{node_id}", response_model=AuditPageOut,
            responses={403: {"description": "No audit.trail.view at the node"}})
@Can(P.AUDIT_VIEW, at=Param("node_id", _node))
def node_activity(
    node_id: uuid.UUID,
    db: Db,
    category: str | None = None,
    actor: Annotated[str | None, Query(description="All or part of a LAN ID, any case")] = None,
    since: datetime | None = None,
    until: datetime | None = None,
    before_id: uuid.UUID | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> AuditPageOut:
    """The activity at a node (e.g. a repository) and below it, for whoever holds audit.trail.view there
    (its owner and admins, and auditors)."""
    return _trail(db, source_system=None, category=category, action=None, actor=actor, node_id=node_id,
                  include_below=True, target_type=None, target_id=None, since=since, until=until,
                  before_id=before_id, offset=offset, limit=limit)
