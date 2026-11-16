"""How a feature plugs its approvable things into CAMS, without CAMS knowing about it.

    approval_kind(ApprovalKind(
        system=SystemCode.DOC_HUB, type_code="DOCUMENT_UPLOAD", name="Document upload", label="Document",
        resource_type="DOC_REPO", subject_type="DOCUMENT", on_decided=documents.on_decided,
        workflow_kind="DOC_HUB.DOCUMENT",
    ))

Each request runs the standalone workflow (app.workflows) bound at its resource's node for
`workflow_kind`; the feature registers that kind's step types and binds its nodes. It reacts to the
outcome through on_decided (APPROVED, REJECTED or CHANGES_REQUESTED). Registered in app.main.
"""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.access.catalog import SystemCode
from app.access.models import AppUser
from app.approvals.models import ApprovalRequest

# (db, request, decision APPROVED | REJECTED | CHANGES_REQUESTED, decided by, comment)
OnDecided = Callable[[Session, ApprovalRequest, str, AppUser, str | None], None]


@dataclass(frozen=True)
class ApprovalKind:
    system: SystemCode
    type_code: str
    name: str
    label: str  # shown on the Approvals page, e.g. "Document"
    resource_type: str
    subject_type: str
    on_decided: OnDecided
    workflow_kind: str  # the kind of workflow its resources' nodes are bound to, e.g. "DOC_HUB.DOCUMENT"


_kinds: dict[str, ApprovalKind] = {}


def approval_kind(kind: ApprovalKind) -> ApprovalKind:
    _kinds[kind.type_code] = kind
    return kind


def kinds() -> list[ApprovalKind]:
    return list(_kinds.values())


def kind_of(type_code: str) -> ApprovalKind:
    try:
        return _kinds[type_code]
    except KeyError:
        raise RuntimeError(f"No approval kind {type_code!r} is registered (app.main registers them).") from None
