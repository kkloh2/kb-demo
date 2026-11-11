"""User endpoints.

    PUT    /api/users/{lan_id}   system admin   create/update a user, their system roles and the
                                                departments they administer
    DELETE /api/users/{lan_id}   system admin   delete a user and all their roles

A user's MAKER, CHECKER and VIEWER roles are set per department, in departments.py.
"""

from fastapi import APIRouter, Response, status

from app.auth.dependencies import CurrentUser
from app.db.session import Db
from app.users import service
from app.users.authorization import SystemRoles
from app.users.routers.common import FORBIDDEN_403, LanId, user_out
from app.users.schemas import UserOut, UserUpsert

router = APIRouter(prefix="/users", tags=["users"])


@router.put(
    "/{lan_id}",
    response_model=UserOut,
    responses={
        201: {"model": UserOut, "description": "User created"},
        **FORBIDDEN_403,
        404: {"description": "A department in department_admin_of doesn't exist"},
        409: {"description": "Email used by another user, or removing your own SYSTEM_ADMIN"},
    },
)
@SystemRoles("SYSTEM_ADMIN")
def upsert_user(lan_id: LanId, body: UserUpsert, db: Db, p: CurrentUser, response: Response) -> UserOut:
    """Create the user (201) or update them (200): profile, system roles and the departments they
    administer. Both role lists are complete. A new user always gets PUBLIC."""
    result = service.upsert_user(
        db, p.lan_id, lan_id,
        display_name=body.display_name, email=body.email, department=body.department, title=body.title,
        system_roles=body.system_roles, department_admin_of=body.department_admin_of,
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
