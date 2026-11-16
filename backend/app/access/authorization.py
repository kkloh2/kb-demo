"""Endpoint guards: the caller must hold a permission at a node.

    @router.post("/doc-repos")
    @Can(P.REPO_CREATE, at=Root(SystemCode.DOC_HUB))
    def create_doc_repo(...): ...

    @router.delete("/doc-repos/{doc_repo_id}")
    @Can(P.NODE_DELETE, at=Param("doc_repo_id", repo_node))      # repo_node(db, value) -> node id
    def delete_doc_repo(doc_repo_id: uuid.UUID, ...): ...

The check reads the database on every request (app.access.service.can), so a role given or taken
away applies at once. Stacked guards combine with OR: any one is enough. Put the guard directly
below the @router decorator. No token answers 401; a missing node 404; no permission 403.
"""

import functools
import inspect
import uuid
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from sqlalchemy.orm import Session

from app.access import service
from app.access.catalog import PERMISSIONS, P, SystemCode
from app.auth.dependencies import CurrentUser
from app.auth.identity import Principal
from app.core.errors import Forbidden
from app.db.session import new_session

F = TypeVar("F", bound=Callable[..., Any])

_PRINCIPAL_PARAM = "_authorized_principal"
FORBIDDEN = "You don't have permission to do this."


class Root:
    """The root node of a source system."""

    def __init__(self, system: SystemCode):
        self.system = system

    def needs(self) -> str | None:
        return None

    def resolve(self, db: Session, arguments: Mapping[str, Any]) -> uuid.UUID:
        return service.root_node(db, self.system).id

    def __repr__(self) -> str:
        return f"Root({self.system.value})"


class Param:
    """The node an endpoint parameter points at: `to_node(db, value)` returns its node id
    (raising NotFound when there's none)."""

    def __init__(self, name: str, to_node: Callable[[Session, Any], uuid.UUID]):
        self.name, self.to_node = name, to_node

    def needs(self) -> str | None:
        return self.name

    def resolve(self, db: Session, arguments: Mapping[str, Any]) -> uuid.UUID:
        return self.to_node(db, arguments[self.name])

    def __repr__(self) -> str:
        return f"Param({self.name!r})"


class Can:
    def __init__(self, permission: P, *, at: Root | Param):
        if permission not in PERMISSIONS:
            raise ValueError(f"Unknown permission {permission!r}.")
        self.permission, self.at = permission, at

    def allows(self, principal: Principal, arguments: Mapping[str, Any]) -> bool:
        with new_session() as db:
            node_id = self.at.resolve(db, arguments)  # NotFound passes through as 404
            user = service.get_user(db, principal.lan_id)
            return user is not None and user.status == "ACTIVE" and service.can(db, user.id, node_id, self.permission)

    def __repr__(self) -> str:
        return f"Can({self.permission.value}, at={self.at!r})"

    def __call__(self, endpoint: F) -> F:
        guards: list[Can] = [*getattr(endpoint, "guards", ()), self]
        original = getattr(endpoint, "guarded_endpoint", endpoint)
        signature = inspect.signature(original)
        if _PRINCIPAL_PARAM in signature.parameters:
            raise TypeError(f"{original.__qualname__} already has a {_PRINCIPAL_PARAM} parameter.")
        needed = self.at.needs()
        if needed and needed not in signature.parameters:
            raise TypeError(f"{original.__qualname__} has no {needed!r} parameter for {self!r}.")

        def check(kwargs: dict[str, Any]) -> None:
            principal = kwargs.pop(_PRINCIPAL_PARAM)
            if not any(g.allows(principal, kwargs) for g in guards):
                raise Forbidden(FORBIDDEN)

        if inspect.iscoroutinefunction(original):

            @functools.wraps(original)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                check(kwargs)
                return await original(*args, **kwargs)

        else:

            @functools.wraps(original)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                check(kwargs)
                return original(*args, **kwargs)

        extra = inspect.Parameter(_PRINCIPAL_PARAM, inspect.Parameter.KEYWORD_ONLY, annotation=CurrentUser)
        wrapper.__signature__ = signature.replace(parameters=[*signature.parameters.values(), extra])  # type: ignore[attr-defined]
        wrapper.guards = tuple(guards)  # type: ignore[attr-defined]
        wrapper.guarded_endpoint = original  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]


PlatformAdmin = Can(P.PLATFORM_MANAGE, at=Root(SystemCode.PLATFORM))
