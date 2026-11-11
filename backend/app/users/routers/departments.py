"""Department endpoints.

    POST   /api/departments                         system admin   create a department {code, name}
    PUT    /api/departments/{code}                  system admin   replace its code and name
    DELETE /api/departments/{code}                  system admin   delete it and every role held in it
    PUT    /api/departments/{code}/users/{lan_id}   system admin OR that department's admin:
                                                                   set the user's MAKER/CHECKER/VIEWER there
    DELETE /api/departments/{code}/users/{lan_id}   system admin OR that department's admin:
                                                                   remove the user's MAKER/CHECKER/VIEWER there
"""

from fastapi import APIRouter, Response, status

from app.auth.dependencies import CurrentUser
from app.db.session import Db
from app.users import service
from app.users.authorization import OrgUnitRoles, SystemRoles
from app.users.models import Department
from app.users.routers.common import FORBIDDEN_403, DepartmentCode, LanId, user_out
from app.users.schemas import DepartmentIn, DepartmentOut, DepartmentRolesIn, UserOut

router = APIRouter(prefix="/departments", tags=["departments"])


def _department_out(d: Department) -> DepartmentOut:
    return DepartmentOut(id=d.id, code=d.code, name=d.name)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=DepartmentOut,
    responses={**FORBIDDEN_403, 409: {"description": "A department with this code already exists"}},
)
@SystemRoles("SYSTEM_ADMIN")
def create_department(body: DepartmentIn, db: Db, p: CurrentUser, response: Response) -> DepartmentOut:
    """Create a department. The Location header points at it."""
    department = service.create_department(db, p.lan_id, body.code, body.name)
    response.headers["Location"] = f"/api/departments/{department.code}"
    return _department_out(department)


@router.put(
    "/{code}",
    response_model=DepartmentOut,
    responses={
        **FORBIDDEN_403,
        404: {"description": "No such department"},
        409: {"description": "The new code is already used by another department"},
    },
)
@SystemRoles("SYSTEM_ADMIN")
def update_department(code: DepartmentCode, body: DepartmentIn, db: Db) -> DepartmentOut:
    """Replace the department's code and name. A different `code` in the body renames the code;
    roles held there move with it."""
    return _department_out(service.update_department(db, code, body.code, body.name))


@router.delete(
    "/{code}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**FORBIDDEN_403, 404: {"description": "No such department"}},
)
@SystemRoles("SYSTEM_ADMIN")
def delete_department(code: DepartmentCode, db: Db) -> Response:
    """Delete the department. Everyone loses the roles they held in it."""
    service.delete_department(db, code)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/{code}/users/{lan_id}",
    response_model=UserOut,
    responses={**FORBIDDEN_403, 404: {"description": "No such department or user"},
               409: {"description": "MAKER and CHECKER together"}},
)
@SystemRoles("SYSTEM_ADMIN")
@OrgUnitRoles("DEPARTMENT_ADMIN", department="code")
def set_department_roles(code: DepartmentCode, lan_id: LanId, body: DepartmentRolesIn, db: Db, p: CurrentUser) -> UserOut:
    """Set the user's MAKER, CHECKER and VIEWER roles in this department to exactly `roles`."""
    user = service.set_department_roles(db, p.lan_id, lan_id, code, body.roles)
    return user_out(db, user)


@router.delete(
    "/{code}/users/{lan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**FORBIDDEN_403, 404: {"description": "No such department or user"}},
)
@SystemRoles("SYSTEM_ADMIN")
@OrgUnitRoles("DEPARTMENT_ADMIN", department="code")
def remove_department_roles(code: DepartmentCode, lan_id: LanId, db: Db, p: CurrentUser) -> Response:
    """Remove the user's MAKER, CHECKER and VIEWER roles in this department."""
    service.set_department_roles(db, p.lan_id, lan_id, code, [])
    return Response(status_code=status.HTTP_204_NO_CONTENT)
