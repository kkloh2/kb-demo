from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.auth import DepartmentOut

KbAccess = Literal["admin", "department", "granted"]


class UserBrief(BaseModel):
    username: str
    display_name: str


class KnowledgeBaseOut(BaseModel):
    id: str
    name: str
    description: str
    department: DepartmentOut
    admin: UserBrief | None = Field(description="Department admin named when the KB was created")
    access: KbAccess = Field(
        description="admin: you manage it; department: your department's; granted: shared with you"
    )
    updated_at: datetime
    favorite: bool


class KbCapabilities(BaseModel):
    view_documents: bool
    view_unapproved: bool
    upload: bool
    review: bool
    edit: bool


class KnowledgeBaseDetail(KnowledgeBaseOut):
    capabilities: KbCapabilities


class KnowledgeBaseDirectoryEntry(BaseModel):
    id: str
    name: str
    description: str
    department: DepartmentOut
    access: KbAccess | None
    request_pending: bool


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)
    department_code: str = Field(min_length=1, max_length=32)
    admin_lan_id: str = Field(
        min_length=1, max_length=64,
        description="A user in that department. Made department admin if they aren't one already.",
    )


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=2000)


class ViewerOut(BaseModel):
    username: str
    display_name: str
    department: DepartmentOut | None
    granted_at: datetime
