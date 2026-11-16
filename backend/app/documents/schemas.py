import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.access.schemas import MemberOut, TeamGrantOut


class PersonRef(BaseModel):
    lan_id: str
    display_name: str


class MetadataPair(BaseModel):
    label: str = Field(min_length=1, max_length=64, description='e.g. "Country"')
    value: str = Field(default="", max_length=512, description='e.g. "Singapore"')


class DocRepoIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)


class DocRepoCreate(DocRepoIn):
    metadata: list[MetadataPair] | None = Field(
        default=None, description="The repository's metadata fields and values. Omitted: none.")


class DocRepoAccessOut(BaseModel):
    """What the caller may do here, for the UI. The server checks again on every request."""

    roles: list[str]
    view: bool = Field(description="Open the repository")
    edit: bool = Field(description="Edit its name, description and metadata fields")
    manage_members: bool
    delete: bool = Field(description="Owner only")
    transfer: bool = Field(description="Hand ownership over (owner only)")
    upload: bool
    activity: bool = Field(description="See the repository's activity (audit.trail.view)")


class DocRepoOut(BaseModel):
    id: uuid.UUID
    node_id: uuid.UUID
    name: str
    description: str
    metadata: list[MetadataPair]
    owner: PersonRef | None
    created_by: PersonRef | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    document_count: int = Field(description="Documents in it the caller may see")
    access: DocRepoAccessOut


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=64, description='e.g. "default" or "Credit reviewers"')


class GroupOut(BaseModel):
    id: uuid.UUID
    name: str
    default: bool = Field(description="The repository's default group (holds the owner)")
    member_count: int
    created_at: datetime
    updated_at: datetime


class GroupsOut(BaseModel):
    groups: list[GroupOut]
    grantable_roles: list[str] = Field(description="Roles a person can be given in a user group")


class MemberGroupOut(BaseModel):
    id: uuid.UUID
    name: str
    roles: list[str] = Field(description="Their roles in it")


class RepoMemberOut(MemberOut):
    groups: list[MemberGroupOut] = Field(description="The repository's user groups they're in")
    added_at: datetime | None = Field(description="When they joined")
    updated_at: datetime | None = Field(description="The latest change to their membership or own roles")


class GroupRolesIn(BaseModel):
    id: uuid.UUID = Field(description="A user group of the repository")
    roles: list[str] = Field(description='Their roles in it, e.g. ["MAKER"]. [] takes them out of it.')


class MemberGroupsIn(BaseModel):
    groups: list[GroupRolesIn] = Field(description="Their user groups and roles here, exactly these. [] takes them "
                                                   "out of every group (the owner keeps Owner).")


class MembersOut(BaseModel):
    members: list[RepoMemberOut]
    team_grants: list[TeamGrantOut] = Field(description="Teams with read-only access (set by platform admins)")
    groups: list[GroupOut] = Field(description="The repository's user groups, to choose from")
    grantable_roles: list[str] = Field(description="Roles a person can be given in a user group")


class OwnerIn(BaseModel):
    lan_id: str = Field(min_length=1, max_length=64)


# --------------------------------------------------------------------------- documents


class MetadataEntryOut(BaseModel):
    field_id: uuid.UUID
    label: str
    value: str | None = Field(description="null when the maker removed the field")
    state: str = Field(description="inherited, overridden, removed, own (the document's own field) or suggested")
    inherited_value: str | None = Field(description="For overridden or removed: the repository's current value")
    from_node: str | None = Field(description="Where an inherited value comes from")
    overridable: bool


class DecisionRef(BaseModel):
    decision: str = Field(description="APPROVED, REJECTED or CHANGES_REQUESTED")
    comment: str | None
    decided_by: PersonRef | None
    decided_at: datetime
    round: int


class DocumentActionsOut(BaseModel):
    edit: bool
    submit: bool
    delete: bool


class DocumentOut(BaseModel):
    id: uuid.UUID
    doc_repo_id: uuid.UUID
    folder: str
    filename: str
    content_type: str | None
    size_bytes: int
    status: str = Field(description="draft, pending_approval, changes_requested, approved or rejected")
    maker: PersonRef | None
    created_at: datetime
    updated_at: datetime
    submitted_at: datetime | None
    last_decision: DecisionRef | None
    metadata: list[MetadataEntryOut]
    actions: DocumentActionsOut


class InheritedChange(BaseModel):
    field_id: uuid.UUID
    state: str = Field(description="inherit, override or remove")
    value: str | None = Field(default=None, max_length=512)


class MetadataUpdate(BaseModel):
    """`inherited`: what to do with each repository field (fields left out stay as they are).
    `own`: the document's own fields, exactly these."""

    inherited: list[InheritedChange] = Field(default_factory=list)
    own: list[MetadataPair] = Field(default_factory=list)


class DocumentIds(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class SkippedOut(BaseModel):
    id: uuid.UUID
    filename: str
    reason: str


class BulkOut(BaseModel):
    done: list[DocumentOut]
    skipped: list[SkippedOut]


# --------------------------------------------------------------------------- the repository's workflow


class WorkflowStepBrief(BaseModel):
    id: str
    name: str
    type: str
    user_group: str | None
    role: str | None
    on: dict[str, str] = Field(description='Outcome -> next step id or "END:<WORD>"')


class WorkflowChoice(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    version: int = Field(description="Its latest published version (new requests start on it)")
    steps: list[WorkflowStepBrief]


class RepoWorkflowOut(BaseModel):
    current: WorkflowChoice | None = Field(description="The workflow new submissions here use")
    options: list[WorkflowChoice] = Field(description="Every Doc Hub document workflow there is to choose from")
    missing_groups: list[str] = Field(description="User groups the current workflow names that this repository "
                                                  "doesn't have yet (its steps can't be met until they exist)")


class RepoWorkflowIn(BaseModel):
    workflow_id: uuid.UUID
