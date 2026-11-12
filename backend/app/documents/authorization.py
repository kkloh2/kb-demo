"""@DocRepoRoles: guard an endpoint by the caller's roles in one doc-repo, or in its department.

    @router.put("/doc-repos/{doc_repo_id}")
    @DocRepoRoles(department_roles=("DEPARTMENT_ADMIN",))                  # the department's admin
    def update_doc_repo(doc_repo_id: int, ...): ...

    @router.get("/doc-repos/{doc_repo_id}/documents")
    @DocRepoRoles("MAKER", "CHECKER", "VIEWER", department_roles=("DEPARTMENT_ADMIN",))
    def list_documents(doc_repo_id: int, ...): ...

The doc-repo comes from the endpoint parameter named by `doc_repo` (default "doc_repo_id"); a missing
doc-repo answers 404. The caller gets in when they hold one of `department_roles` in the doc-repo's
department (from their token) OR one of the doc-repo `roles` (from the database: doc-repo roles are
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
from app.documents.models import DocRepoRole
from app.users.authorization import _RoleGuard  # shared guard machinery (wrapping, stacking, 401/403)
from app.users.models import ROLE_DEFINITIONS, RoleCode, RoleScope
from app.users.service import org_unit_roles_of


class DocRepoRoles(_RoleGuard):
    """Allow callers holding one of `roles` in the doc-repo, or one of `department_roles` in the
    doc-repo's department."""

    scope = RoleScope.ORG_UNIT

    def __init__(self, *roles: str, department_roles: tuple[str, ...] = (), doc_repo: str = "doc_repo_id"):
        # Not super().__init__: these are doc-repo roles, checked against DocRepoRole.
        for role in roles:
            if role not in DocRepoRole.__members__:
                raise ValueError(f"{role!r} is not a doc-repo role ({', '.join(DocRepoRole.__members__)}).")
        for role in department_roles:
            if ROLE_DEFINITIONS[RoleCode(role)][0] is not RoleScope.ORG_UNIT:  # ValueError if unknown
                raise ValueError(f"{role} is not a department (org unit) role.")
        if not roles and not department_roles:
            raise ValueError("DocRepoRoles needs at least one doc-repo or department role.")
        self.roles = frozenset(roles)
        self.department_roles = frozenset(department_roles)
        self.doc_repo_param = doc_repo

    def validate(self, endpoint: Callable[..., Any], signature: inspect.Signature) -> None:
        if self.doc_repo_param not in signature.parameters:
            raise TypeError(
                f"{endpoint.__qualname__} has no {self.doc_repo_param!r} parameter for DocRepoRoles to read "
                f"the doc-repo from."
            )

    def allows(self, principal: Principal, arguments: Mapping[str, Any]) -> bool:
        with new_session() as db:
            doc_repo = service.get_doc_repo(db, int(arguments[self.doc_repo_param]))  # NotFound -> 404
            held = org_unit_roles_of(principal).get(doc_repo.department.code, frozenset())
            if self.department_roles & held:
                return True
            return bool(self.roles & service.doc_repo_roles_of(db, principal.lan_id, doc_repo.id))

    def __repr__(self) -> str:
        return (f"DocRepoRoles({', '.join(sorted(self.roles))}, department_roles={sorted(self.department_roles)}, "
                f"doc_repo={self.doc_repo_param!r})")
