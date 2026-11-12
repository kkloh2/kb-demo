from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DepartmentRef(BaseModel):
    code: str
    name: str


class DepartmentMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")  # only these keys

    department: str = Field(default="", max_length=128)
    business_unit: str = Field(default="", max_length=128, description='e.g. "Consumer Banking"')
    country: str = Field(default="", max_length=64, description='e.g. "Singapore"')


class MetadataPair(BaseModel):
    """One repository metadata entry: plain text key and value."""

    key: str = Field(min_length=1, max_length=64, description='e.g. "Product code"')
    value: str = Field(default="", max_length=512, description='e.g. "VISA-PLAT"')


class DocRepoIn(BaseModel):
    """Create (POST) or replace (PUT) a doc-repo: name, description and department metadata."""

    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)
    department_metadata: DepartmentMetadata = Field(
        default_factory=DepartmentMetadata,
        description="Copied onto each document. An empty department becomes the department's name.")


class DocRepoAccessOut(BaseModel):
    """What the caller can do with the doc-repo, for the UI. The server checks again on each request."""

    manage: bool = Field(description="Edit or delete the doc-repo and manage its members (department admin)")
    view_details: bool = Field(description="Open its page: a doc-repo role, or department VIEWER / admin")
    view_documents: bool
    upload: bool = Field(description="Doc-repo maker")
    review: bool = Field(description="Doc-repo checker")
    doc_repo_roles: list[str] = Field(description="The caller's roles in this doc-repo")


class DocRepoOut(BaseModel):
    id: int
    name: str
    description: str
    department: DepartmentRef
    department_metadata: DepartmentMetadata
    repository_metadata: list[MetadataPair]
    created_by: str | None = Field(description="Display name of whoever created it")
    created_at: datetime
    updated_at: datetime
    document_count: int = Field(description="Documents in it that the caller may see")
    access: DocRepoAccessOut


class MemberRolesIn(BaseModel):
    roles: list[str] = Field(description='Complete list from MAKER, CHECKER, VIEWER, e.g. ["CHECKER"]. [] removes them.')


class MemberOut(BaseModel):
    lan_id: str
    display_name: str
    email: str
    title: str
    roles: list[str]


# --------------------------------------------------------------------------- documents


class PersonRef(BaseModel):
    lan_id: str
    display_name: str


class DocumentActionsOut(BaseModel):
    edit: bool
    submit: bool
    review: bool
    delete: bool


class DocumentOut(BaseModel):
    id: int
    doc_repo_id: int
    folder: str = Field(description='Path inside the doc-repo, e.g. "Policies/2026"; "" for the top level')
    filename: str
    content_type: str | None
    size_bytes: int
    status: str = Field(description="draft, pending_approval, approved or rejected")
    maker: PersonRef | None
    checker: PersonRef | None
    created_at: datetime
    updated_at: datetime
    submitted_at: datetime | None
    decided_at: datetime | None
    rejection_reason: str | None
    department_metadata: DepartmentMetadata
    department_overrides: list[str] = Field(description="Department metadata keys the maker changed from the doc-repo's")
    repository_metadata: dict[str, str] = Field(description="Values for the doc-repo's repository metadata keys")
    repository_overrides: list[str] = Field(description="Repository metadata keys the maker changed from the doc-repo's")
    extra: dict[str, str] = Field(description="Fields the maker added")
    ai_metadata: dict = Field(description="Phase 2: extracted by an LLM")
    actions: DocumentActionsOut


class DocumentList(BaseModel):
    documents: list[DocumentOut]
    repository_metadata: list[MetadataPair] = Field(description="The doc-repo's current keys and values")


class MetadataUpdate(BaseModel):
    """Replace the document's metadata."""

    department_metadata: DepartmentMetadata
    repository_metadata: dict[str, str] = Field(default_factory=dict)
    extra: dict[str, str] = Field(default_factory=dict)


class DocumentIds(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)


class ReviewIn(DocumentIds):
    decision: str = Field(description="approve or reject")
    reason: str = Field(default="", max_length=2000, description="Required when rejecting")


class SkippedOut(BaseModel):
    id: int
    filename: str
    reason: str


class BulkOut(BaseModel):
    """Documents the action applied to, and the ones it skipped with why."""

    done: list[DocumentOut]
    skipped: list[SkippedOut]
