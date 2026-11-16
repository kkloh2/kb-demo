import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.access.schemas import MemberOut


class SourceIn(BaseModel):
    code: str = Field(min_length=2, max_length=32, description='e.g. "DOC_HUB" (letters, digits, underscores)')
    name: str = Field(min_length=1, max_length=128, description='e.g. "Document repositories"')


class HierarchyIn(BaseModel):
    name: str = Field(default="", max_length=128, description="The root node's name (default: the system's code)")
    levels: list[str] | None = Field(default=None, max_length=8,
                                     description='The levels below the root, top down, e.g. ["DOC_REPO"]. Left out: '
                                                 "the ones Data Hub defines for that system (DOC_HUB: DOC_REPO), or none.")


class GroupMemberOut(MemberOut):
    added_at: datetime | None = Field(description="When they joined the group")
    updated_at: datetime | None = Field(description="The latest change to their membership or roles in it")


class GroupOut(BaseModel):
    type: str = Field(description="ADMINS or USERS")
    name: str
    roles: list[str] = Field(description="Roles its members may hold")
    auto_join_role: str | None = Field(description="Everyone joins with this role (users group: VIEWER)")
    members: list[GroupMemberOut]


class HierarchyOut(BaseModel):
    name: str
    levels: list[str] = Field(description='Node type at each level, root first, e.g. ["ROOT", "DOC_REPO"]')
    root_node_id: uuid.UUID
    child_count: int = Field(description="Nodes directly under the root (e.g. repositories)")
    groups: list[GroupOut]


class SourceOut(BaseModel):
    code: str
    name: str
    status: str
    created_at: datetime
    last_updated: datetime = Field(description="The latest change to the system, its hierarchy, or who is in its root groups")
    hierarchy: HierarchyOut | None = Field(description="null until a platform admin creates it")


class GroupRolesIn(BaseModel):
    roles: list[str] = Field(description='Complete list for this group, e.g. ["ADMIN"]. [] removes them from it.')
