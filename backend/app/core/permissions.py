"""Roles, permissions and the rules between them.

This module is the single source of truth. The roles / permissions / role_permissions
tables are seeded from it, and the role-assignment rules below are enforced by
app.services.roles.
"""

from dataclasses import dataclass
from enum import StrEnum


class RoleCode(StrEnum):
    SYSTEM_ADMIN = "system_admin"
    DEPARTMENT_ADMIN = "department_admin"
    MAKER = "maker"
    CHECKER = "checker"
    VIEWER = "viewer"  # implicit for every department member who isn't a department admin


class Perm(StrEnum):
    # Knowledge bases
    KB_CREATE = "kb:create"
    KB_UPDATE = "kb:update"
    KB_VIEW = "kb:view"
    # People and organisation
    USERS_VIEW = "users:view"
    USERS_CREATE = "users:create"
    DEPARTMENTS_MANAGE = "departments:manage"
    ROLES_VIEW = "roles:view"
    WORKFLOWS_VIEW = "workflows:view"
    DEPARTMENT_ADMINS_MANAGE = "department_admins:manage"
    DEPARTMENT_ROLES_MANAGE = "department_roles:manage"  # maker / checker
    # Cross-department view access
    ACCESS_REQUESTS_CREATE = "access_requests:create"
    ACCESS_REQUESTS_DECIDE = "access_requests:decide"
    # Documents
    DOCUMENTS_VIEW = "documents:view"  # approved documents only
    DOCUMENTS_VIEW_UNAPPROVED = "documents:view_unapproved"
    DOCUMENTS_UPLOAD = "documents:upload"
    DOCUMENTS_APPROVE = "documents:approve"


PERMISSION_DESCRIPTIONS: dict[Perm, str] = {
    Perm.KB_CREATE: "Create knowledge bases for any department",
    Perm.KB_UPDATE: "Edit knowledge base details",
    Perm.KB_VIEW: "Open knowledge bases you have access to",
    Perm.USERS_VIEW: "See users and their roles",
    Perm.USERS_CREATE: "Add users (system admins add department admins; department admins add their own department's users)",
    Perm.DEPARTMENTS_MANAGE: "Create departments",
    Perm.ROLES_VIEW: "See roles and permissions",
    Perm.WORKFLOWS_VIEW: "See approval workflow definitions",
    Perm.DEPARTMENT_ADMINS_MANAGE: "Assign and remove department admins",
    Perm.DEPARTMENT_ROLES_MANAGE: "Assign and remove makers and checkers in your department",
    Perm.ACCESS_REQUESTS_CREATE: "Request view access to another department's knowledge base",
    Perm.ACCESS_REQUESTS_DECIDE: "Approve or reject view-access requests for your department",
    Perm.DOCUMENTS_VIEW: "View approved documents",
    Perm.DOCUMENTS_VIEW_UNAPPROVED: "View pending and rejected documents in your department",
    Perm.DOCUMENTS_UPLOAD: "Upload documents to your department's knowledge bases",
    Perm.DOCUMENTS_APPROVE: "Approve or reject documents raised by your department's makers",
}


@dataclass(frozen=True)
class RoleDef:
    name: str
    description: str
    scope: str  # "global" or "department"
    permissions: frozenset[Perm]
    assignable: bool  # can be granted through the API


_VIEWER_PERMS = frozenset({Perm.KB_VIEW, Perm.DOCUMENTS_VIEW, Perm.ACCESS_REQUESTS_CREATE})

ROLES: dict[RoleCode, RoleDef] = {
    RoleCode.SYSTEM_ADMIN: RoleDef(
        "System admin",
        "Creates knowledge bases and manages department admins. Not tied to a department. "
        "Cannot upload, approve or view documents.",
        "global",
        frozenset({
            Perm.KB_CREATE,
            Perm.KB_UPDATE,
            Perm.USERS_VIEW,
            Perm.USERS_CREATE,
            Perm.DEPARTMENT_ADMINS_MANAGE,
            Perm.DEPARTMENTS_MANAGE,
            Perm.ROLES_VIEW,
            Perm.WORKFLOWS_VIEW,
        }),
        assignable=False,
    ),
    RoleCode.DEPARTMENT_ADMIN: RoleDef(
        "Department admin",
        "Maintains the department's knowledge bases, manages makers and checkers, and decides "
        "view-access requests. Cannot upload, approve or view documents.",
        "department",
        frozenset({
            Perm.KB_UPDATE,
            Perm.USERS_VIEW,
            Perm.USERS_CREATE,
            Perm.DEPARTMENT_ROLES_MANAGE,
            Perm.ACCESS_REQUESTS_DECIDE,
        }),
        assignable=True,
    ),
    RoleCode.MAKER: RoleDef(
        "Maker",
        "Uploads documents to the department's knowledge bases.",
        "department",
        frozenset({Perm.DOCUMENTS_UPLOAD, Perm.DOCUMENTS_VIEW_UNAPPROVED}),
        assignable=True,
    ),
    RoleCode.CHECKER: RoleDef(
        "Checker",
        "Approves or rejects documents raised by the department's makers.",
        "department",
        frozenset({Perm.DOCUMENTS_APPROVE, Perm.DOCUMENTS_VIEW_UNAPPROVED}),
        assignable=True,
    ),
    RoleCode.VIEWER: RoleDef(
        "Viewer",
        "Views approved documents in the department's knowledge bases, and in other "
        "departments' knowledge bases once access is approved. Given to every department "
        "member automatically.",
        "department",
        _VIEWER_PERMS,
        assignable=False,
    ),
}

# Pairs of roles one person may not hold at the same time.
MUTUALLY_EXCLUSIVE: frozenset[frozenset[RoleCode]] = frozenset({
    frozenset({RoleCode.MAKER, RoleCode.CHECKER}),  # separation of duties
    frozenset({RoleCode.DEPARTMENT_ADMIN, RoleCode.MAKER}),  # admins don't handle documents
    frozenset({RoleCode.DEPARTMENT_ADMIN, RoleCode.CHECKER}),
})


def effective_roles(assigned: set[RoleCode], has_department: bool) -> set[RoleCode]:
    """Assigned roles plus the implicit viewer role."""
    roles = set(assigned)
    admin = {RoleCode.SYSTEM_ADMIN, RoleCode.DEPARTMENT_ADMIN}
    if has_department and not roles & admin:
        roles.add(RoleCode.VIEWER)
    return roles


def permissions_for(roles: set[RoleCode]) -> set[Perm]:
    perms: set[Perm] = set()
    for role in roles:
        perms |= ROLES[role].permissions
    return perms
