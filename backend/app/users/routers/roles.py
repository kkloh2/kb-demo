"""Role endpoints (read-only: roles are defined in code and synced into the database at start-up).

    GET    /api/roles            system admin   every role: system roles, then org unit roles (by privilege)
    GET    /api/roles/{code}     system admin   one role
"""

from typing import Annotated

from fastapi import APIRouter, Path

from app.db.session import Db
from app.users import service
from app.users.authorization import SystemRoles
from app.users.models import Role
from app.users.routers.common import FORBIDDEN_403
from app.users.schemas import RoleOut

router = APIRouter(prefix="/roles", tags=["roles"])

RoleCodeParam = Annotated[str, Path(min_length=1, max_length=32, description='e.g. "CHECKER" (case-insensitive)')]


def _role_out(r: Role) -> RoleOut:
    return RoleOut(code=r.code, scope=r.scope, name=r.name, description=r.description)


@router.get("", response_model=list[RoleOut], responses=FORBIDDEN_403)
@SystemRoles("SYSTEM_ADMIN")
def list_roles(db: Db) -> list[RoleOut]:
    """Every role with its scope: system roles, then org unit roles from department admin to viewer."""
    return [_role_out(r) for r in service.list_roles(db)]


@router.get("/{code}", response_model=RoleOut, responses={**FORBIDDEN_403, 404: {"description": "No such role"}})
@SystemRoles("SYSTEM_ADMIN")
def get_role(code: RoleCodeParam, db: Db) -> RoleOut:
    """One role."""
    return _role_out(service.require_role(db, code))
