from datetime import date, datetime

from pydantic import BaseModel, Field


class DepartmentRef(BaseModel):
    code: str
    name: str


class ProjectIn(BaseModel):
    """Create (POST) or replace (PUT) a project: name, description and base metadata."""

    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)
    country: str = Field(default="", max_length=64, description='e.g. "Singapore"')
    business_unit: str = Field(default="", max_length=128, description='e.g. "Consumer Banking"')
    purpose: str = Field(default="", max_length=128, description='e.g. "Credit card", "Loan"')
    valid_till: date | None = Field(default=None, description="Metadata only: approved documents stay viewable")


class ProjectAccessOut(BaseModel):
    """What the caller can do with the project, for the UI. The server checks again on each request."""

    manage: bool = Field(description="Edit or delete the project and manage its members (department admin)")
    view_documents: bool
    upload: bool = Field(description="Project maker")
    review: bool = Field(description="Project checker")
    project_roles: list[str] = Field(description="The caller's roles in this project")


class ProjectOut(BaseModel):
    id: int
    name: str
    description: str
    department: DepartmentRef
    country: str
    business_unit: str
    purpose: str
    valid_till: date | None
    created_by: str | None = Field(description="Display name of whoever created it")
    created_at: datetime
    updated_at: datetime
    access: ProjectAccessOut


class MemberRolesIn(BaseModel):
    roles: list[str] = Field(description='Complete list from MAKER, CHECKER, VIEWER, e.g. ["CHECKER"]. [] removes them.')


class MemberOut(BaseModel):
    lan_id: str
    display_name: str
    email: str
    title: str
    roles: list[str]


# --------------------------------------------------------------------------- metadata fields


class FieldDef(BaseModel):
    """A metadata field the project's documents fill in."""

    key: str = Field(default="", max_length=64, description="Derived from the label when empty, e.g. product_code")
    label: str = Field(min_length=1, max_length=128, description='e.g. "Product code"')
    type: str = Field(default="text", description="text, date or select")
    options: list[str] = Field(default_factory=list, description="For select fields")
    required: bool = Field(default=False, description="Must be filled in before submitting")


# --------------------------------------------------------------------------- documents


class PersonRef(BaseModel):
    lan_id: str
    display_name: str


class BaseMetadata(BaseModel):
    country: str = ""
    business_unit: str = ""
    purpose: str = ""
    valid_till: date | None = None


class DocumentActionsOut(BaseModel):
    edit: bool
    submit: bool
    review: bool
    delete: bool


class DocumentOut(BaseModel):
    id: int
    project_id: int
    folder: str = Field(description='Path inside the project, e.g. "Policies/2026"; "" for the top level')
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
    base: BaseMetadata
    base_overrides: list[str] = Field(description="Base fields the maker changed from the project's values")
    fields: dict[str, str] = Field(description="Values of the project's fields")
    extra: dict[str, str] = Field(description="Fields the maker added")
    ai_metadata: dict = Field(description="Phase 2: extracted by an LLM")
    missing_required: list[str] = Field(description="Labels of required fields not filled in yet")
    actions: DocumentActionsOut


class DocumentList(BaseModel):
    documents: list[DocumentOut]
    fields: list[FieldDef]


class MetadataUpdate(BaseModel):
    """Replace the document's metadata."""

    base: BaseMetadata
    fields: dict[str, str] = Field(default_factory=dict)
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
