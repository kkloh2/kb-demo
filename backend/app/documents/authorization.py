"""@ProjectRoles: guard an endpoint by the caller's roles in one project, or in its department.

    @router.put("/projects/{project_id}")
    @ProjectRoles(department_roles=("DEPARTMENT_ADMIN",))                  # the department's admin
    def update_project(project_id: int, ...): ...

    @router.get("/projects/{project_id}/documents")
    @ProjectRoles("MAKER", "CHECKER", "VIEWER", department_roles=("DEPARTMENT_ADMIN",))
    def list_documents(project_id: int, ...): ...

The project comes from the endpoint parameter named by `project` (default "project_id"); a missing
project answers 404. The caller gets in when they hold one of `department_roles` in the project's
department (from their token) OR one of the project `roles` (from the database: project roles are
per resource and change without signing anyone out).

It is built on the users module's guard machinery, so it also combines with @SystemRoles and
@OrgUnitRoles stacked on the same endpoint: any one of them is enough (OR).
"""

import inspect
from collections.abc import Callable, Mapping
from typing import Any

from app.auth.identity import Principal
from app.db.session import new_session
from app.documents import service
from app.documents.models import ProjectRole
from app.users.authorization import _RoleGuard  # shared guard machinery (wrapping, stacking, 401/403)
from app.users.models import ROLE_DEFINITIONS, RoleCode, RoleScope
from app.users.service import org_unit_roles_of


class ProjectRoles(_RoleGuard):
    """Allow callers holding one of `roles` in the project, or one of `department_roles` in the
    project's department."""

    scope = RoleScope.ORG_UNIT

    def __init__(self, *roles: str, department_roles: tuple[str, ...] = (), project: str = "project_id"):
        # Not super().__init__: these are project roles, checked against ProjectRole.
        for role in roles:
            if role not in ProjectRole.__members__:
                raise ValueError(f"{role!r} is not a project role ({', '.join(ProjectRole.__members__)}).")
        for role in department_roles:
            if ROLE_DEFINITIONS[RoleCode(role)][0] is not RoleScope.ORG_UNIT:  # ValueError if unknown
                raise ValueError(f"{role} is not a department (org unit) role.")
        if not roles and not department_roles:
            raise ValueError("ProjectRoles needs at least one project or department role.")
        self.roles = frozenset(roles)
        self.department_roles = frozenset(department_roles)
        self.project_param = project

    def validate(self, endpoint: Callable[..., Any], signature: inspect.Signature) -> None:
        if self.project_param not in signature.parameters:
            raise TypeError(
                f"{endpoint.__qualname__} has no {self.project_param!r} parameter for ProjectRoles to read "
                f"the project from."
            )

    def allows(self, principal: Principal, arguments: Mapping[str, Any]) -> bool:
        with new_session() as db:
            project = service.get_project(db, int(arguments[self.project_param]))  # NotFound -> 404
            held = org_unit_roles_of(principal).get(project.department.code, frozenset())
            if self.department_roles & held:
                return True
            return bool(self.roles & service.project_roles_of(db, principal.lan_id, project.id))

    def __repr__(self) -> str:
        return (f"ProjectRoles({', '.join(sorted(self.roles))}, department_roles={sorted(self.department_roles)}, "
                f"project={self.project_param!r})")
