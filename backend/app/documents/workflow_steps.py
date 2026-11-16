"""Doc Hub's workflow step types, built from what approvals offers. The workflow engine runs them;
which flow a repository uses is bound to its node (the default flow when it's created).

    DOCUMENT_UPLOAD   the maker's step: whoever submits must hold role.role in the repository's user
                      group role.user_group. PASSED / FAILED. When the flow comes back to it (changes
                      were requested) it waits, and the maker's resubmission runs the check again.
    DOCUMENT_REVIEW   a review: a task for the active members of that user group holding that role.
                      APPROVED / REJECTED / CHANGES_REQUESTED.
"""

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.access.catalog import RoleCode
from app.approvals import service as approvals
from app.workflows import engine
from app.workflows.flow import Step, StepContext, StepType, register_default_flow, register_step_type

KIND = "DOC_HUB.DOCUMENT"  # what Doc Hub's flows work on: a document, in a repository
DEFAULT_WORKFLOW = json.loads((Path(__file__).parent / "document_approval.workflow.json").read_text())


def _needs_role(step: Step) -> None:
    if step.role is None:
        raise ValueError(f'step {step.id}: needs "role": {{"user_group": ..., "role": ...}}')
    if step.role.role not in RoleCode.__members__:
        raise ValueError(f"step {step.id}: unknown role {step.role.role!r}")


def _check_submitter(db: Session, ctx: StepContext) -> str:
    why = approvals.holds_role_in_group(db, ctx.actor, ctx.instance.hierarchy_node_id,
                                        ctx.step.role.user_group, ctx.step.role.role)
    ctx.step_instance.detail = {"reason": why} if why else {}
    return "FAILED" if why else "PASSED"


def _upload_enter(db: Session, ctx: StepContext) -> str | None:
    if ctx.reentry:  # back for changes: wait for the maker to resubmit
        return None
    return _check_submitter(db, ctx)


def _review_enter(db: Session, ctx: StepContext) -> None:
    approvals.open_review(db, approvals.request_of(db, ctx.instance), ctx.step_instance, ctx.step.name,
                          ctx.step.role.user_group, ctx.step.role.role, ctx.data)
    return None  # waits for the decision


DOCUMENT_UPLOAD = StepType(
    code="DOCUMENT_UPLOAD", kind=KIND, kind_label="Document", outcomes=("PASSED", "FAILED"),
    enter=_upload_enter, signal=_check_submitter, validate=_needs_role,
    description="The submitter must hold the role in the named user group; waits for resubmission after changes.")
DOCUMENT_REVIEW = StepType(
    code="DOCUMENT_REVIEW", kind=KIND, kind_label="Document", outcomes=("APPROVED", "REJECTED", "CHANGES_REQUESTED"),
    enter=_review_enter, validate=_needs_role,
    description="Any one active member of the named user group holding the role decides.")

register_step_type(DOCUMENT_UPLOAD)
register_step_type(DOCUMENT_REVIEW)
register_default_flow(DEFAULT_WORKFLOW)


def bind_default(db: Session, node_id, actor_id=None) -> None:
    """A new repository uses Doc Hub's default flow (created as version 1 the first time)."""
    wf = engine.ensure_definition(db, DEFAULT_WORKFLOW)
    engine.bind(db, node_id, wf.id, actor_id)
