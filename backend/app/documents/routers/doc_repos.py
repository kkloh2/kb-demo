"""Repository endpoints.

    GET    /api/doc-repos                            docs.repository.list at DOC_HUB root   every active repository
    POST   /api/doc-repos                            Doc Hub admins (docs.repository.create at its root) or platform admins
    GET    /api/doc-repos/deleted                    platform admin
    GET    /api/doc-repos/{id}                       docs.repository.view
    PUT    /api/doc-repos/{id}                       docs.repository.edit      name, description
    PUT    /api/doc-repos/{id}/metadata              docs.repository.edit      [{label, value}]
    DELETE /api/doc-repos/{id}                       access.node.delete        owner only; soft delete
    POST   /api/doc-repos/{id}/restore               platform admin
    GET    /api/doc-repos/{id}/groups                access.members.manage     user groups (names)
    POST   /api/doc-repos/{id}/groups                access.members.manage     {name}
    PUT    /api/doc-repos/{id}/groups/{group_id}     access.members.manage     {name}: rename
    DELETE /api/doc-repos/{id}/groups/{group_id}     access.members.manage     delete (not the default group)
    GET    /api/doc-repos/{id}/members               access.members.manage     members, their groups and roles, team grants
    PUT    /api/doc-repos/{id}/members/{lan_id}      access.members.manage     {groups: [{id, roles}]}
    DELETE /api/doc-repos/{id}/members/{lan_id}      access.members.manage
    PUT    /api/doc-repos/{id}/owner                 access.node.transfer      hand ownership over
    GET    /api/doc-repos/{id}/workflow              docs.repository.edit      the workflow new submissions use, and the choices
    PUT    /api/doc-repos/{id}/workflow              docs.repository.edit      {workflow_id}: choose another
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Response, status

from app.access import service as access
from app.access.authorization import Can, Param, PlatformAdmin, Root
from app.access.catalog import REPO_GROUP_ROLES, P, RoleCode, SystemCode
from app.access.models import AppUser
from app.access.router import member_out
from app.access.schemas import TeamGrantOut
from app.auth.dependencies import CurrentUser
from app.db.session import Db
from app.core.errors import InvalidRequest
from app.documents import metadata, service, workflow_steps
from app.workflows import engine as workflows
from app.documents.schemas import (
    DocRepoAccessOut,
    DocRepoCreate,
    DocRepoIn,
    DocRepoOut,
    GroupIn,
    GroupOut,
    GroupsOut,
    MemberGroupOut,
    MemberGroupsIn,
    MembersOut,
    MetadataPair,
    OwnerIn,
    PersonRef,
    RepoMemberOut,
    RepoWorkflowIn,
    RepoWorkflowOut,
    WorkflowChoice,
    WorkflowStepBrief,
)

router = APIRouter(tags=["doc-repos"])

DocRepoId = Annotated[uuid.UUID, Path(description="Repository id")]
LanId = Annotated[str, Path(min_length=1, max_length=64, description="LAN ID (case-insensitive)")]
DOC_HUB = Root(SystemCode.DOC_HUB)


def at_repo(param: str = "doc_repo_id") -> Param:
    return Param(param, service.repo_node)


def ref(u: AppUser | None) -> PersonRef | None:
    return PersonRef(lan_id=u.lan_id, display_name=u.display_name) if u else None


def repo_out(db: Db, item: service.RepoWithAccess) -> DocRepoOut:
    r, a = item.repo, item.access
    owners = access.holders_of(db, r.hierarchy_node_id, RoleCode.OWNER)
    return DocRepoOut(
        id=r.id, node_id=r.hierarchy_node_id, name=r.node.name, description=r.description,
        metadata=[MetadataPair(label=e.field.label, value=e.value) for e in metadata.node_entries(db, r.hierarchy_node_id)],
        owner=ref(owners[0]) if owners else None, created_by=ref(r.created_by),
        created_at=r.created_at, updated_at=r.updated_at, deleted_at=r.node.deleted_at,
        document_count=item.document_count,
        access=DocRepoAccessOut(
            roles=sorted(a.roles), view=a.has(P.REPO_VIEW), edit=a.has(P.REPO_EDIT),
            manage_members=a.has(P.MEMBERS_MANAGE), delete=a.has(P.NODE_DELETE), transfer=a.has(P.NODE_TRANSFER),
            upload=a.has(P.DOC_UPLOAD), activity=a.has(P.AUDIT_VIEW)),
    )


def me(db: Db, p: CurrentUser) -> AppUser:
    return access.require_user(db, p.lan_id)


@router.get("/doc-repos", response_model=list[DocRepoOut])
@Can(P.REPO_LIST, at=DOC_HUB)
def list_doc_repos(db: Db, p: CurrentUser) -> list[DocRepoOut]:
    """Every repository, most recently updated first. `access.view` says whether the caller can open it."""
    return [repo_out(db, i) for i in service.list_repos(db, me(db, p))]


@router.post("/doc-repos", response_model=DocRepoOut, status_code=status.HTTP_201_CREATED,
             responses={409: {"description": "A repository with this name exists"}})
@Can(P.REPO_CREATE, at=DOC_HUB)  # Doc Hub admins
@PlatformAdmin  # or platform admins
def create_doc_repo(body: DocRepoCreate, db: Db, p: CurrentUser, response: Response) -> DocRepoOut:
    """Create a repository. You become its owner; the default team grants apply."""
    user = me(db, p)
    fields = [(m.label, m.value) for m in body.metadata] if body.metadata is not None else None
    repo = service.create_repo(db, user, body.name, body.description, fields)
    response.headers["Location"] = f"/api/doc-repos/{repo.id}"
    return repo_out(db, service.with_access(db, user, repo))


@router.get("/doc-repos/deleted", response_model=list[DocRepoOut])
@PlatformAdmin
def list_deleted(db: Db, p: CurrentUser) -> list[DocRepoOut]:
    """Deleted repositories, newest first (platform admins can restore them)."""
    user = me(db, p)
    return [repo_out(db, service.with_access(db, user, r)) for r in service.list_deleted(db)]


@router.get("/doc-repos/{doc_repo_id}", response_model=DocRepoOut)
@Can(P.REPO_VIEW, at=at_repo())
def get_doc_repo(doc_repo_id: DocRepoId, db: Db, p: CurrentUser) -> DocRepoOut:
    user = me(db, p)
    return repo_out(db, service.with_access(db, user, service.get_repo(db, doc_repo_id)))


@router.put("/doc-repos/{doc_repo_id}", response_model=DocRepoOut)
@Can(P.REPO_EDIT, at=at_repo())
def update_doc_repo(doc_repo_id: DocRepoId, body: DocRepoIn, db: Db, p: CurrentUser) -> DocRepoOut:
    user = me(db, p)
    repo = service.update_repo(db, user, service.get_repo(db, doc_repo_id), body.name, body.description)
    return repo_out(db, service.with_access(db, user, repo))


@router.put("/doc-repos/{doc_repo_id}/metadata", response_model=list[MetadataPair])
@Can(P.REPO_EDIT, at=at_repo())
def set_metadata(doc_repo_id: DocRepoId, body: list[MetadataPair], db: Db, p: CurrentUser) -> list[MetadataPair]:
    """Make the repository's metadata fields exactly these, in this order. Documents not yet approved
    get the new values (unless the maker changed them); approved ones keep theirs."""
    repo = service.get_repo(db, doc_repo_id)
    service.set_repo_metadata(db, me(db, p), repo, [(m.label, m.value) for m in body])
    return [MetadataPair(label=e.field.label, value=e.value) for e in metadata.node_entries(db, repo.hierarchy_node_id)]


@router.delete("/doc-repos/{doc_repo_id}", status_code=status.HTTP_204_NO_CONTENT)
@Can(P.NODE_DELETE, at=at_repo())
def delete_doc_repo(doc_repo_id: DocRepoId, db: Db, p: CurrentUser) -> Response:
    """Soft delete (owner only): it's hidden and its pending approvals are cancelled; everything is kept."""
    service.delete_repo(db, me(db, p), service.get_repo(db, doc_repo_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/doc-repos/{doc_repo_id}/restore", response_model=DocRepoOut)
@PlatformAdmin
def restore_doc_repo(doc_repo_id: DocRepoId, db: Db, p: CurrentUser) -> DocRepoOut:
    user = me(db, p)
    repo = service.restore_repo(db, user, service.get_repo(db, doc_repo_id, include_deleted=True))
    return repo_out(db, service.with_access(db, user, repo))


# --------------------------------------------------------------------------- members


def group_out(v: access.GroupView) -> GroupOut:
    g = v.group
    return GroupOut(id=g.id, name=g.name, default=v.default, member_count=v.member_count,
                    created_at=g.created_at, updated_at=g.updated_at)


def repo_member_out(m: access.Member) -> RepoMemberOut:
    return RepoMemberOut(**member_out(m).model_dump(), added_at=m.added_at, updated_at=m.updated_at,
                         groups=[MemberGroupOut(id=mg.group.id, name=mg.group.name, roles=mg.roles) for mg in m.groups])


def _group_view(db: Db, node_id: uuid.UUID, group_id: uuid.UUID) -> GroupOut:
    return group_out(next(v for v in access.repo_groups(db, node_id) if v.group.id == group_id))


@router.get("/doc-repos/{doc_repo_id}/groups", response_model=GroupsOut)
@Can(P.MEMBERS_MANAGE, at=at_repo())
def list_groups(doc_repo_id: DocRepoId, db: Db) -> GroupsOut:
    node_id = service.get_repo(db, doc_repo_id).hierarchy_node_id
    return GroupsOut(groups=[group_out(v) for v in access.repo_groups(db, node_id)],
                     grantable_roles=[r.value for r in REPO_GROUP_ROLES])


@router.post("/doc-repos/{doc_repo_id}/groups", response_model=GroupOut, status_code=status.HTTP_201_CREATED,
             responses={409: {"description": "Name taken"}})
@Can(P.MEMBERS_MANAGE, at=at_repo())
def create_group(doc_repo_id: DocRepoId, body: GroupIn, db: Db, p: CurrentUser) -> GroupOut:
    """A new user group (a name); people are put in it with their own roles."""
    node = service.get_repo(db, doc_repo_id).node
    group = access.create_group(db, me(db, p), node, body.name)
    return _group_view(db, node.id, group.id)


@router.put("/doc-repos/{doc_repo_id}/groups/{group_id}", response_model=GroupOut,
            responses={409: {"description": "Name taken"}})
@Can(P.MEMBERS_MANAGE, at=at_repo())
def update_group(doc_repo_id: DocRepoId, group_id: uuid.UUID, body: GroupIn, db: Db, p: CurrentUser) -> GroupOut:
    """Rename the group."""
    node = service.get_repo(db, doc_repo_id).node
    group = access.update_group(db, me(db, p), node, group_id, body.name)
    return _group_view(db, node.id, group.id)


@router.delete("/doc-repos/{doc_repo_id}/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT,
               responses={409: {"description": "The default group"}})
@Can(P.MEMBERS_MANAGE, at=at_repo())
def delete_group(doc_repo_id: DocRepoId, group_id: uuid.UUID, db: Db, p: CurrentUser) -> Response:
    """Delete the user group: everyone in it loses the roles they held in it, at once."""
    access.delete_group(db, me(db, p), service.get_repo(db, doc_repo_id).node, group_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/doc-repos/{doc_repo_id}/members", response_model=MembersOut)
@Can(P.MEMBERS_MANAGE, at=at_repo())
def list_members(doc_repo_id: DocRepoId, db: Db) -> MembersOut:
    node_id = service.get_repo(db, doc_repo_id).hierarchy_node_id
    return MembersOut(
        members=[repo_member_out(m) for m in access.list_members(db, node_id)],
        team_grants=[TeamGrantOut(team=g.team_code, team_name=g.team_name, role=g.role, from_default=g.from_default)
                     for g in access.team_grants(db, node_id)],
        groups=[group_out(v) for v in access.repo_groups(db, node_id)],
        grantable_roles=[r.value for r in REPO_GROUP_ROLES],
    )


@router.put("/doc-repos/{doc_repo_id}/members/{lan_id}", response_model=RepoMemberOut)
@Can(P.MEMBERS_MANAGE, at=at_repo())
def set_member_groups(doc_repo_id: DocRepoId, lan_id: LanId, body: MemberGroupsIn, db: Db,
                      p: CurrentUser) -> RepoMemberOut:
    """Make the person's user groups and roles here exactly these. Takes effect at once."""
    node = service.get_repo(db, doc_repo_id).node
    assignments = {g.id: g.roles for g in body.groups}
    return repo_member_out(access.set_member_groups(db, me(db, p), node, lan_id, assignments))


@router.delete("/doc-repos/{doc_repo_id}/members/{lan_id}", status_code=status.HTTP_204_NO_CONTENT)
@Can(P.MEMBERS_MANAGE, at=at_repo())
def remove_member(doc_repo_id: DocRepoId, lan_id: LanId, db: Db, p: CurrentUser) -> Response:
    """Take the person out of every user group here (the owner stays: ownership moves only by hand-over)."""
    access.set_member_groups(db, me(db, p), service.get_repo(db, doc_repo_id).node, lan_id, {})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/doc-repos/{doc_repo_id}/owner", status_code=status.HTTP_204_NO_CONTENT)
@Can(P.NODE_TRANSFER, at=at_repo())
def transfer(doc_repo_id: DocRepoId, body: OwnerIn, db: Db, p: CurrentUser) -> Response:
    """Hand ownership to someone else; you stay as an admin."""
    access.transfer_ownership(db, me(db, p), service.get_repo(db, doc_repo_id).node, body.lan_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- the repository's workflow


def _choice(db: Db, wf) -> WorkflowChoice | None:
    latest = workflows.latest_version(db, wf.id)
    if latest is None:
        return None
    steps = latest.definition.get("steps", [])
    return WorkflowChoice(id=wf.id, code=wf.code, name=wf.name, version=latest.version, steps=[
        WorkflowStepBrief(id=x["id"], name=x["name"], type=x["type"], user_group=(x.get("role") or {}).get("user_group"),
                          role=(x.get("role") or {}).get("role"), on=x.get("on", {})) for x in steps])


def _repo_workflow(db: Db, node_id: uuid.UUID) -> RepoWorkflowOut:
    current = workflows.bound_definition(db, node_id, workflow_steps.KIND)
    options = [c for c in (_choice(db, wf) for wf in workflows.definitions(db, workflow_steps.KIND)) if c]
    db.commit()  # the shipped default flow, if it was just created
    chosen = _choice(db, current) if current else None
    groups = {s.user_group for s in (chosen.steps if chosen else []) if s.user_group}
    missing = sorted(g for g in groups if access.group_named(db, node_id, g) is None)
    return RepoWorkflowOut(current=chosen, options=options, missing_groups=missing)


@router.get("/doc-repos/{doc_repo_id}/workflow", response_model=RepoWorkflowOut)
@Can(P.REPO_EDIT, at=at_repo())
def get_repo_workflow(doc_repo_id: DocRepoId, db: Db) -> RepoWorkflowOut:
    return _repo_workflow(db, service.get_repo(db, doc_repo_id).hierarchy_node_id)


@router.put("/doc-repos/{doc_repo_id}/workflow", response_model=RepoWorkflowOut,
            responses={404: {"description": "No such workflow"}, 422: {"description": "Not a document workflow"}})
@Can(P.REPO_EDIT, at=at_repo())
def set_repo_workflow(doc_repo_id: DocRepoId, body: RepoWorkflowIn, db: Db, p: CurrentUser) -> RepoWorkflowOut:
    """New submissions here use this workflow (its latest version). Requests already running keep theirs."""
    node_id = service.get_repo(db, doc_repo_id).hierarchy_node_id
    wf = workflows.get_definition(db, body.workflow_id)
    if wf.kind != workflow_steps.KIND:
        raise InvalidRequest(f"{wf.name} isn't a document workflow.")
    user = me(db, p)
    previous = workflows.bound_definition(db, node_id, workflow_steps.KIND)
    workflows.bind(db, node_id, wf.id, user.id)
    if previous is None or previous.id != wf.id:
        access.record(db, user, "REPO_WORKFLOW_SET", "node", str(node_id), node_id,
                      {"before": previous.code if previous else None, "after": wf.code,
                       "version": workflows.latest_version(db, wf.id).version}, source_system="WORKFLOWS")
    db.commit()
    return _repo_workflow(db, node_id)
