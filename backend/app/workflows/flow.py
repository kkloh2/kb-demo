"""The flow format, and the step types features register.

    {
      "code": "DOC_HUB.DOCUMENT_APPROVAL",
      "name": "Document approval",                       (optional)
      "start": "maker_upload",
      "steps": [
        {"id": "maker_upload", "type": "DOCUMENT_UPLOAD", "name": "Raised by a maker",
         "role": {"user_group": "default", "role": "MAKER"},
         "on": {"PASSED": "checker_review", "FAILED": "END:UNAUTHORIZED"}},
        {"id": "checker_review", "type": "DOCUMENT_REVIEW", "name": "Checker review",
         "role": {"user_group": "default", "role": "CHECKER"},
         "completion": {"rule": "ANY"},
         "on": {"APPROVED": "END:APPROVED", "REJECTED": "END:REJECTED", "CHANGES_REQUESTED": "maker_upload"}}
      ]
    }

- "type" is a step type a feature registered (register_step_type). It says what the step does and
  which outcomes it has; "on" must map exactly those outcomes.
- "role" is for the step type to use: here, a user group by name at the node the flow runs at
  ("default" is a group named "default") and the role a person needs in it.
- "on": outcome -> another step id, or END:<WORD> (e.g. END:APPROVED, END:UNAUTHORIZED). Going back to
  a step already run starts a new round.
- Every step type in a flow must work on the same kind of subject; that's the flow's kind.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy.orm import Session

from app.core.errors import InvalidRequest

END = re.compile(r"^END:[A-Z][A-Z_]*$")


class RoleSpec(BaseModel):
    user_group: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=32)


class Completion(BaseModel):
    rule: str = "ANY"


class Step(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    type: str
    name: str = Field(min_length=1, max_length=128)
    role: RoleSpec | None = None
    completion: Completion | None = None
    on: dict[str, str]


class Flow(BaseModel):
    code: str = Field(min_length=1, max_length=128)
    name: str | None = None
    start: str
    steps: list[Step] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self):
        ids = [s.id for s in self.steps]
        if len(set(ids)) != len(ids):
            raise ValueError("step ids must be unique")
        if self.start not in ids:
            raise ValueError(f'"start" {self.start!r} isn\'t a step')
        kinds = set()
        for s in self.steps:
            st = _types.get(s.type)
            if st is None:
                raise ValueError(f"step {s.id}: no step type {s.type!r} is registered")
            kinds.add(st.kind)
            if set(s.on) != set(st.outcomes):
                raise ValueError(f"step {s.id}: \"on\" needs exactly {sorted(st.outcomes)}")
            for outcome, target in s.on.items():
                if target not in ids and not END.match(target):
                    raise ValueError(f"step {s.id}: {outcome} goes to {target!r}, which isn't a step or END:<WORD>")
            if st.validate:
                st.validate(s)
        if len(kinds) > 1:
            raise ValueError(f"the steps work on different kinds of subject: {sorted(kinds)}")
        return self

    @property
    def kind(self) -> str:
        return _types[self.steps[0].type].kind

    def step(self, step_id: str) -> Step:
        return next(s for s in self.steps if s.id == step_id)


def parse(definition: dict[str, Any]) -> Flow:
    """Validate a flow (raises InvalidRequest saying what's wrong)."""
    try:
        return Flow.model_validate(definition)
    except ValidationError as e:
        raise InvalidRequest("The flow isn't valid: " + "; ".join(
            err["msg"].removeprefix("Value error, ") for err in e.errors())) from None


# --------------------------------------------------------------------------- step types


@dataclass
class StepContext:
    """What a step type gets when its step runs."""

    instance: Any  # WorkflowInstance
    step: Step  # the step's definition
    step_instance: Any  # StepInstance (set `detail` to explain an outcome)
    actor: Any  # whoever made it happen (opaque to the engine), or None
    data: dict[str, Any] = field(default_factory=dict)  # what the caller passed along
    reentry: bool = False  # the flow came back to this step (a new round), e.g. changes were requested


Handler = Callable[[Session, StepContext], str | None]  # an outcome now, or None to wait


@dataclass(frozen=True)
class StepType:
    code: str  # used as "type" in flows
    kind: str  # what it works on, e.g. "DOC_HUB.DOCUMENT"
    kind_label: str  # e.g. "Document"
    outcomes: tuple[str, ...]
    enter: Handler  # the step is reached
    signal: Handler | None = None  # someone acts on the waiting step (e.g. resubmits)
    validate: Callable[[Step], None] | None = None  # raise ValueError when the step's settings are wrong
    description: str = ""


_types: dict[str, StepType] = {}


def register_step_type(step_type: StepType) -> StepType:
    _types[step_type.code] = step_type
    return step_type


def step_type(code: str) -> StepType:
    return _types[code]


def kind_label(kind: str) -> str:
    return next((t.kind_label for t in _types.values() if t.kind == kind), kind)


# Flows features ship with (created as version 1 when first needed, e.g. Doc Hub's default).
_defaults: list[dict[str, Any]] = []


def register_default_flow(definition: dict[str, Any]) -> None:
    _defaults.append(definition)


def default_flows() -> list[dict[str, Any]]:
    return list(_defaults)
