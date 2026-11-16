"""Access endpoints.

    GET    /api/me/access                         signed in        what I may do (for the UI)
    GET    /api/users                             platform admin   everyone, with platform admin and status
    PUT    /api/users/{lan_id}                    platform admin   add or update someone; platform admin yes/no
    POST   /api/users/{lan_id}/active             platform admin   switch access off or on
    GET    /api/roles                             platform admin   roles and their permissions
    GET    /api/teams                             platform admin   COMPLIANCE, AUDIT ... and their members
    PUT    /api/teams/{code}/members              platform admin   set a team's members
    GET    /api/default-grants                    platform admin   team grants every new repository gets
    POST   /api/default-grants                    platform admin   add one (applied to existing ones too)
    DELETE /api/default-grants/{id}               platform admin
    PUT    /api/nodes/{node_id}/owner             platform admin   recovery: reassign a node's owner
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status

from app.access import service
from app.access.authorization import PlatformAdmin
from app.access.catalog import PERMISSIONS, ROLE_PERMISSIONS, ROLES, NodeType
from app.access.models import AppUser
from app.access.schemas import (
    ActiveIn,
    DefaultGrantIn,
    DefaultGrantOut,
    MemberOut,
    MyAccessOut,
    NodeAccessOut,
    OwnerIn,
    PermissionOut,
    PersonOut,
    RoleOut,
    RolesOut,
    TeamMembersIn,
    TeamOut,
    UserIn,
    UserOut,
)
from app.auth.dependencies import CurrentUser
from app.core.errors import InvalidRequest
from app.db.session import Db

router = APIRouter(tags=["access"])

LanId = Annotated[str, Path(min_length=1, max_length=64, description="LAN ID (case-insensitive)")]
_403 = {403: {"description": "Not a platform admin"}}


def person(u: AppUser) -> PersonOut:
    return PersonOut(lan_id=u.lan_id, display_name=u.display_name, email=u.email, title=u.title)


def member_out(m: service.Member) -> MemberOut:
    return MemberOut(**person(m.user).model_dump(), roles=m.roles)


def _user_out(v: service.UserView) -> UserOut:
    u = v.user
    return UserOut(**person(u).model_dump(), directory_department=u.directory_department, status=u.status,
                   platform_admin=v.platform_admin, last_login_at=u.last_login_at, created_at=u.created_at,
                   updated_at=u.updated_at)


def _system(code: str) -> str:
    return code.strip().upper()


@router.get("/me/access", response_model=MyAccessOut)
def my_access(db: Db, p: CurrentUser) -> MyAccessOut:
    """Where I hold roles, what they let me do, and whether to show the admin and Approvals pages."""
    a = service.my_access(db, service.require_user(db, p.lan_id))
    return MyAccessOut(
        system_roles=a.system_roles, platform_admin=a.platform_admin, can_decide=a.can_decide,
        nodes=[NodeAccessOut(system=n.system, node_id=n.node.id, node_code=n.node.code, node_name=n.node.name,
                             node_type=n.node.node_type, path=n.node.path, roles=n.roles, permissions=n.permissions)
               for n in a.nodes],
    )


# --------------------------------------------------------------------------- users


@router.get("/users", response_model=list[UserOut], responses=_403)
@PlatformAdmin
def list_users(db: Db) -> list[UserOut]:
    return [_user_out(v) for v in service.list_users(db)]


@router.put("/users/{lan_id}", response_model=UserOut, responses={**_403, 201: {"model": UserOut}})
@PlatformAdmin
def upsert_user(lan_id: LanId, body: UserIn, db: Db, p: CurrentUser, response: Response) -> UserOut:
    """Add someone before their first sign-in (201) or update them (200), and say whether they're a
    platform admin. The directory refreshes their details at every sign-in."""
    view, created = service.upsert_user(
        db, service.require_user(db, p.lan_id), lan_id, display_name=body.display_name, email=body.email,
        title=body.title, directory_department=body.directory_department, platform_admin=body.platform_admin)
    if created:
        response.status_code = status.HTTP_201_CREATED
    return _user_out(view)


@router.post("/users/{lan_id}/active", response_model=UserOut, responses=_403)
@PlatformAdmin
def set_active(lan_id: LanId, body: ActiveIn, db: Db, p: CurrentUser) -> UserOut:
    """Switch someone's access off (they can't sign in and their sessions end) or back on."""
    return _user_out(service.set_user_active(db, service.require_user(db, p.lan_id), lan_id, body.active))


@router.get("/roles", response_model=RolesOut, responses=_403)
@PlatformAdmin
def list_roles(db: Db) -> RolesOut:
    """Roles (most to least powerful) and the permissions each carries. Defined in code."""
    return RolesOut(
        roles=[RoleOut(code=c.value, name=n, description=d, permissions=sorted(p.value for p in ROLE_PERMISSIONS[c]))
               for c, (n, d) in ROLES.items()],
        permissions=[PermissionOut(code=c.value, name=n) for c, n in PERMISSIONS.items()],
    )


# --------------------------------------------------------------------------- teams


def _team_out(t: service.TeamView) -> TeamOut:
    return TeamOut(code=t.code, name=t.name, members=[person(u) for u in t.members])


@router.get("/teams", response_model=list[TeamOut], responses=_403)
@PlatformAdmin
def list_teams(db: Db) -> list[TeamOut]:
    return [_team_out(t) for t in service.list_teams(db)]


@router.put("/teams/{code}/members", response_model=TeamOut, responses=_403)
@PlatformAdmin
def set_team_members(code: str, body: TeamMembersIn, db: Db, p: CurrentUser) -> TeamOut:
    return _team_out(service.set_team_members(db, service.require_user(db, p.lan_id), code, body.lan_ids))


def _default_out(d: service.DefaultGrantView) -> DefaultGrantOut:
    return DefaultGrantOut(id=d.id, system=d.parent_system, child_node_type=d.child_node_type, team=d.team_code,
                           team_name=d.team_name, role=d.role)


@router.get("/default-grants", response_model=list[DefaultGrantOut], responses=_403)
@PlatformAdmin
def list_default_grants(db: Db) -> list[DefaultGrantOut]:
    return [_default_out(d) for d in service.list_default_grants(db)]


@router.post("/default-grants", response_model=DefaultGrantOut, status_code=status.HTTP_201_CREATED, responses=_403)
@PlatformAdmin
def add_default_grant(body: DefaultGrantIn, db: Db, p: CurrentUser) -> DefaultGrantOut:
    """Give a team a read-only role on every repository: new ones when created, existing ones now."""
    try:
        child_type = NodeType(body.child_node_type.strip().upper())
    except ValueError:
        raise InvalidRequest(f"Unknown node type {body.child_node_type!r}.") from None
    return _default_out(service.add_default_grant(
        db, service.require_user(db, p.lan_id), _system(body.system), child_type, body.team, body.role))


@router.delete("/default-grants/{grant_id}", status_code=status.HTTP_204_NO_CONTENT, responses=_403)
@PlatformAdmin
def remove_default_grant(grant_id: uuid.UUID, db: Db, p: CurrentUser) -> Response:
    """Stop the default and remove the team grants it made."""
    service.remove_default_grant(db, service.require_user(db, p.lan_id), grant_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- recovery and audit


@router.put("/nodes/{node_id}/owner", status_code=status.HTTP_204_NO_CONTENT, responses=_403)
@PlatformAdmin
def reassign_owner(node_id: uuid.UUID, body: OwnerIn, db: Db, p: CurrentUser) -> Response:
    """Recovery: give the node a new owner (e.g. its owner has left). Audited."""
    node = service.get_node(db, node_id, include_deleted=True)
    service.transfer_ownership(db, service.require_user(db, p.lan_id), node, body.lan_id, recovery=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
