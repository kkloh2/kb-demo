"""Built-in engines: fixed flows written in Python, used until BPMN definitions are uploaded."""

from typing import Any

from app.workflow.engine import EngineSnapshot, EngineTask

REVIEW = EngineTask(id="review", name="review", title="Review document", lane="checker")


class SingleReviewEngine:
    """One review step, then done.

        start ──▶ [review]  (lane: checker)
                     │ decision = approve | reject (+ reason)
                     ▼
                    end      outcome = {"decision", "reason"}

    This is the equivalent of a BPMN process with one user task in a "checker" lane.
    """

    name = "builtin.single_review"

    def validate_definition(self, source: str | None) -> None:
        if source:
            raise ValueError("The built-in engine doesn't take a definition file.")

    def start(self, source: str | None, context: dict[str, Any]) -> EngineSnapshot:
        return EngineSnapshot(state={"step": "review", "data": dict(context)}, ready=[REVIEW])

    def complete(self, state: dict[str, Any], task_id: str, data: dict[str, Any]) -> EngineSnapshot:
        if state.get("step") != "review" or task_id != REVIEW.id:
            raise ValueError(f"Task '{task_id}' isn't waiting in this workflow.")
        merged = {**state["data"], **data}
        return EngineSnapshot(
            state={"step": "end", "data": merged},
            completed=True,
            outcome={"decision": data.get("decision"), "reason": data.get("reason")},
        )
