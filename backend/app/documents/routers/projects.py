"""Project endpoints.

    GET    /api/projects                              signed in        projects the caller can see
    GET    /api/projects/departments                  signed in        departments the caller can create projects in
    POST   /api/departments/{code}/projects           that department's admin
    GET    /api/projects/{project_id}                 department VIEWER or admin, or any project role
    PUT    /api/projects/{project_id}                 the department's admin   name, description, base metadata
    DELETE /api/projects/{project_id}                 the department's admin
    GET    /api/projects/{project_id}/members         the department's admin
    PUT    /api/projects/{project_id}/members/{lan_id}   the department's admin   {roles: [MAKER|CHECKER|VIEWER]}
    DELETE /api/projects/{project_id}/members/{lan_id}   the department's admin
"""

from typing import Annotated

from fastapi import APIRouter, Path, Response, status

from app.auth.dependencies import CurrentUser
from app.auth.identity import Principal
from app.db.session import Db
from app.documents import service
from app.documents.authorization import ProjectRoles
from app.documents.models import Project
from app.documents.schemas import (
    DepartmentRef,
    MemberOut,
    MemberRolesIn,
    ProjectAccessOut,
    ProjectIn,
    ProjectOut,
)
from app.users.authorization import OrgUnitRoles

router = APIRouter(tags=["projects"])

ProjectId = Annotated[int, Path(ge=1, description="Project id")]
DepartmentCode = Annotated[str, Path(min_length=1, max_length=32, description='e.g. "RISK" (case-insensitive)')]
LanId = Annotated[str, Path(min_length=1, max_length=64, description="LAN ID (case-insensitive)")]

DEPARTMENT_ADMIN = ("DEPARTMENT_ADMIN",)
ANY_PROJECT_ROLE = ("MAKER", "CHECKER", "VIEWER")
_403 = {403: {"description": "Caller lacks the required role"}}
_404 = {404: {"description": "No such project"}}


def _out(project: Project, access: service.ProjectAccess) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        department=DepartmentRef(code=project.department.code, name=project.department.name),
        country=project.country,
        business_unit=project.business_unit,
        purpose=project.purpose,
        valid_till=project.valid_till,
        created_by=project.created_by.display_name if project.created_by else None,
        created_at=project.created_at,
        updated_at=project.updated_at,
        access=ProjectAccessOut(
            manage=access.manage,
            view_documents=access.view_documents,
            upload=access.upload,
            review=access.review,
            project_roles=[r for r in ANY_PROJECT_ROLE if r in access.project_roles],
        ),
    )


def _out_for(db: Db, p: Principal, project: Project) -> ProjectOut:
    return _out(project, service.access_to(db, p, project))


# --------------------------------------------------------------------------- projects


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(db: Db, p: CurrentUser) -> list[ProjectOut]:
    """Projects in the caller's departments (as VIEWER or DEPARTMENT_ADMIN) and any project they hold a
    role in, most recently updated first."""
    return [_out(item.project, item.access) for item in service.list_projects(db, p)]


@router.get("/projects/departments", response_model=list[DepartmentRef])
def creatable_departments(db: Db, p: CurrentUser) -> list[DepartmentRef]:
    """Departments the caller administers, i.e. can create projects in."""
    return [DepartmentRef(code=d.code, name=d.name) for d in service.manageable_departments(db, p)]


@router.post(
    "/departments/{code}/projects",
    status_code=status.HTTP_201_CREATED,
    response_model=ProjectOut,
    responses={**_403, 404: {"description": "No such department"},
               409: {"description": "The department already has a project with this name"}},
)
@OrgUnitRoles("DEPARTMENT_ADMIN", department="code")
def create_project(code: DepartmentCode, body: ProjectIn, db: Db, p: CurrentUser, response: Response) -> ProjectOut:
    """Create a project in the department, with its base metadata."""
    project = service.create_project(db, p.lan_id, code, service.ProjectFields(**body.model_dump()))
    response.headers["Location"] = f"/api/projects/{project.id}"
    return _out_for(db, p, project)


@router.get("/projects/{project_id}", response_model=ProjectOut, responses={**_403, **_404})
@ProjectRoles(*ANY_PROJECT_ROLE, department_roles=("DEPARTMENT_ADMIN", "VIEWER"))
def get_project(project_id: ProjectId, db: Db, p: CurrentUser) -> ProjectOut:
    """One project, with what the caller can do with it."""
    return _out_for(db, p, service.get_project(db, project_id))


@router.put(
    "/projects/{project_id}",
    response_model=ProjectOut,
    responses={**_403, **_404, 409: {"description": "The department already has a project with this name"}},
)
@ProjectRoles(department_roles=DEPARTMENT_ADMIN)
def update_project(project_id: ProjectId, body: ProjectIn, db: Db, p: CurrentUser) -> ProjectOut:
    """Replace the project's name, description and base metadata."""
    project = service.update_project(db, project_id, service.ProjectFields(**body.model_dump()))
    return _out_for(db, p, project)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT, responses={**_403, **_404})
@ProjectRoles(department_roles=DEPARTMENT_ADMIN)
def delete_project(project_id: ProjectId, db: Db) -> Response:
    """Delete the project and its members."""
    service.delete_project(db, project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- members


def _member_out(m: service.Member) -> MemberOut:
    return MemberOut(lan_id=m.user.lan_id, display_name=m.user.display_name, email=m.user.email,
                     title=m.user.title, roles=m.roles)


@router.get("/projects/{project_id}/members", response_model=list[MemberOut], responses={**_403, **_404})
@ProjectRoles(department_roles=DEPARTMENT_ADMIN)
def list_members(project_id: ProjectId, db: Db) -> list[MemberOut]:
    """The project's members and their roles. The department's admin isn't listed: they're a viewer
    of every project by default."""
    return [_member_out(m) for m in service.list_members(db, project_id)]


@router.put(
    "/projects/{project_id}/members/{lan_id}",
    response_model=MemberOut,
    responses={**_403, 404: {"description": "No such project or user"},
               409: {"description": "MAKER and CHECKER together"}},
)
@ProjectRoles(department_roles=DEPARTMENT_ADMIN)
def set_member_roles(project_id: ProjectId, lan_id: LanId, body: MemberRolesIn, db: Db, p: CurrentUser) -> MemberOut:
    """Make the user's roles in the project exactly `roles`. Takes effect immediately."""
    return _member_out(service.set_member_roles(db, p.lan_id, project_id, lan_id, body.roles))


@router.delete(
    "/projects/{project_id}/members/{lan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_403, 404: {"description": "No such project or user"}},
)
@ProjectRoles(department_roles=DEPARTMENT_ADMIN)
def remove_member(project_id: ProjectId, lan_id: LanId, db: Db, p: CurrentUser) -> Response:
    """Remove the user from the project."""
    service.set_member_roles(db, p.lan_id, project_id, lan_id, [])
    return Response(status_code=status.HTTP_204_NO_CONTENT)
