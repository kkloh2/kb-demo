from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.auth import DepartmentOut


class UserSummary(BaseModel):
    username: str
    display_name: str
    title: str
    email: str
    department: DepartmentOut | None
    roles: list[str] = Field(description="Assigned roles (the implicit viewer role is not listed)")
    is_active: bool


class DepartmentWithCounts(DepartmentOut):
    members: int
    knowledge_bases: int
    admins: list[str]


class DepartmentCreate(BaseModel):
    code: str = Field(min_length=2, max_length=16, description="e.g. TREASURY")
    name: str = Field(min_length=1, max_length=128)


class UserCreate(BaseModel):
    lan_id: str = Field(min_length=2, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    email: str = Field(min_length=3, max_length=256)
    title: str = Field(default="", max_length=128)
    password: str = Field(min_length=1, max_length=256, description="Initial password (at least 8 characters)")
    department_code: str | None = Field(
        default=None, description="Required for system admins; ignored (own department) for department admins"
    )
    role: str | None = Field(
        default=None,
        description="System admins: always department_admin. Department admins: viewer (default), maker or checker.",
    )


class RoleOut(BaseModel):
    code: str
    name: str
    description: str
    scope: str
    assignable: bool
    permissions: list[str]


class PermissionOut(BaseModel):
    code: str
    description: str
    roles: list[str]


class UserRef(BaseModel):
    username: str
    display_name: str
    department: DepartmentOut | None


class AccessRequestCreate(BaseModel):
    reason: str = Field(default="", max_length=1000)


class AccessDecision(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class AccessRequestOut(BaseModel):
    id: int
    kb_id: str
    kb_name: str
    kb_department: DepartmentOut
    requester: UserRef
    reason: str
    status: str
    created_at: datetime
    decided_by: str | None
    decided_at: datetime | None
    decision_note: str | None
