import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PersonOut(BaseModel):
    lan_id: str
    display_name: str
    email: str
    title: str


class NodeAccessOut(BaseModel):
    system: str = Field(description='e.g. "DOC_HUB"')
    node_id: uuid.UUID
    node_code: str
    node_name: str
    node_type: str
    path: str
    roles: list[str]
    permissions: list[str]


class MyAccessOut(BaseModel):
    """What the signed-in person may do, for the UI. The server checks again on every request."""

    system_roles: dict[str, list[str]] = Field(description="{system: roles at its root}; [] = roles only below the root")
    platform_admin: bool
    can_decide: bool = Field(description="Holds a deciding role somewhere: show the Approvals page")
    nodes: list[NodeAccessOut]


class UserOut(PersonOut):
    directory_department: str
    status: str = Field(description="ACTIVE or INACTIVE (access switched off)")
    platform_admin: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UserIn(BaseModel):
    """Every field is optional: a new user given only a LAN ID gets placeholder details, which the
    directory fills in at their first sign-in. Left out on an update: unchanged."""

    display_name: str | None = Field(default=None, max_length=128)
    email: str | None = Field(default=None, max_length=256)
    title: str | None = Field(default=None, max_length=128)
    directory_department: str | None = Field(default=None, max_length=128)
    platform_admin: bool | None = None


class ActiveIn(BaseModel):
    active: bool


class RoleOut(BaseModel):
    code: str
    name: str
    description: str
    permissions: list[str]


class PermissionOut(BaseModel):
    code: str
    name: str


class RolesOut(BaseModel):
    roles: list[RoleOut]
    permissions: list[PermissionOut]


class MemberOut(PersonOut):
    roles: list[str]


class TeamGrantOut(BaseModel):
    team: str
    team_name: str
    role: str
    from_default: bool


class TeamOut(BaseModel):
    code: str
    name: str
    members: list[PersonOut]


class TeamMembersIn(BaseModel):
    lan_ids: list[str] = Field(description="Complete list of the team's members")


class DefaultGrantIn(BaseModel):
    system: str = Field(default="DOC_HUB")
    child_node_type: str = Field(default="DOC_REPO")
    team: str
    role: str = Field(description="VIEWER or AUDITOR")


class DefaultGrantOut(BaseModel):
    id: uuid.UUID
    system: str
    child_node_type: str
    team: str
    team_name: str
    role: str


class OwnerIn(BaseModel):
    lan_id: str = Field(min_length=1, max_length=64)
