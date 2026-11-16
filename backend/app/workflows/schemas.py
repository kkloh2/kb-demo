import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class StepBriefOut(BaseModel):
    id: str
    name: str
    type: str


class WorkflowSummaryOut(BaseModel):
    id: uuid.UUID
    code: str = Field(description='e.g. "DOC_HUB.DOCUMENT_APPROVAL"')
    name: str
    kind: str = Field(description='What it works on, e.g. "DOC_HUB.DOCUMENT"')
    kind_label: str = Field(description='e.g. "Document"')
    latest_version: int
    last_published_at: datetime | None
    steps: list[StepBriefOut] = Field(description="The latest version's steps, in order")
    used_by: int = Field(description="How many nodes (e.g. repositories) use it")


class WorkflowVersionOut(BaseModel):
    id: uuid.UUID
    version: int
    status: str
    published_at: datetime | None
    definition: dict[str, Any]


class WorkflowOut(WorkflowSummaryOut):
    versions: list[WorkflowVersionOut] = Field(description="Newest first")
    used_by_nodes: list[str] = Field(description="The nodes using it, by name")


class FlowIn(BaseModel):
    definition: dict[str, Any]


class FlowCheckOut(BaseModel):
    ok: bool
    steps: int
    start: str
    kind: str


class StepTypeOut(BaseModel):
    code: str
    kind: str
    kind_label: str
    outcomes: list[str]
    description: str
