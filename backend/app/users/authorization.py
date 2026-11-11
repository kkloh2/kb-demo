"""Endpoint authorization from the roles in the caller's access token.

    @router.post("/departments")
    @SystemRoles("SYSTEM_ADMIN")                              # system admins only
    def create_department(body: DepartmentIn, db: Db, p: CurrentUser): ...

    @router.put("/departments/{code}/users/{lan_id}")
    @SystemRoles("SYSTEM_ADMIN")                              # system admins
    @OrgUnitRoles("DEPARTMENT_ADMIN", department="code")      #   OR admins of that department
    def set_department_roles(code: str, lan_id: str, body: DepartmentRolesIn, db: Db): ...

SystemRoles    the token's "system_roles" must hold at least one of the roles.
OrgUnitRoles   the token's "org_unit_roles" must hold at least one of the roles in the department
               whose code is in the endpoint parameter named by `department` (a path parameter,
               compared case-insensitively).

Used alone, a decorator's condition must hold. Stacked on one endpoint, the decorators combine
with OR: the caller gets in when any one of them holds.

Put the decorator directly above the function and below the @router decorator: FastAPI reads the
endpoint's signature when @router registers it. Both decorators require sign-in (they add auth's
CurrentUser dependency, so no token -> 401) and answer 403 when the role isn't held. The endpoint
may still take `p: CurrentUser` itself; FastAPI resolves it once per request.

The roles are those recorded in the token at sign-in. Changing someone's roles ends their
sessions (see service.py), so a token never carries roles that have since been taken away.
"""

import functools
import inspect
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from app.auth.dependencies import CurrentUser
from app.auth.identity import Principal
from app.core.errors import Forbidden
from app.users.models import ROLE_DEFINITIONS, RoleCode, RoleScope
from app.users.service import org_unit_roles_of, system_roles_of

F = TypeVar("F", bound=Callable[..., Any])

_PRINCIPAL_PARAM = "_authorized_principal"
FORBIDDEN = "You don't have permission to do this."


class _RoleGuard:
    """Shared machinery: validate the roles up front, inject the caller, check before the call.

    Stacking guards doesn't wrap twice: the outer one joins the inner one's list, and the single
    wrapper lets the call through when any guard in the list allows it (OR).
    """

    scope: RoleScope

    def __init__(self, *roles: str):
        if not roles:
            raise ValueError(f"{type(self).__name__} needs at least one role.")
        codes = []
        for role in roles:
            code = RoleCode(role)  # ValueError for an unknown role: caught when the module loads
            if ROLE_DEFINITIONS[code][0] is not self.scope:
                raise ValueError(f"{code.value} is not a {self.scope.value.replace('_', ' ')} role.")
            codes.append(code.value)
        self.roles = frozenset(codes)

    def allows(self, principal: Principal, arguments: Mapping[str, Any]) -> bool:
        raise NotImplementedError

    def validate(self, endpoint: Callable[..., Any], signature: inspect.Signature) -> None:
        """Hook for checks on the endpoint itself, run when it's decorated."""

    def __repr__(self) -> str:
        return f"{type(self).__name__}({', '.join(sorted(self.roles))})"

    def __call__(self, endpoint: F) -> F:
        inner_guards: list[_RoleGuard] = list(getattr(endpoint, "role_guards", []))
        original = getattr(endpoint, "guarded_endpoint", endpoint)  # unwrap a guard below this one
        signature = inspect.signature(original)
        if _PRINCIPAL_PARAM in signature.parameters:
            raise TypeError(f"{original.__qualname__} already has a {_PRINCIPAL_PARAM} parameter.")
        self.validate(original, signature)
        guards = [*inner_guards, self]

        def check(kwargs: dict[str, Any]) -> None:
            principal = kwargs.pop(_PRINCIPAL_PARAM)
            if not any(guard.allows(principal, kwargs) for guard in guards):
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

        # Tell FastAPI to inject the signed-in caller as an extra keyword argument.
        extra = inspect.Parameter(_PRINCIPAL_PARAM, inspect.Parameter.KEYWORD_ONLY, annotation=CurrentUser)
        wrapper.__signature__ = signature.replace(parameters=[*signature.parameters.values(), extra])  # type: ignore[attr-defined]
        wrapper.role_guards = tuple(guards)  # type: ignore[attr-defined]  (any one is enough)
        wrapper.guarded_endpoint = original  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]


class SystemRoles(_RoleGuard):
    """Allow callers holding at least one of the given system roles."""

    scope = RoleScope.SYSTEM

    def allows(self, principal: Principal, arguments: Mapping[str, Any]) -> bool:
        return bool(self.roles & system_roles_of(principal))


SystemRole = SystemRoles  # the original name


class OrgUnitRoles(_RoleGuard):
    """Allow callers holding at least one of the given org unit roles in the department named by
    the endpoint's `department` parameter (default "code")."""

    scope = RoleScope.ORG_UNIT

    def __init__(self, *roles: str, department: str = "code"):
        super().__init__(*roles)
        self.department_param = department

    def validate(self, endpoint: Callable[..., Any], signature: inspect.Signature) -> None:
        if self.department_param not in signature.parameters:
            raise TypeError(
                f"{endpoint.__qualname__} has no {self.department_param!r} parameter for OrgUnitRoles to read "
                f"the department code from."
            )

    def allows(self, principal: Principal, arguments: Mapping[str, Any]) -> bool:
        code = str(arguments.get(self.department_param, "")).strip().upper()
        return bool(self.roles & org_unit_roles_of(principal).get(code, frozenset()))

    def __repr__(self) -> str:
        return f"OrgUnitRoles({', '.join(sorted(self.roles))}, department={self.department_param!r})"
