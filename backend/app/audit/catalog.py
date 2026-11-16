"""The kinds of audit event. Each area registers its own (register_actions); recording an
unregistered action is an error. Codes are unique across areas; the area an event belongs to is
its own column (an event at a node belongs to that node's source system)."""

from dataclasses import dataclass

CATEGORIES = ("access", "configuration", "content", "approval", "security")


@dataclass(frozen=True)
class Action:
    code: str
    source_system: str
    category: str
    label: str
    description: str = ""


_actions: dict[str, Action] = {}


def register_actions(source_system: str, actions: dict[str, tuple[str, str] | tuple[str, str, str]]) -> None:
    """{code: (category, label[, description])} for one area, e.g. register_actions("DOC_HUB", {...})."""
    for code, spec in actions.items():
        category, label, *rest = spec
        if category not in CATEGORIES:
            raise ValueError(f"{code}: unknown category {category!r}")
        _actions[code] = Action(code, source_system, category, label, rest[0] if rest else "")


def action(code: str) -> Action:
    try:
        return _actions[code]
    except KeyError:
        raise RuntimeError(f"Audit action {code!r} isn't registered (app.audit.catalog.register_actions).") from None


def actions() -> list[Action]:
    return list(_actions.values())
