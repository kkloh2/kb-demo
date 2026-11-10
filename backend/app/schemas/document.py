from datetime import datetime

from pydantic import BaseModel, Field


class DocumentDecision(BaseModel):
    reason: str | None = Field(default=None, max_length=1000, description="Required when rejecting")


class PersonRef(BaseModel):
    username: str
    display_name: str


class DocumentOut(BaseModel):
    id: int
    kb_id: str
    title: str
    filename: str
    content_type: str | None
    size_bytes: int | None
    has_file: bool
    status: str = Field(description="pending_approval | approved | rejected")
    maker: PersonRef
    checker: PersonRef | None
    submitted_at: datetime
    decided_at: datetime | None
    rejection_reason: str | None


class ActivityDocument(BaseModel):
    id: int
    filename: str
    status: str = Field(description="The document's current status")


class ActivityOut(BaseModel):
    id: str
    type: str = Field(description="uploaded | approved | rejected")
    at: datetime
    document: ActivityDocument
    actor: PersonRef | None
    reason: str | None
