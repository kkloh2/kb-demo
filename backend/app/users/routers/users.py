"""User endpoints.

    GET    /api/users            system admin   every user with their roles, sorted by LAN ID
    GET    /api/users/{lan_id}   system admin   one user with their roles
    PUT    /api/users/{lan_id}   system admin   create/update a user and all their roles
                                                (system roles, and org unit roles in any department)
    DELETE /api/users/{lan_id}   system admin   delete a user and all their roles

Department admins set MAKER, CHECKER and VIEWER in their own department, in departments.py.
"""

from fastapi import APIRouter, Response, status

from app.auth.dependencies import CurrentUser
from app.db.session import Db
from app.users import service
from app.users.authorization import SystemRoles
from app.users.routers.common import FORBIDDEN_403, LanId, user_out, user_out_from
from app.users.schemas import UserOut, UserUpsert

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut], responses=FORBIDDEN_403)
@SystemRoles("SYSTEM_ADMIN")
def list_users(db: Db) -> list[UserOut]:
    """Every user, sorted by LAN ID, with their system and org unit roles."""
    return [user_out_from(item) for item in service.list_users(db)]


@router.get("/{lan_id}", response_model=UserOut, responses={**FORBIDDEN_403, 404: {"description": "No such user"}})
@SystemRoles("SYSTEM_ADMIN")
def get_user(lan_id: LanId, db: Db) -> UserOut:
    """One user with their system and org unit roles."""
    return user_out(db, service.get_user(db, lan_id))


@router.put(
    "/{lan_id}",
    response_model=UserOut,
    responses={
        201: {"model": UserOut, "description": "User created"},
        **FORBIDDEN_403,
        404: {"description": "A department in org_unit_roles doesn't exist"},
        409: {"description": "Email used by another user, MAKER and CHECKER together, or removing your own SYSTEM_ADMIN"},
    },
)
@SystemRoles("SYSTEM_ADMIN")
def upsert_user(lan_id: LanId, body: UserUpsert, db: Db, p: CurrentUser, response: Response) -> UserOut:
    """Create the user (201) or update them (200): profile, system roles and org unit roles in any
    department. Both are complete, in the token's shape. A new user always gets PUBLIC."""
    result = service.upsert_user(
        db, p.lan_id, lan_id,
        display_name=body.display_name, email=body.email, department=body.department, title=body.title,
        system_roles=body.system_roles, org_unit_roles=body.org_unit_roles,
    )
    if result.created:
        response.status_code = status.HTTP_201_CREATED
    return user_out(db, result.user)


@router.delete(
    "/{lan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**FORBIDDEN_403, 404: {"description": "No such user"}, 409: {"description": "Deleting yourself"}},
)
@SystemRoles("SYSTEM_ADMIN")
def delete_user(lan_id: LanId, db: Db, p: CurrentUser) -> Response:
    """Delete the user and all their roles; their sessions end."""
    service.delete_user(db, p.lan_id, lan_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
