"""Subject handlers: how the workflow module talks to the things it governs.

The workflow module knows nothing about documents. Each kind of subject (today only
"document") registers a handler that answers the domain questions:

- may this person complete this task?            authorize()
- is this task data acceptable?                  validate()
- what should the inbox show for this subject?   describe()
- may this person see this subject's history?    can_view()
- what happens when the workflow finishes?       on_completed()
"""

from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.workflow.models import WorkflowInstance, WorkflowTask


class Actor(Protocol):
    """The person acting. app.services.auth.Principal satisfies this."""

    user_id: int
    lan_id: str
    roles: Any  # collection of role codes; lanes are matched against it


class SubjectHandler(Protocol):
    subject_type: str
    definition_key: str  # which workflow definition governs this subject type

    def authorize(self, db: Session, actor: Actor, task: WorkflowTask, instance: WorkflowInstance) -> None:
        """Raise Forbidden if the actor may not complete the task."""

    def validate(self, task: WorkflowTask, data: dict[str, Any]) -> dict[str, Any]:
        """Return cleaned data, or raise InvalidRequest."""

    def describe(self, db: Session, subject_id: str) -> dict[str, Any]:
        """Short summary for task lists, e.g. {"title": ..., "link": ...}."""

    def can_view(self, db: Session, actor: Actor, subject_id: str) -> bool:
        """Whether the actor may see this subject's workflow history."""

    def on_completed(
        self, db: Session, instance: WorkflowInstance, outcome: dict[str, Any], actor: Actor | None
    ) -> None:
        """Apply the outcome to the subject (e.g. mark a document approved)."""


_HANDLERS: dict[str, SubjectHandler] = {}


def register_handler(handler: SubjectHandler) -> None:
    _HANDLERS[handler.subject_type] = handler


def get_handler(subject_type: str) -> SubjectHandler:
    try:
        return _HANDLERS[subject_type]
    except KeyError:
        raise LookupError(f"No workflow handler for subject type '{subject_type}'.") from None
