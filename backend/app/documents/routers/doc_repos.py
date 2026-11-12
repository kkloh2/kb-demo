"""Doc-repo endpoints.

    GET    /api/doc-repos                              PUBLIC system role   every doc-repo (opening one needs more)
    GET    /api/doc-repos/departments                  signed in        departments the caller can create doc-repos in
    POST   /api/departments/{code}/doc-repos           that department's admin
    GET    /api/doc-repos/{doc_repo_id}                 department VIEWER or admin, or any doc-repo role
    PUT    /api/doc-repos/{doc_repo_id}                 the department's admin   name, description, department metadata
    DELETE /api/doc-repos/{doc_repo_id}                 the department's admin
    GET    /api/doc-repos/{doc_repo_id}/members         the department's admin
    PUT    /api/doc-repos/{doc_repo_id}/members/{lan_id}   the department's admin   {roles: [MAKER|CHECKER|VIEWER]}
    DELETE /api/doc-repos/{doc_repo_id}/members/{lan_id}   the department's admin
"""

from typing import Annotated

from fastapi import APIRouter, Path, Response, status

from app.auth.dependencies import CurrentUser
from app.auth.identity import Principal
from app.db.session import Db
from app.documents import service
from app.documents.documents import visible_counts
from app.documents.authorization import DocRepoRoles
from app.documents.models import DocRepo
from app.documents.schemas import (
    DepartmentMetadata,
    DepartmentRef,
    MemberOut,
    MetadataPair,
    MemberRolesIn,
    DocRepoAccessOut,
    DocRepoIn,
    DocRepoOut,
)
from app.users.authorization import OrgUnitRoles, SystemRoles

router = APIRouter(tags=["doc-repos"])

DocRepoId = Annotated[int, Path(ge=1, description="Doc-repo id")]
DepartmentCode = Annotated[str, Path(min_length=1, max_length=32, description='e.g. "RISK" (case-insensitive)')]
LanId = Annotated[str, Path(min_length=1, max_length=64, description="LAN ID (case-insensitive)")]

DEPARTMENT_ADMIN = ("DEPARTMENT_ADMIN",)
ANY_DOC_REPO_ROLE = ("MAKER", "CHECKER", "VIEWER")
_403 = {403: {"description": "Caller lacks the required role"}}
_404 = {404: {"description": "No such doc-repo"}}


def _out(doc_repo: DocRepo, access: service.DocRepoAccess, document_count: int) -> DocRepoOut:
    return DocRepoOut(
        id=doc_repo.id,
        name=doc_repo.name,
        description=doc_repo.description,
        department=DepartmentRef(code=doc_repo.department.code, name=doc_repo.department.name),
        department_metadata=DepartmentMetadata(**doc_repo.department_metadata),
        repository_metadata=[MetadataPair(**m) for m in doc_repo.repository_metadata],
        created_by=doc_repo.created_by.display_name if doc_repo.created_by else None,
        created_at=doc_repo.created_at,
        updated_at=doc_repo.updated_at,
        document_count=document_count,
        access=DocRepoAccessOut(
            manage=access.manage,
            view_details=access.view_details,
            view_documents=access.view_documents,
            upload=access.upload,
            review=access.review,
            doc_repo_roles=[r for r in ANY_DOC_REPO_ROLE if r in access.doc_repo_roles],
        ),
    )


def _out_for(db: Db, p: Principal, doc_repo: DocRepo) -> DocRepoOut:
    access = service.access_to(db, p, doc_repo)
    return _out(doc_repo, access, visible_counts(db, [(doc_repo.id, access)])[doc_repo.id])


# --------------------------------------------------------------------------- doc-repos


@router.get("/doc-repos", response_model=list[DocRepoOut], responses=_403)
@SystemRoles("PUBLIC")
def list_doc_repos(db: Db, p: CurrentUser) -> list[DocRepoOut]:
    """Every doc-repo, most recently updated first, for callers with the PUBLIC system role.
    `access.view_details` says whether the caller can open it."""
    items = service.list_doc_repos(db, p)
    counts = visible_counts(db, [(i.doc_repo.id, i.access) for i in items])
    return [_out(i.doc_repo, i.access, counts[i.doc_repo.id]) for i in items]


@router.get("/doc-repos/departments", response_model=list[DepartmentRef])
def creatable_departments(db: Db, p: CurrentUser) -> list[DepartmentRef]:
    """Departments the caller administers, i.e. can create doc-repos in."""
    return [DepartmentRef(code=d.code, name=d.name) for d in service.manageable_departments(db, p)]


@router.post(
    "/departments/{code}/doc-repos",
    status_code=status.HTTP_201_CREATED,
    response_model=DocRepoOut,
    responses={**_403, 404: {"description": "No such department"},
               409: {"description": "The department already has a doc-repo with this name"}},
)
@OrgUnitRoles("DEPARTMENT_ADMIN", department="code")
def create_doc_repo(code: DepartmentCode, body: DocRepoIn, db: Db, p: CurrentUser, response: Response) -> DocRepoOut:
    """Create a doc-repo in the department, with its department metadata."""
    doc_repo = service.create_doc_repo(db, p.lan_id, code, service.DocRepoFields(**body.model_dump()))
    response.headers["Location"] = f"/api/doc-repos/{doc_repo.id}"
    return _out_for(db, p, doc_repo)


@router.get("/doc-repos/{doc_repo_id}", response_model=DocRepoOut, responses={**_403, **_404})
@DocRepoRoles(*ANY_DOC_REPO_ROLE, department_roles=("DEPARTMENT_ADMIN", "VIEWER"))
def get_doc_repo(doc_repo_id: DocRepoId, db: Db, p: CurrentUser) -> DocRepoOut:
    """One doc-repo, with what the caller can do with it."""
    return _out_for(db, p, service.get_doc_repo(db, doc_repo_id))


@router.put(
    "/doc-repos/{doc_repo_id}",
    response_model=DocRepoOut,
    responses={**_403, **_404, 409: {"description": "The department already has a doc-repo with this name"}},
)
@DocRepoRoles(department_roles=DEPARTMENT_ADMIN)
def update_doc_repo(doc_repo_id: DocRepoId, body: DocRepoIn, db: Db, p: CurrentUser) -> DocRepoOut:
    """Replace the doc-repo's name, description and department metadata."""
    doc_repo = service.update_doc_repo(db, doc_repo_id, service.DocRepoFields(**body.model_dump()))
    return _out_for(db, p, doc_repo)


@router.delete("/doc-repos/{doc_repo_id}", status_code=status.HTTP_204_NO_CONTENT, responses={**_403, **_404})
@DocRepoRoles(department_roles=DEPARTMENT_ADMIN)
def delete_doc_repo(doc_repo_id: DocRepoId, db: Db) -> Response:
    """Delete the doc-repo and its members."""
    service.delete_doc_repo(db, doc_repo_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- members


def _member_out(m: service.Member) -> MemberOut:
    return MemberOut(lan_id=m.user.lan_id, display_name=m.user.display_name, email=m.user.email,
                     title=m.user.title, roles=m.roles)


@router.get("/doc-repos/{doc_repo_id}/members", response_model=list[MemberOut], responses={**_403, **_404})
@DocRepoRoles(department_roles=DEPARTMENT_ADMIN)
def list_members(doc_repo_id: DocRepoId, db: Db) -> list[MemberOut]:
    """The doc-repo's members and their roles. The department's admin isn't listed: they're a viewer
    of every doc-repo by default."""
    return [_member_out(m) for m in service.list_members(db, doc_repo_id)]


@router.put(
    "/doc-repos/{doc_repo_id}/members/{lan_id}",
    response_model=MemberOut,
    responses={**_403, 404: {"description": "No such doc-repo or user"},
               409: {"description": "MAKER and CHECKER together"}},
)
@DocRepoRoles(department_roles=DEPARTMENT_ADMIN)
def set_member_roles(doc_repo_id: DocRepoId, lan_id: LanId, body: MemberRolesIn, db: Db, p: CurrentUser) -> MemberOut:
    """Make the user's roles in the doc-repo exactly `roles`. Takes effect immediately."""
    return _member_out(service.set_member_roles(db, p.lan_id, doc_repo_id, lan_id, body.roles))


@router.delete(
    "/doc-repos/{doc_repo_id}/members/{lan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_403, 404: {"description": "No such doc-repo or user"}},
)
@DocRepoRoles(department_roles=DEPARTMENT_ADMIN)
def remove_member(doc_repo_id: DocRepoId, lan_id: LanId, db: Db, p: CurrentUser) -> Response:
    """Remove the user from the doc-repo."""
    service.set_member_roles(db, p.lan_id, doc_repo_id, lan_id, [])
    return Response(status_code=status.HTTP_204_NO_CONTENT)
