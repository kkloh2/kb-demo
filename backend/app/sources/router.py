"""Source system endpoints (platform admins).

    GET    /api/sources                                         every source system, its hierarchy and root groups
    POST   /api/sources                                         {code, name}: a new source system
    POST   /api/sources/{code}/hierarchy                        {name, levels}: its hierarchy and root node,
                                                                with admins (platform admins) and users (everyone)
    PUT    /api/sources/{code}/groups/{group}/members/{lan_id}  {roles}: someone's roles in a root group
    DELETE /api/sources/{code}/groups/{group}/members/{lan_id}  take them out of that group
"""

from typing import Annotated

from fastapi import APIRouter, Path, Response, status

from app.access import service as access
from app.access.authorization import PlatformAdmin
from app.access.router import member_out
from app.auth.dependencies import CurrentUser
from app.db.session import Db
from app.sources import service
from app.sources.schemas import GroupMemberOut, GroupOut, GroupRolesIn, HierarchyIn, HierarchyOut, SourceIn, SourceOut

router = APIRouter(prefix="/sources", tags=["sources"])

Code = Annotated[str, Path(min_length=1, max_length=32, description='e.g. "DOC_HUB" (case-insensitive)')]
LanId = Annotated[str, Path(min_length=1, max_length=64)]
_403 = {403: {"description": "Not a platform admin"}}


def _out(v: service.SourceView) -> SourceOut:
    h = None
    if v.hierarchy is not None and v.root is not None:
        h = HierarchyOut(
            name=v.root.name, levels=v.hierarchy.levels, root_node_id=v.root.id, child_count=v.child_count,
            groups=[GroupOut(type=g.group.group_type, name=g.group.name, roles=g.grantable,
                             auto_join_role=g.auto_join_role,
                             members=[GroupMemberOut(**member_out(m).model_dump(), added_at=m.added_at,
                                                     updated_at=m.updated_at) for m in g.members])
                    for g in v.groups])
    return SourceOut(code=v.system.code, name=v.system.name, status=v.system.status,
                     created_at=v.system.created_at, last_updated=v.last_updated, hierarchy=h)


def _one(db: Db, code: str) -> SourceOut:
    return next(_out(v) for v in service.list_sources(db) if v.system.code == code.strip().upper())


@router.get("", response_model=list[SourceOut], responses=_403)
@PlatformAdmin
def list_sources(db: Db) -> list[SourceOut]:
    return [_out(v) for v in service.list_sources(db)]


@router.post("", response_model=SourceOut, status_code=status.HTTP_201_CREATED,
             responses={**_403, 409: {"description": "The code is taken"}})
@PlatformAdmin
def create_source(body: SourceIn, db: Db, p: CurrentUser) -> SourceOut:
    system = service.create_source(db, access.require_user(db, p.lan_id), body.code, body.name)
    return _one(db, system.code)


@router.post("/{code}/hierarchy", response_model=SourceOut, status_code=status.HTTP_201_CREATED,
             responses={**_403, 409: {"description": "It already has one"}})
@PlatformAdmin
def create_hierarchy(code: Code, body: HierarchyIn, db: Db, p: CurrentUser) -> SourceOut:
    """Create the system's hierarchy and root node. The root gets an admins group (every platform
    admin is added, as ADMIN) and a users group (everyone, as VIEWER, now and at their first sign-in)."""
    service.create_hierarchy(db, access.require_user(db, p.lan_id), code, body.name, body.levels)
    return _one(db, code)


@router.put("/{code}/groups/{group}/members/{lan_id}", response_model=SourceOut, responses=_403)
@PlatformAdmin
def set_group_roles(code: Code, group: str, lan_id: LanId, body: GroupRolesIn, db: Db, p: CurrentUser) -> SourceOut:
    """Make someone's roles in the root's admins or users group exactly `roles`."""
    service.set_group_roles(db, access.require_user(db, p.lan_id), code, group, lan_id, body.roles)
    return _one(db, code)


@router.delete("/{code}/groups/{group}/members/{lan_id}", status_code=status.HTTP_204_NO_CONTENT, responses=_403)
@PlatformAdmin
def remove_from_group(code: Code, group: str, lan_id: LanId, db: Db, p: CurrentUser) -> Response:
    service.set_group_roles(db, access.require_user(db, p.lan_id), code, group, lan_id, [])
    return Response(status_code=status.HTTP_204_NO_CONTENT)
