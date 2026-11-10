from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TaskOut(BaseModel):
    id: int
    name: str
    title: str
    lane: str | None = Field(description="Role allowed to complete it")
    status: str = Field(description="ready | completed | cancelled")
    created_at: datetime
    completed_by: str | None
    completed_at: datetime | None
    data: dict[str, Any] | None


class InboxTaskOut(TaskOut):
    instance_id: int
    subject_type: str
    subject_id: str
    subject: dict[str, Any]
    workflow: str = Field(description="definition key@version")


class TaskComplete(BaseModel):
    data: dict[str, Any] = Field(
        default_factory=dict, description='For document review: {"decision": "approve"|"reject", "reason": "..."}'
    )


class InstanceOut(BaseModel):
    id: int
    workflow: str
    engine: str
    subject_type: str
    subject_id: str
    status: str
    outcome: dict[str, Any] | None
    started_at: datetime
    completed_at: datetime | None
    tasks: list[TaskOut]


class DefinitionOut(BaseModel):
    id: int
    key: str
    version: int
    name: str
    description: str
    engine: str
    is_active: bool
    has_source: bool
    source_filename: str | None
    created_at: datetime
