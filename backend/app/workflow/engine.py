"""The engine contract: the only thing a workflow engine has to implement.

Modelled on how BPMN engines such as SpiffWorkflow work, so a Spiff-backed engine can be
added later without changing the rest of the module:

- a workflow runs until it reaches one or more **user tasks** waiting for a person;
- each task sits in a **lane**, which Data Hub treats as the role allowed to do it
  (e.g. "checker");
- a person completes a task with some **data**, and the engine runs on;
- the engine's state is **serialised to JSON** between steps (Spiff: BpmnWorkflowSerializer);
- when the workflow ends, its final data is the **outcome**.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class EngineTask:
    """A user task waiting for a person."""

    id: str  # stable within one workflow instance (Spiff: the task's UUID)
    name: str  # task spec id from the definition, e.g. "review"
    title: str  # human label, e.g. "Review document"
    lane: str | None  # role allowed to complete it, e.g. "checker"


@dataclass
class EngineSnapshot:
    """Where a workflow instance stands after start() or complete()."""

    state: dict[str, Any]  # opaque to everyone but the engine; stored as JSON
    ready: list[EngineTask] = field(default_factory=list)
    completed: bool = False
    outcome: dict[str, Any] = field(default_factory=dict)  # final workflow data when completed


class WorkflowEngine(Protocol):
    """Implement this to add an engine (e.g. "spiff.bpmn")."""

    name: str

    def validate_definition(self, source: str | None) -> None:
        """Raise ValueError if a definition can't run on this engine (called on upload)."""

    def start(self, source: str | None, context: dict[str, Any]) -> EngineSnapshot:
        """Start an instance with initial data (e.g. who uploaded what) and run to the first wait."""

    def complete(self, state: dict[str, Any], task_id: str, data: dict[str, Any]) -> EngineSnapshot:
        """Complete one ready task with data and run on to the next wait or the end."""


_ENGINES: dict[str, WorkflowEngine] = {}


def register_engine(engine: WorkflowEngine) -> None:
    _ENGINES[engine.name] = engine


def get_engine(name: str) -> WorkflowEngine:
    try:
        return _ENGINES[name]
    except KeyError:
        raise LookupError(f"No workflow engine named '{name}' is registered.") from None


def engine_names() -> list[str]:
    return sorted(_ENGINES)
