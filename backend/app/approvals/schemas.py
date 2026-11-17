import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PersonRef(BaseModel):
    lan_id: str
    display_name: str


class ApprovalOut(BaseModel):
    """One task waiting for the caller's decision."""

    id: uuid.UUID = Field(description="The task id (decide with POST /api/approvals/{id}/decision)")
    request_id: uuid.UUID
    kind: str = Field(description='Approval type code, e.g. "DOCUMENT_UPLOAD"')
    kind_label: str = Field(description='e.g. "Document"')
    title: str
    round: int = Field(description="1, then 2, 3 ... after changes were requested")
    resource_name: str
    summary: dict[str, Any] = Field(description="What the submitting module shows the checker: subtitle, facts, "
                                                "sections, download, link")
    requested_by: PersonRef | None
    requested_at: datetime


class ApprovalListOut(BaseModel):
    """One task waiting for the caller's decision, as listed: straight from the task's metadata.
    Open it (GET /api/approvals/{id}) for the summary."""

    id: uuid.UUID = Field(description="The task id")
    kind: str = Field(description='Approval type code, e.g. "DOCUMENT_UPLOAD"')
    kind_label: str = Field(description='e.g. "Document"')
    title: str
    round: int
    resource_name: str
    requested_by: PersonRef | None = Field(description="Who submitted this round")
    requested_at: datetime = Field(description="When this round was submitted")
    metadata: dict[str, Any] = Field(description="The task's metadata as stored (type, title, submitted_by, "
                                                 "submitted_at, resource, subject, and the module's own fields)")


class DecisionIn(BaseModel):
    decision: str = Field(description="approve, reject or request_changes")
    comment: str = Field(default="", max_length=4000, description="Required unless approving")


class BulkDecisionIn(DecisionIn):
    task_ids: list[uuid.UUID] = Field(min_length=1, max_length=500,
                                      description="Tasks to decide, all or none; the comment is recorded on each")


class BulkDecisionOut(BaseModel):
    decided: int


class DecisionOut(BaseModel):
    decision: str = Field(description="APPROVED, REJECTED or CHANGES_REQUESTED")
    comment: str | None
    decided_by: PersonRef | None
    decided_at: datetime
    round: int


class RoundOut(BaseModel):
    """One task of the request: a REVIEW step in a round."""

    id: uuid.UUID = Field(description="The task")
    round: int
    step: str | None = Field(description='The step\'s name, e.g. "Checker review"')
    status: str
    outcome: str | None
    created_at: datetime
    completed_at: datetime | None
    decisions: list[DecisionOut]


class RequestHistoryOut(BaseModel):
    id: uuid.UUID
    reference: str
    status: str
    requested_by: PersonRef | None
    submitted_at: datetime
    completed_at: datetime | None
    rounds: list[RoundOut]


# --------------------------------------------------------------------------- approval workflows


class WorkflowBindingOut(BaseModel):
    version: int
    node_id: uuid.UUID | None = Field(description="None: the approval type's default")
    node_name: str | None


class StepBriefOut(BaseModel):
    id: str
    name: str
    type: str = Field(description="CHECK or REVIEW")


class WorkflowSummaryOut(BaseModel):
    id: uuid.UUID
    code: str = Field(description='e.g. "DOC_HUB.DOCUMENT_UPLOAD"')
    name: str
    approval_type: str
    approval_type_label: str
    latest_version: int
    last_published_at: datetime | None
    applies: list[WorkflowBindingOut] = Field(description="Where each version is in use for new requests")
    steps: list[StepBriefOut] = Field(description="The latest version's steps, in order")


class WorkflowVersionOut(BaseModel):
    id: uuid.UUID
    version: int
    status: str
    published_at: datetime | None
    definition: dict[str, Any]
    applies_to: list[str] = Field(description='"Default" and/or node names it is bound to')


class WorkflowOut(WorkflowSummaryOut):
    versions: list[WorkflowVersionOut] = Field(description="Newest first")


class FlowIn(BaseModel):
    definition: dict[str, Any]


class PublishIn(FlowIn):
    node_id: uuid.UUID | None = Field(default=None, description="Publish for one node only; omitted: the default")


class FlowCheckOut(BaseModel):
    ok: bool
    steps: int
    start: str
