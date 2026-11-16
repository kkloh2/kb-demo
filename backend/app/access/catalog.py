"""Reference data defined in code and synced into the database at every start-up: the PLATFORM
source system, roles, permissions, which roles carry which permissions, and which roles each kind
of group may hold. Other source systems, their hierarchies and levels are created by platform
admins (app.sources).

A permission is checked at one node: "may this person do P at node N?". A role's permissions
apply only at the node where the role is held, so e.g. ADMIN carries both platform.manage and
docs.repository.create, but platform.manage only counts at the PLATFORM root and
docs.repository.create only at the DOC_HUB root.
"""

from enum import StrEnum


class SystemCode(StrEnum):
    """Codes the code itself relies on. PLATFORM is seeded; the others are created by platform
    admins, and the module that uses one works once it exists."""

    PLATFORM = "PLATFORM"  # Data Hub itself: who may use it, platform admins, teams
    DOC_HUB = "DOC_HUB"  # document repositories (app.documents): levels ROOT -> DOC_REPO


PLATFORM_NAME = "Platform"

# The levels below the root that the code relies on, for systems it knows. Used when a platform
# admin creates the system's hierarchy; any other system gets only its root.
CHILD_LEVELS: dict[str, tuple[str, ...]] = {"DOC_HUB": ("DOC_REPO",)}


class RoleCode(StrEnum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MAKER = "MAKER"
    CHECKER = "CHECKER"
    VIEWER = "VIEWER"
    APPROVER = "APPROVER"
    AUDITOR = "AUDITOR"


ROLES: dict[RoleCode, tuple[str, str]] = {
    RoleCode.OWNER: ("Owner", "Created the node. Everything an admin can do, plus delete it and hand ownership over."),
    RoleCode.ADMIN: ("Admin", "Manages the node's members. At a system's root: sets up what's under it."),
    RoleCode.MAKER: ("Maker", "Uploads documents and submits them for approval."),
    RoleCode.CHECKER: ("Checker", "Approves, rejects or requests changes to what makers submit."),
    RoleCode.VIEWER: ("Viewer", "Sees approved documents. At a system's root: may use the system."),
    RoleCode.APPROVER: ("Approver", "Decides a later approval step (when workflows have more than one)."),
    RoleCode.AUDITOR: ("Auditor", "Sees documents in every status and their approval history. Can't act."),
}


class P(StrEnum):
    """Permission codes."""

    PLATFORM_USE = "platform.use"
    PLATFORM_MANAGE = "platform.manage"
    MEMBERS_MANAGE = "access.members.manage"
    NODE_DELETE = "access.node.delete"
    NODE_TRANSFER = "access.node.transfer"
    REPO_LIST = "docs.repository.list"
    REPO_CREATE = "docs.repository.create"
    REPO_VIEW = "docs.repository.view"
    REPO_EDIT = "docs.repository.edit"
    DOC_VIEW_APPROVED = "docs.document.view_approved"
    DOC_VIEW_SUBMITTED = "docs.document.view_submitted"
    DOC_VIEW_ALL = "docs.document.view_all"
    DOC_UPLOAD = "docs.document.upload"
    DOC_APPROVE = "docs.document.approve"
    HISTORY_VIEW = "approvals.history.view"
    AUDIT_VIEW = "audit.trail.view"


PERMISSIONS: dict[P, str] = {
    P.PLATFORM_USE: "Use Data Hub",
    P.PLATFORM_MANAGE: "Manage users, teams, system roots and recovery",
    P.MEMBERS_MANAGE: "Manage the node's members and their roles",
    P.NODE_DELETE: "Delete the node (soft delete)",
    P.NODE_TRANSFER: "Hand ownership of the node to someone else",
    P.REPO_LIST: "See the list of document repositories",
    P.REPO_CREATE: "Create document repositories",
    P.REPO_VIEW: "Open the repository",
    P.REPO_EDIT: "Edit the repository's description and metadata fields",
    P.DOC_VIEW_APPROVED: "See approved documents",
    P.DOC_VIEW_SUBMITTED: "See submitted documents (pending, changes requested, approved, rejected)",
    P.DOC_VIEW_ALL: "See documents in every status, drafts included",
    P.DOC_UPLOAD: "Upload documents, edit their metadata and submit them",
    P.DOC_APPROVE: "Approve, reject or request changes to submitted documents",
    P.HISTORY_VIEW: "See approval history and the audit trail",
    P.AUDIT_VIEW: "See the activity (audit trail) at the node and below it",
}

ROLE_PERMISSIONS: dict[RoleCode, frozenset[P]] = {
    RoleCode.OWNER: frozenset({
        P.MEMBERS_MANAGE, P.NODE_DELETE, P.NODE_TRANSFER, P.REPO_VIEW, P.REPO_EDIT, P.DOC_VIEW_APPROVED,
        P.AUDIT_VIEW,
    }),
    RoleCode.ADMIN: frozenset({
        P.PLATFORM_USE, P.PLATFORM_MANAGE, P.MEMBERS_MANAGE, P.REPO_LIST, P.REPO_CREATE, P.REPO_VIEW,
        P.REPO_EDIT, P.DOC_VIEW_APPROVED, P.AUDIT_VIEW,
    }),
    RoleCode.MAKER: frozenset({P.REPO_VIEW, P.DOC_VIEW_ALL, P.DOC_UPLOAD}),
    RoleCode.CHECKER: frozenset({P.REPO_VIEW, P.DOC_VIEW_SUBMITTED, P.DOC_APPROVE}),
    RoleCode.VIEWER: frozenset({P.PLATFORM_USE, P.REPO_LIST, P.REPO_VIEW, P.DOC_VIEW_APPROVED}),
    RoleCode.APPROVER: frozenset({P.REPO_VIEW, P.DOC_VIEW_SUBMITTED}),
    RoleCode.AUDITOR: frozenset({P.REPO_VIEW, P.DOC_VIEW_ALL, P.HISTORY_VIEW, P.AUDIT_VIEW}),
}

# Permissions that make someone a decider: they get the Approvals page.
DECIDING_PERMISSIONS = frozenset({P.DOC_APPROVE})


class NodeType(StrEnum):
    """Node types the code relies on. A hierarchy's levels may name others."""

    ROOT = "ROOT"
    DOC_REPO = "DOC_REPO"


# Roles a person may be given in a root's groups (a source system's admins and users).
GROUP_ROLES: dict[str, tuple[RoleCode, ...]] = {
    "ADMINS": (RoleCode.ADMIN,),
    "USERS": (RoleCode.VIEWER,),
}

# Roles a person may be given in a repository's user groups (OWNER only by creating the node, or by
# hand-over).
REPO_GROUP_ROLES: tuple[RoleCode, ...] = (RoleCode.ADMIN, RoleCode.MAKER, RoleCode.CHECKER, RoleCode.VIEWER)

# A new repository's default user group (the owner is in it, as OWNER).
DEFAULT_GROUP_NAME = "Users"

# The groups a root gets, with the role everyone joins with (None: nobody joins automatically).
ROOT_GROUPS: dict[str, RoleCode | None] = {"ADMINS": None, "USERS": RoleCode.VIEWER}

# Roles a team may be given on a node through a team grant: read-only ones only.
TEAM_ROLES = (RoleCode.VIEWER, RoleCode.AUDITOR)

# Seeded teams (TEAM groups at the PLATFORM root); platform admins manage their members.
TEAMS: dict[str, str] = {"COMPLIANCE": "Compliance", "AUDIT": "Audit"}
