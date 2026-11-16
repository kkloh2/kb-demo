"""The access model's rules.

The one access check: may person X do permission P at node N? Yes when X holds, at N itself, a
role carrying P: as an active member of one of N's own user groups, assigned that role in it, or
through a team grant at N for a team X is an active member of. User groups are just names; each
member holds their own roles in each group they're in.
Nothing is inherited from parent nodes.

Callers commit unless a function says it commits itself.
"""

import re
import uuid
from datetime import datetime
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.access.catalog import (
    DEFAULT_GROUP_NAME,
    DECIDING_PERMISSIONS,
    GROUP_ROLES,
    REPO_GROUP_ROLES,
    PERMISSIONS,
    PLATFORM_NAME,
    ROLE_PERMISSIONS,
    ROLES,
    ROOT_GROUPS,
    TEAM_ROLES,
    TEAMS,
    NodeType,
    P,
    RoleCode,
    SystemCode,
)
from app.access.models import (
    AppUser,
    DefaultGrant,
    GroupType,
    Hierarchy,
    HierarchyNode,
    NodeStatus,
    NodeTeamGrant,
    Permission,
    Role,
    RolePermission,
    SourceSystem,
    Status,
    UserGroup,
    UserGroupMember,
    UserGroupMemberRole,
)
from app.auth.errors import Unauthenticated
from app.auth.identity import Identity
from app.auth.service import revoke_sessions
from app.core.config import get_settings
from app.core.errors import Conflict, InvalidRequest, NotFound
from app.audit import service as audit
from app.audit.catalog import register_actions
from app.db.base import utcnow, uuid7

register_actions("PLATFORM", {
    "USER_ADDED": ("access", "User added", "A platform admin added someone by LAN ID."),
    "USER_UPDATED": ("access", "User details changed", "Name, email, title or department changed."),
    "USER_DEACTIVATED": ("access", "Access switched off"),
    "USER_ACTIVATED": ("access", "Access switched on"),
    "PLATFORM_ADMIN_GRANTED": ("access", "Made a platform admin"),
    "PLATFORM_ADMIN_REVOKED": ("access", "No longer a platform admin"),
    "ROOT_GROUP_ROLES_SET": ("access", "Roles in a source system's admins or users changed"),
    "SOURCE_SYSTEM_CREATED": ("configuration", "Source system created"),
    "HIERARCHY_CREATED": ("configuration", "Hierarchy created"),
    "TEAM_MEMBERS_SET": ("access", "Team members changed"),
    "DEFAULT_GRANT_ADDED": ("access", "Team given default access"),
    "DEFAULT_GRANT_REMOVED": ("access", "Team's default access removed"),
    "OWNER_REASSIGNED": ("access", "Owner reassigned by a platform admin"),
    # at a node (e.g. a repository): recorded under that node's source system
    "NODE_CREATED": ("configuration", "Created"),
    "NODE_UPDATED": ("configuration", "Renamed or edited"),
    "NODE_DELETED": ("configuration", "Deleted"),
    "NODE_RESTORED": ("configuration", "Restored"),
    "OWNERSHIP_TRANSFERRED": ("access", "Ownership handed over"),
    "GROUP_CREATED": ("access", "User group created"),
    "GROUP_RENAMED": ("access", "User group renamed"),
    "GROUP_DELETED": ("access", "User group deleted"),
    "MEMBER_GROUPS_SET": ("access", "User groups and roles changed"),
})

ACTIVE = Status.ACTIVE.value
REPO_GROUP_TYPES = (GroupType.MEMBERS.value, GroupType.CUSTOM.value)  # a repository's user groups
# How a node's groups are listed: a root's admins then users; a repository's default group, then the rest.
GROUP_ORDER = (GroupType.ADMINS.value, GroupType.USERS.value, GroupType.MEMBERS.value, GroupType.CUSTOM.value)

# Called when who holds which role changes: (db, node id or None, user id or None). A node: roles
# there changed for anyone; a user: their roles changed everywhere (switched off or on). Listeners
# run before the change commits (e.g. approvals updates who each waiting task is assigned to).
RolesChanged = Callable[[Session, "uuid.UUID | None", "uuid.UUID | None"], None]
_roles_changed_listeners: list[RolesChanged] = []


def on_roles_changed(listener: RolesChanged) -> RolesChanged:
    _roles_changed_listeners.append(listener)
    return listener


def _roles_changed(db: Session, node_id: uuid.UUID | None = None, user_id: uuid.UUID | None = None) -> None:
    db.flush()
    for listener in _roles_changed_listeners:
        listener(db, node_id, user_id)
INACTIVE = Status.INACTIVE.value
SYSTEM_ROLES_CLAIM = "system_roles"


# --------------------------------------------------------------------------- reference data


def sync_reference(db: Session) -> None:
    """Make roles, permissions and teams match the catalog, and create the PLATFORM system with its
    root, admins and users groups if it's missing. Runs at every start-up; never removes anything.
    The caller commits."""
    roles = {r.code: r for r in db.scalars(select(Role))}
    for position, (code, (name, description)) in enumerate(ROLES.items()):
        role = roles.get(code) or Role(code=code.value)
        role.name, role.description, role.position = name, description, position
        db.add(role)
        roles[code.value] = role
    permissions = {p.code: p for p in db.scalars(select(Permission))}
    for code, name in PERMISSIONS.items():
        permission = permissions.get(code) or Permission(code=code.value)
        permission.name = name
        db.add(permission)
        permissions[code.value] = permission
    db.flush()
    wanted = {(roles[r].id, permissions[p].id) for r, ps in ROLE_PERMISSIONS.items() for p in ps}
    current = {(rp.role_id, rp.permission_id): rp for rp in db.scalars(select(RolePermission))}
    for key in wanted - current.keys():
        db.add(RolePermission(role_id=key[0], permission_id=key[1]))
    for key in current.keys() - wanted:
        db.delete(current[key])

    system = db.scalar(select(SourceSystem).where(SourceSystem.code == SystemCode.PLATFORM.value))
    if system is None:
        system = SourceSystem(code=SystemCode.PLATFORM.value, name=PLATFORM_NAME)
        db.add(system)
        db.flush()
        create_root(db, None, system, PLATFORM_NAME, [NodeType.ROOT.value])
    else:  # keep its names in step with the catalog
        root = root_node(db, SystemCode.PLATFORM)
        system.name = root.name = root.hierarchy.name = PLATFORM_NAME
        for group in node_groups(db, root.id):
            group.name = f"{PLATFORM_NAME} {group.group_type.lower()}"
    db.flush()

    platform_root = root_node(db, SystemCode.PLATFORM)
    for code, name in TEAMS.items():
        if db.scalar(select(UserGroup).where(UserGroup.code == f"TEAM:{code}")) is None:
            db.add(UserGroup(hierarchy_node_id=platform_root.id, code=f"TEAM:{code}", name=name,
                             group_type=GroupType.TEAM.value))
    db.flush()


def seed_platform_admins(db: Session) -> list[str]:
    """When nobody is ADMIN at the PLATFORM root, give it to settings.bootstrap_system_admins.
    A missing user is created with placeholder details, filled in at their first sign-in.
    Returns the LAN IDs that were given ADMIN. The caller commits."""
    root = root_node(db, SystemCode.PLATFORM)
    if holders_of(db, root.id, RoleCode.ADMIN):
        return []
    given = []
    for lan_id in sorted({x.strip().lower() for x in get_settings().bootstrap_system_admins if x.strip()}):
        user = get_user(db, lan_id)
        if user is None:
            user = AppUser(lan_id=lan_id, display_name=lan_id, email=f"{lan_id}@pending.invalid")
            db.add(user)
            db.flush()
        _grant(db, None, _ensure_member(db, None, node_group(db, root.id, "ADMINS"), user), RoleCode.ADMIN)
        given.append(lan_id)
    db.flush()
    return given


# --------------------------------------------------------------------------- lookups


def get_user(db: Session, lan_id: str) -> AppUser | None:
    return db.scalar(select(AppUser).where(AppUser.lan_id == lan_id.strip().lower()))


def require_user(db: Session, lan_id: str) -> AppUser:
    user = get_user(db, lan_id)
    if user is None:
        raise NotFound(f"No user with LAN ID {lan_id.strip().lower()!r}. They get one when they first sign in, "
                       f"or a platform admin can add them.")
    return user


def root_node(db: Session, system: SystemCode | str) -> HierarchyNode:
    node = db.scalar(
        select(HierarchyNode).join(Hierarchy).join(SourceSystem)
        .where(SourceSystem.code == str(system), HierarchyNode.parent_id.is_(None))
    )
    if node is None:
        raise NotFound(f"{system} isn't set up yet. A platform admin creates it in Administration.")
    return node


def get_node(db: Session, node_id: uuid.UUID, *, include_deleted: bool = False) -> HierarchyNode:
    node = db.get(HierarchyNode, node_id)
    if node is None or (node.status == NodeStatus.DELETED.value and not include_deleted):
        raise NotFound("Not found.")
    return node


def system_of(db: Session, node: HierarchyNode) -> str:
    return db.scalar(select(SourceSystem.code).join(Hierarchy).where(Hierarchy.id == node.hierarchy_id))


def role_ids(db: Session) -> dict[str, uuid.UUID]:
    return {code: rid for rid, code in db.execute(select(Role.id, Role.code))}


def _node_group(db: Session, node_id: uuid.UUID, group_type: str) -> UserGroup | None:
    return db.scalar(select(UserGroup).where(
        UserGroup.hierarchy_node_id == node_id, UserGroup.group_type == group_type, UserGroup.status == ACTIVE))


def node_group(db: Session, node_id: uuid.UUID, group_type: str) -> UserGroup:
    group = _node_group(db, node_id, group_type)
    if group is None:
        raise NotFound(f"That node has no {group_type.lower()} group.")
    return group


def node_groups(db: Session, node_id: uuid.UUID) -> list[UserGroup]:
    """The node's own groups (not teams), e.g. ADMINS and USERS at a root, MEMBERS at a repository."""
    order = {t: i for i, t in enumerate(GROUP_ORDER)}
    groups = db.scalars(select(UserGroup).where(UserGroup.hierarchy_node_id == node_id, UserGroup.status == ACTIVE,
                                                UserGroup.group_type != GroupType.TEAM.value)).all()
    return sorted(groups, key=lambda g: (order.get(g.group_type, 99), g.name.lower()))


def team(db: Session, code: str) -> UserGroup:
    group = db.scalar(select(UserGroup).where(UserGroup.code == f"TEAM:{code.strip().upper()}"))
    if group is None:
        raise NotFound(f"No team {code.strip().upper()!r}.")
    return group


# --------------------------------------------------------------------------- the access check


def _member_roles_query(user_id: uuid.UUID):
    """(node id, role code) for every role the user holds in a node's own groups."""
    return (
        select(UserGroup.hierarchy_node_id, Role.code)
        .join(UserGroupMember, UserGroupMember.group_id == UserGroup.id)
        .join(UserGroupMemberRole, UserGroupMemberRole.group_member_id == UserGroupMember.id)
        .join(Role, Role.id == UserGroupMemberRole.role_id)
        .join(HierarchyNode, HierarchyNode.id == UserGroup.hierarchy_node_id)
        .where(
            UserGroupMember.user_id == user_id,
            UserGroupMember.status == ACTIVE,
            UserGroupMemberRole.status == ACTIVE,
            UserGroup.status == ACTIVE,
            UserGroup.group_type != GroupType.TEAM.value,
            HierarchyNode.status == NodeStatus.ACTIVE.value,
        )
    )


def _team_roles_query(user_id: uuid.UUID):
    """(node id, role code) for every role the user holds through a team grant."""
    return (
        select(NodeTeamGrant.hierarchy_node_id, Role.code)
        .join(Role, Role.id == NodeTeamGrant.role_id)
        .join(UserGroup, UserGroup.id == NodeTeamGrant.team_group_id)
        .join(UserGroupMember, UserGroupMember.group_id == UserGroup.id)
        .join(HierarchyNode, HierarchyNode.id == NodeTeamGrant.hierarchy_node_id)
        .where(
            UserGroupMember.user_id == user_id,
            UserGroupMember.status == ACTIVE,
            NodeTeamGrant.status == ACTIVE,
            UserGroup.status == ACTIVE,
            HierarchyNode.status == NodeStatus.ACTIVE.value,
        )
    )


def roles_by_node(db: Session, user_id: uuid.UUID, node_ids: Iterable[uuid.UUID] | None = None) -> dict[uuid.UUID, set[str]]:
    """Node id -> the roles the user holds there (own membership and team grants), active nodes only."""
    member, teams = _member_roles_query(user_id), _team_roles_query(user_id)
    if node_ids is not None:
        ids = list(node_ids)
        member = member.where(UserGroup.hierarchy_node_id.in_(ids))
        teams = teams.where(NodeTeamGrant.hierarchy_node_id.in_(ids))
    held: dict[uuid.UUID, set[str]] = {}
    for node_id, code in [*db.execute(member), *db.execute(teams)]:
        held.setdefault(node_id, set()).add(code)
    return held


def roles_at(db: Session, user_id: uuid.UUID, node_id: uuid.UUID) -> set[str]:
    return roles_by_node(db, user_id, [node_id]).get(node_id, set())


def permissions_for(roles: Iterable[str]) -> set[str]:
    return {p.value for r in roles for p in ROLE_PERMISSIONS.get(RoleCode(r), ())}


def can(db: Session, user_id: uuid.UUID, node_id: uuid.UUID, permission: P | str) -> bool:
    return str(permission) in permissions_for(roles_at(db, user_id, node_id))


def holders_of(db: Session, node_id: uuid.UUID, role: RoleCode) -> list[AppUser]:
    """Active members holding the role at the node (in any of its own groups; not through teams)."""
    return list(db.scalars(
        select(AppUser).distinct()
        .join(UserGroupMember, UserGroupMember.user_id == AppUser.id)
        .join(UserGroup, UserGroup.id == UserGroupMember.group_id)
        .join(UserGroupMemberRole, UserGroupMemberRole.group_member_id == UserGroupMember.id)
        .join(Role, Role.id == UserGroupMemberRole.role_id)
        .where(UserGroup.hierarchy_node_id == node_id, UserGroup.group_type != GroupType.TEAM.value,
               UserGroup.status == ACTIVE, UserGroupMember.status == ACTIVE, UserGroupMemberRole.status == ACTIVE,
               Role.code == role.value)
        .order_by(AppUser.display_name, AppUser.lan_id)))


def held_roles(user_id: uuid.UUID):
    """One SQL subquery of (node_id, role_id): every role the person holds at a node in its own groups,
    on active nodes. Starts from the person's memberships (indexed by user). Teams aren't included:
    they only give read-only roles."""
    return (select(UserGroup.hierarchy_node_id.label("node_id"), UserGroupMemberRole.role_id.label("role_id"))
            .select_from(UserGroupMember)
            .join(UserGroup, UserGroup.id == UserGroupMember.group_id)
            .join(HierarchyNode, HierarchyNode.id == UserGroup.hierarchy_node_id)
            .join(UserGroupMemberRole, UserGroupMemberRole.group_member_id == UserGroupMember.id)
            .where(UserGroupMember.user_id == user_id, UserGroupMember.status == ACTIVE,
                   UserGroup.status == ACTIVE, UserGroup.group_type != GroupType.TEAM.value,
                   HierarchyNode.status == NodeStatus.ACTIVE.value, UserGroupMemberRole.status == ACTIVE)
            .distinct().subquery("held_roles"))


def system_roles_claim(db: Session, user: AppUser) -> dict[str, list[str]]:
    """{system code: roles held at its root}. A system where the person holds roles only below the
    root is listed with []."""
    claim: dict[str, set[str]] = {}
    rows = db.execute(
        select(SourceSystem.code, HierarchyNode.parent_id, HierarchyNode.id)
        .join(Hierarchy, Hierarchy.source_system_id == SourceSystem.id)
        .join(HierarchyNode, HierarchyNode.hierarchy_id == Hierarchy.id)
        .where(HierarchyNode.id.in_(list(roles_by_node(db, user.id).keys())))
    )
    held = roles_by_node(db, user.id)
    for system, parent_id, node_id in rows:
        claim.setdefault(system, set())
        if parent_id is None:
            claim[system] |= held.get(node_id, set())
    return {system: sorted(roles) for system, roles in sorted(claim.items())}


@dataclass(frozen=True)
class NodeAccess:
    system: str
    node: HierarchyNode
    roles: list[str]
    permissions: list[str]


@dataclass(frozen=True)
class MyAccess:
    system_roles: dict[str, list[str]]
    nodes: list[NodeAccess]
    platform_admin: bool
    can_decide: bool


def my_access(db: Session, user: AppUser) -> MyAccess:
    held = roles_by_node(db, user.id)
    nodes = db.scalars(select(HierarchyNode).where(HierarchyNode.id.in_(list(held)))).all()
    systems = dict(db.execute(select(Hierarchy.id, SourceSystem.code).join(SourceSystem)).all())
    items = [
        NodeAccess(systems[n.hierarchy_id], n, sorted(held[n.id]), sorted(permissions_for(held[n.id])))
        for n in sorted(nodes, key=lambda n: n.path)
    ]
    platform_root = root_node(db, SystemCode.PLATFORM)
    deciding = {p.value for p in DECIDING_PERMISSIONS}
    return MyAccess(
        system_roles=system_roles_claim(db, user),
        nodes=items,
        platform_admin=P.PLATFORM_MANAGE.value in permissions_for(held.get(platform_root.id, set())),
        can_decide=any(deciding & set(i.permissions) for i in items),
    )


# --------------------------------------------------------------------------- sign-in hooks


def record_sign_in(db: Session, identity: Identity) -> None:
    """Create or refresh the person from the directory. Refuses people whose access was switched off.
    Adds the person to every group that everyone joins (e.g. PLATFORM and DOC_HUB members as VIEWER)."""
    user = get_user(db, identity.lan_id)
    if user is not None and user.status != ACTIVE:
        raise Unauthenticated("Your Data Hub access has been switched off. Ask a platform admin.")
    fields = ("display_name", "email", "directory_department", "title")
    before = {f: getattr(user, f) for f in fields} if user is not None else None
    if user is None:
        user = AppUser(lan_id=identity.lan_id)
        db.add(user)
    user.display_name, user.email = identity.display_name, identity.email
    user.directory_department, user.title = identity.department, identity.title
    after = {f: getattr(user, f) for f in fields}
    if before is not None and before != after:
        db.flush()
        record(db, user, "USER_UPDATED", "user", user.lan_id, None, {**audit.diff(before, after), "by": "directory"})
    user.last_login_at = utcnow()
    db.flush()
    _auto_join(db, user)


def add_access_claim(db: Session, identity: Identity) -> dict[str, Any]:
    user = get_user(db, identity.lan_id)
    return {SYSTEM_ROLES_CLAIM: system_roles_claim(db, user) if user else {}}


def _auto_join(db: Session, user: AppUser) -> None:
    """Join every group with an auto-join role, unless the person already has (or had) a
    membership there: someone deliberately removed stays removed."""
    codes = {rid: code for code, rid in role_ids(db).items()}
    for group in db.scalars(select(UserGroup).where(UserGroup.auto_join_role_id.is_not(None),
                                                    UserGroup.status == ACTIVE)):
        exists = db.scalar(select(UserGroupMember.id).where(
            UserGroupMember.group_id == group.id, UserGroupMember.user_id == user.id))
        if exists is None:
            _grant(db, None, _ensure_member(db, None, group, user), RoleCode(codes[group.auto_join_role_id]))


# --------------------------------------------------------------------------- members of a node


@dataclass(frozen=True)
class MemberGroup:
    group: UserGroup
    roles: list[str]  # what they hold through it: the group's roles and their own there, in catalog order


@dataclass(frozen=True)
class Member:
    user: AppUser
    roles: list[str]  # in catalog order
    added_at: datetime | None = None  # when they first joined (these groups)
    updated_at: datetime | None = None  # the latest change to their membership or roles here
    groups: tuple[MemberGroup, ...] = ()  # the node's groups they're in


@dataclass(frozen=True)
class TeamGrantView:
    team_code: str
    team_name: str
    role: str
    from_default: bool


def _in_order(codes: Iterable[str]) -> list[str]:
    order = {code.value: i for i, code in enumerate(ROLES)}
    return sorted(set(codes), key=lambda c: order.get(c, 99))


def list_members(db: Session, node_id: uuid.UUID, group_type: str | None = None) -> list[Member]:
    """The active members of the node's own groups (or of one type of them), with their roles in each,
    sorted by name."""
    groups = {g.id: g for g in node_groups(db, node_id) if group_type is None or g.group_type == group_type}
    own: dict[uuid.UUID, list[tuple[str, datetime]]] = {}
    for m_id, code, updated in db.execute(
        select(UserGroupMemberRole.group_member_id, Role.code, UserGroupMemberRole.updated_at)
        .join(Role, Role.id == UserGroupMemberRole.role_id)
        .join(UserGroupMember, UserGroupMember.id == UserGroupMemberRole.group_member_id)
        .where(UserGroupMember.group_id.in_(list(groups)), UserGroupMemberRole.status == ACTIVE)
    ):
        own.setdefault(m_id, []).append((code, updated))
    by_user: dict[uuid.UUID, tuple[AppUser, list[MemberGroup], list[datetime], list[datetime]]] = {}
    for m, user in db.execute(
        select(UserGroupMember, AppUser).join(AppUser, AppUser.id == UserGroupMember.user_id)
        .where(UserGroupMember.group_id.in_(list(groups)), UserGroupMember.status == ACTIVE)
    ).all():
        mine = own.get(m.id, [])
        roles = _in_order(c for c, _ in mine)
        if not roles and groups[m.group_id].group_type not in REPO_GROUP_TYPES:
            continue  # a root group's member without roles is no longer in it
        entry = by_user.setdefault(user.id, (user, [], [], []))
        entry[1].append(MemberGroup(groups[m.group_id], roles))
        entry[2].append(m.added_at)
        entry[3].extend([m.updated_at, *(t for _, t in mine)])
    order = {g: i for i, g in enumerate(groups)}
    members = [Member(u, _in_order(r for mg in gs for r in mg.roles), min(a), max(t),
                      tuple(sorted(gs, key=lambda mg: order[mg.group.id])))
               for u, gs, a, t in by_user.values()]
    return sorted(members, key=lambda m: (m.user.display_name.lower(), m.user.lan_id))


def team_grants(db: Session, node_id: uuid.UUID) -> list[TeamGrantView]:
    return [
        TeamGrantView(g.team.code.removeprefix("TEAM:"), g.team.name, g.role.code, g.default_grant_id is not None)
        for g in db.scalars(select(NodeTeamGrant).where(
            NodeTeamGrant.hierarchy_node_id == node_id, NodeTeamGrant.status == ACTIVE))
    ]


def set_member_roles(db: Session, actor: AppUser, node: HierarchyNode, lan_id: str, roles: list[str]) -> Member:
    """Make the person's roles at the node exactly `roles`, across the node's groups (at a root:
    ADMIN in admins, VIEWER in users; in a repository: its members). OWNER is untouched: it moves
    only by hand-over. [] removes them from the node. Commits."""
    groups = node_groups(db, node.id)
    home: dict[RoleCode, UserGroup] = {}
    for g in groups:
        for r in GROUP_ROLES.get(g.group_type, ()):
            home.setdefault(r, g)
    wanted: set[RoleCode] = set()
    for name in roles:
        try:
            code = RoleCode(name.strip().upper())
        except ValueError:
            raise InvalidRequest(f"Unknown role {name!r}.") from None
        if code not in home:
            raise InvalidRequest(f"Roles here are {', '.join(r.value for r in home)}; not {code.value}.")
        wanted.add(code)
    if {RoleCode.MAKER, RoleCode.CHECKER} <= wanted:
        raise Conflict("One person can't be both maker and checker here.")
    user = require_user(db, lan_id)
    if user.status != ACTIVE:
        raise Conflict(f"{user.display_name}'s access is switched off.")
    platform_root = root_node(db, SystemCode.PLATFORM)
    if node.id == platform_root.id and user.id == actor.id and RoleCode.ADMIN not in wanted:
        raise Conflict("You can't remove your own platform admin role.")

    before = sorted(roles_held_in_groups(db, user.id, node.id))
    for g in groups:
        member = db.scalar(select(UserGroupMember).where(UserGroupMember.group_id == g.id,
                                                         UserGroupMember.user_id == user.id))
        mine = {r for r, home_group in home.items() if home_group.id == g.id and r in wanted}
        if member is None and not mine:
            continue
        member = member or _ensure_member(db, actor, g, user)
        current = {r.role.code: r for r in member.roles if r.status == ACTIVE}
        for code, row in current.items():
            if code != RoleCode.OWNER.value and RoleCode(code) not in mine:
                row.status = INACTIVE
        for code in mine:
            _grant(db, actor, member, code)
        if not mine and RoleCode.OWNER.value not in current:
            member.status = INACTIVE
    db.flush()
    after = sorted(roles_held_in_groups(db, user.id, node.id))
    if before != after:
        admin = RoleCode.ADMIN.value
        if node.id == platform_root.id and (admin in before) != (admin in after):
            record(db, actor, "PLATFORM_ADMIN_GRANTED" if admin in after else "PLATFORM_ADMIN_REVOKED", "user",
                   user.lan_id, node.id, {})
        else:
            record(db, actor, "ROOT_GROUP_ROLES_SET", "user", user.lan_id, node.id,
                   {"system": system_of(db, node), "before": before, "after": after})
        if node.parent_id is None:  # a root role is in the token: end their sessions so it's current
            revoke_sessions(db, user.lan_id, reason="roles_changed")
    _roles_changed(db, node.id)
    db.commit()
    return next((m for m in list_members(db, node.id) if m.user.id == user.id), Member(user, []))


def roles_held_in_groups(db: Session, user_id: uuid.UUID, node_id: uuid.UUID) -> set[str]:
    return set(db.scalars(
        select(Role.code)
        .join(UserGroupMemberRole, UserGroupMemberRole.role_id == Role.id)
        .join(UserGroupMember, UserGroupMember.id == UserGroupMemberRole.group_member_id)
        .join(UserGroup, UserGroup.id == UserGroupMember.group_id)
        .where(UserGroup.hierarchy_node_id == node_id, UserGroup.group_type != GroupType.TEAM.value,
               UserGroup.status == ACTIVE, UserGroupMember.user_id == user_id, UserGroupMember.status == ACTIVE,
               UserGroupMemberRole.status == ACTIVE)))


def transfer_ownership(db: Session, actor: AppUser, node: HierarchyNode, new_owner_lan_id: str, *,
                       recovery: bool = False) -> None:
    """Hand the node's OWNER role to someone else. The previous owner stays as ADMIN. Commits."""
    new_owner = require_user(db, new_owner_lan_id)
    if new_owner.status != ACTIVE:
        raise Conflict(f"{new_owner.display_name}'s access is switched off.")
    group = owner_group(db, node.id)
    previous = holders_of(db, node.id, RoleCode.OWNER)
    if previous and previous[0].id == new_owner.id:
        raise Conflict(f"{new_owner.display_name} already owns it.")
    for old in previous:
        old_member = _ensure_member(db, actor, group, old)
        for r in old_member.roles:
            if r.status == ACTIVE and r.role.code == RoleCode.OWNER.value:
                r.status = INACTIVE
        _grant(db, actor, old_member, RoleCode.ADMIN)
    _grant(db, actor, _ensure_member(db, actor, group, new_owner), RoleCode.OWNER)
    record(db, actor, "OWNER_REASSIGNED" if recovery else "OWNERSHIP_TRANSFERRED", "node", str(node.id), node.id,
           {"from": [u.lan_id for u in previous], "to": new_owner.lan_id})
    _roles_changed(db, node.id)
    db.commit()


def owner_group(db: Session, node_id: uuid.UUID) -> UserGroup:
    """Where a node's OWNER (and an owner's ADMIN) are held: its MEMBERS group, or a root's admins."""
    return _node_group(db, node_id, GroupType.MEMBERS.value) or node_group(db, node_id, GroupType.ADMINS.value)


def _ensure_member(db: Session, actor: AppUser | None, group: UserGroup, user: AppUser) -> UserGroupMember:
    member = db.scalar(select(UserGroupMember).where(
        UserGroupMember.group_id == group.id, UserGroupMember.user_id == user.id))
    if member is None:
        member = UserGroupMember(group_id=group.id, user_id=user.id, added_by_id=actor.id if actor else None)
        db.add(member)
        db.flush()
    elif member.status != ACTIVE:
        member.status = ACTIVE
        member.added_by_id, member.added_at = (actor.id if actor else None), utcnow()
    return member


def _grant(db: Session, actor: AppUser | None, member: UserGroupMember, role: RoleCode) -> None:
    role_id = role_ids(db)[role.value]
    row = db.scalar(select(UserGroupMemberRole).where(
        UserGroupMemberRole.group_member_id == member.id, UserGroupMemberRole.role_id == role_id))
    if row is None:
        db.add(UserGroupMemberRole(group_member_id=member.id, role_id=role_id,
                                   granted_by_id=actor.id if actor else None))
    elif row.status != ACTIVE:
        row.status, row.granted_by_id, row.granted_at = ACTIVE, (actor.id if actor else None), utcnow()
    member.status = ACTIVE
    db.flush()
    db.expire(member, ["roles"])


# --------------------------------------------------------------------------- a repository's user groups


@dataclass(frozen=True)
class GroupView:
    group: UserGroup
    member_count: int
    default: bool  # the default group (holds the owner; can't be removed)


def repo_groups(db: Session, node_id: uuid.UUID) -> list[GroupView]:
    """The node's user groups: its default group first, then the others by name."""
    groups = [g for g in node_groups(db, node_id) if g.group_type in REPO_GROUP_TYPES]
    counts = dict(db.execute(select(UserGroupMember.group_id, func.count()).where(
        UserGroupMember.group_id.in_([g.id for g in groups]), UserGroupMember.status == ACTIVE)
        .group_by(UserGroupMember.group_id)).all())
    return [GroupView(g, counts.get(g.id, 0), g.group_type == GroupType.MEMBERS.value) for g in groups]


def group_named(db: Session, node_id: uuid.UUID, name: str) -> UserGroup | None:
    """The node's user group with this name (any case), e.g. "default" for a group named default."""
    wanted = " ".join(name.split()).lower()
    return next((g for g in node_groups(db, node_id)
                 if g.group_type in REPO_GROUP_TYPES and g.name.lower() == wanted), None)


def _in_group_with_role(group_id: uuid.UUID, role: str):
    """Active members of the group who were assigned the role in it."""
    return (select(UserGroupMember.user_id)
            .join(UserGroup, UserGroup.id == UserGroupMember.group_id)
            .join(UserGroupMemberRole, UserGroupMemberRole.group_member_id == UserGroupMember.id)
            .join(Role, Role.id == UserGroupMemberRole.role_id)
            .where(UserGroupMember.group_id == group_id, UserGroupMember.status == ACTIVE, UserGroup.status == ACTIVE,
                   UserGroupMemberRole.status == ACTIVE, Role.code == role).subquery())


def holds_in_group(db: Session, user_id: uuid.UUID, group_id: uuid.UUID, role: str) -> bool:
    q = _in_group_with_role(group_id, role)
    return db.scalar(select(q.c.user_id).where(q.c.user_id == user_id)) is not None


def holders_in_group(db: Session, group_id: uuid.UUID, role: str) -> list[AppUser]:
    q = _in_group_with_role(group_id, role)
    return list(db.scalars(select(AppUser).where(AppUser.id.in_(select(q.c.user_id)))))


def repo_group(db: Session, node_id: uuid.UUID, group_id: uuid.UUID) -> UserGroup:
    group = db.get(UserGroup, group_id)
    if (group is None or group.hierarchy_node_id != node_id or group.status != ACTIVE
            or group.group_type not in REPO_GROUP_TYPES):
        raise NotFound("No such user group here.")
    return group


def _wanted_roles(roles: Iterable[str]) -> list[str]:
    allowed = {r.value for r in REPO_GROUP_ROLES}
    wanted = set()
    for name in roles:
        code = name.strip().upper()
        if code not in allowed:
            raise InvalidRequest(f"Roles in a user group are {', '.join(sorted(allowed))}; not {name!r}.")
        wanted.add(code)
    return _in_order(wanted)


def _check_name(db: Session, node_id: uuid.UUID, name: str, group_id: uuid.UUID | None = None) -> str:
    name = " ".join(name.split())
    if not name:
        raise InvalidRequest("Give the user group a name.")
    for g in node_groups(db, node_id):
        if g.id != group_id and g.name.lower() == name.lower():
            raise Conflict(f"There's already a user group called {g.name}.")
    return name


def create_group(db: Session, actor: AppUser, node: HierarchyNode, name: str) -> UserGroup:
    """A new user group at the node: a name; people are added to it with their own roles. Commits."""
    name = _check_name(db, node.id, name)
    group_id = uuid7()
    prefix = node_group(db, node.id, GroupType.MEMBERS.value).code.removesuffix("MEMBERS")
    group = UserGroup(id=group_id, hierarchy_node_id=node.id, code=f"{prefix}{group_id}", name=name,
                      group_type=GroupType.CUSTOM.value)
    db.add(group)
    db.flush()
    record(db, actor, "GROUP_CREATED", "user_group", group.code, node.id, {"name": name})
    db.commit()
    return group


def update_group(db: Session, actor: AppUser, node: HierarchyNode, group_id: uuid.UUID, name: str) -> UserGroup:
    """Rename the group. Commits."""
    group = repo_group(db, node.id, group_id)
    name = _check_name(db, node.id, name, group.id)
    if name != group.name:
        record(db, actor, "GROUP_RENAMED", "user_group", group.code, node.id, {"before": group.name, "after": name})
        group.name, group.updated_at = name, utcnow()
    db.commit()
    return group


def _keep_own_management(db: Session, actor: AppUser, node: HierarchyNode, what: str) -> None:
    """Refuse (and undo) a change that would leave the person making it unable to manage the node's
    users and groups: they'd be locked out mid-way. The owner always keeps it."""
    db.flush()
    if not can(db, actor.id, node.id, P.MEMBERS_MANAGE):
        db.rollback()
        raise Conflict(f"{what} would take away your own right to manage {node.name}'s users and groups. "
                       "Ask its owner or another admin to do it.")


def delete_group(db: Session, actor: AppUser, node: HierarchyNode, group_id: uuid.UUID) -> int:
    """Delete a user group (kept, inactive): everyone in it loses the roles they held in it, at once.
    The default group can't be deleted. Returns how many people were in it. Commits."""
    group = repo_group(db, node.id, group_id)
    if group.group_type == GroupType.MEMBERS.value:
        raise Conflict("The default user group can't be deleted: it holds the owner.")
    members = db.scalars(select(UserGroupMember).where(UserGroupMember.group_id == group.id,
                                                       UserGroupMember.status == ACTIVE)).all()
    for member in members:
        for row in member.roles:
            if row.status == ACTIVE:
                row.status = INACTIVE
        member.status = INACTIVE
    group.status, group.updated_at = INACTIVE, utcnow()
    _keep_own_management(db, actor, node, f"Deleting {group.name}")
    record(db, actor, "GROUP_DELETED", "user_group", group.code, node.id,
           {"name": group.name, "members": len(members)})
    _roles_changed(db, node.id)
    db.commit()
    return len(members)


def set_member_groups(db: Session, actor: AppUser, node: HierarchyNode, lan_id: str,
                      assignments: dict[uuid.UUID, list[str]]) -> Member:
    """Make the person's user groups and roles at the node exactly `assignments` ({group id: roles}).
    A group with no roles takes them out of it. The owner keeps Owner in the default group, whatever
    else changes. {} takes them out of every group. Commits."""
    groups = {g.group.id: g.group for g in repo_groups(db, node.id)}
    if set(assignments) - set(groups):
        raise InvalidRequest("Those aren't this repository's user groups.")
    wanted = {gid: set(_wanted_roles(roles)) for gid, roles in assignments.items() if roles}
    user = require_user(db, lan_id)
    if wanted and user.status != ACTIVE:
        raise Conflict(f"{user.display_name}'s access is switched off.")
    before = _assignments(db, groups.values(), user.id)
    for g in groups.values():
        member = db.scalar(select(UserGroupMember).where(UserGroupMember.group_id == g.id,
                                                         UserGroupMember.user_id == user.id))
        roles = wanted.get(g.id, set())
        if member is None and not roles:
            continue
        member = member or _ensure_member(db, actor, g, user)
        current = {r.role.code: r for r in member.roles if r.status == ACTIVE}
        for code, row in current.items():
            if code != RoleCode.OWNER.value and code not in roles:
                row.status = INACTIVE
        for code in roles:
            _grant(db, actor, member, RoleCode(code))
        if not roles and RoleCode.OWNER.value not in current:
            member.status = INACTIVE
        elif member.status != ACTIVE:
            member.status = ACTIVE
    db.flush()
    if user.id == actor.id:
        _keep_own_management(db, actor, node, "This change")
    after = _assignments(db, groups.values(), user.id)
    if before != after:
        record(db, actor, "MEMBER_GROUPS_SET", "user", user.lan_id, node.id, {"before": before, "after": after})
    _roles_changed(db, node.id)
    db.commit()
    return next((m for m in list_members(db, node.id) if m.user.id == user.id), Member(user, []))


def _assignments(db: Session, groups: Iterable[UserGroup], user_id: uuid.UUID) -> dict[str, list[str]]:
    """{group name: roles} the person holds, for the audit trail."""
    out = {}
    for g in groups:
        codes = db.scalars(select(Role.code).join(UserGroupMemberRole, UserGroupMemberRole.role_id == Role.id)
                           .join(UserGroupMember, UserGroupMember.id == UserGroupMemberRole.group_member_id)
                           .where(UserGroupMember.group_id == g.id, UserGroupMember.user_id == user_id,
                                  UserGroupMember.status == ACTIVE, UserGroupMemberRole.status == ACTIVE)).all()
        if codes:
            out[g.name] = _in_order(codes)
    return out


def _is_member(db: Session, group_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return db.scalar(select(UserGroupMember.id).where(UserGroupMember.group_id == group_id,
                                                      UserGroupMember.user_id == user_id,
                                                      UserGroupMember.status == ACTIVE)) is not None


# --------------------------------------------------------------------------- nodes


def create_root(db: Session, actor: AppUser | None, system: SourceSystem, name: str, levels: list[str]) -> HierarchyNode:
    """A system's hierarchy and root node, with the root's admins and users groups. Every platform
    admin joins its admins group (ADMIN); every active user joins its users group (VIEWER), and
    everyone who signs in later does too. The caller commits."""
    if db.scalar(select(Hierarchy.id).where(Hierarchy.source_system_id == system.id)) is not None:
        raise Conflict(f"{system.code} already has a hierarchy.")
    hierarchy = Hierarchy(source_system_id=system.id, code=system.code, name=name, levels=levels)
    db.add(hierarchy)
    db.flush()
    root = HierarchyNode(hierarchy_id=hierarchy.id, code=system.code, path=f"/{system.code}", name=name,
                         node_type=levels[0], created_by_id=actor.id if actor else None)
    db.add(root)
    db.flush()
    rids = role_ids(db)
    groups = {}
    for group_type, auto in ROOT_GROUPS.items():
        groups[group_type] = UserGroup(hierarchy_node_id=root.id, code=f"{system.code}:{group_type}",
                                       name=f"{name} {group_type.lower()}", group_type=group_type,
                                       auto_join_role_id=rids[auto.value] if auto else None)
        db.add(groups[group_type])
    db.flush()
    if system.code != SystemCode.PLATFORM.value:
        platform = root_node(db, SystemCode.PLATFORM)
        for admin in holders_of(db, platform.id, RoleCode.ADMIN):
            _grant(db, actor, _ensure_member(db, actor, groups["ADMINS"], admin), RoleCode.ADMIN)
        for user in db.scalars(select(AppUser).where(AppUser.status == ACTIVE)):
            _grant(db, actor, _ensure_member(db, actor, groups["USERS"], user), RoleCode.VIEWER)
        record(db, actor, "HIERARCHY_CREATED", "source_system", system.code, root.id, {"levels": levels})
    return root



def _code_for(db: Session, hierarchy_id: uuid.UUID, name: str) -> str:
    base = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")[:48] or "NODE"
    taken = set(db.scalars(select(HierarchyNode.code).where(HierarchyNode.hierarchy_id == hierarchy_id)))
    code, n = base, 2
    while code in taken:  # deleted nodes keep their code
        code, n = f"{base}_{n}", n + 1
    return code


def create_child(db: Session, actor: AppUser, parent: HierarchyNode, node_type: NodeType | str, name: str) -> HierarchyNode:
    """Create a node under `parent`, with its default user group ("Users"); the creator joins it as
    OWNER, and the
    parent's default team grants are applied. The caller commits."""
    system = system_of(db, parent)
    levels = parent.hierarchy.levels
    if parent.depth + 1 >= len(levels) or levels[parent.depth + 1] != str(node_type):
        raise InvalidRequest(f"A {node_type} can't be created here: {system}'s levels are {' > '.join(levels)}.")
    name = name.strip()
    code = _code_for(db, parent.hierarchy_id, name)
    node = HierarchyNode(hierarchy_id=parent.hierarchy_id, parent_id=parent.id, code=code,
                         path=f"{parent.path}/{code}", name=name, node_type=node_type.value, created_by_id=actor.id)
    db.add(node)
    db.flush()
    group = UserGroup(hierarchy_node_id=node.id, code=f"{system}:{code}:MEMBERS", name=DEFAULT_GROUP_NAME,
                      group_type=GroupType.MEMBERS.value)
    db.add(group)
    db.flush()
    _grant(db, actor, _ensure_member(db, actor, group, actor), RoleCode.OWNER)
    for default in db.scalars(select(DefaultGrant).where(
        DefaultGrant.parent_node_id == parent.id, DefaultGrant.child_node_type == node_type.value,
        DefaultGrant.status == ACTIVE,
    )):
        _apply_default(db, actor, default, node)
    record(db, actor, "NODE_CREATED", "node", str(node.id), node.id, {"name": name, "type": str(node_type)})
    return node


def children(db: Session, parent: HierarchyNode, *, include_deleted: bool = False) -> list[HierarchyNode]:
    query = select(HierarchyNode).where(HierarchyNode.parent_id == parent.id)
    if not include_deleted:
        query = query.where(HierarchyNode.status == NodeStatus.ACTIVE.value)
    return list(db.scalars(query.order_by(HierarchyNode.name)))


def soft_delete(db: Session, actor: AppUser, node: HierarchyNode) -> None:
    """Mark the node DELETED. Everything in it is kept. The caller commits."""
    node.status, node.deleted_by_id, node.deleted_at = NodeStatus.DELETED.value, actor.id, utcnow()
    record(db, actor, "NODE_DELETED", "node", str(node.id), node.id, {"name": node.name})


def restore(db: Session, actor: AppUser, node: HierarchyNode) -> None:
    if node.status != NodeStatus.DELETED.value:
        raise Conflict(f"{node.name} isn't deleted.")
    node.status, node.deleted_by_id, node.deleted_at = NodeStatus.ACTIVE.value, None, None
    record(db, actor, "NODE_RESTORED", "node", str(node.id), node.id, {"name": node.name})


# --------------------------------------------------------------------------- teams and default grants


@dataclass(frozen=True)
class TeamView:
    code: str
    name: str
    members: list[AppUser]


@dataclass(frozen=True)
class DefaultGrantView:
    id: uuid.UUID
    parent_system: str
    child_node_type: str
    team_code: str
    team_name: str
    role: str


def list_teams(db: Session) -> list[TeamView]:
    teams = db.scalars(select(UserGroup).where(UserGroup.group_type == GroupType.TEAM.value,
                                               UserGroup.status == ACTIVE).order_by(UserGroup.name))
    return [
        TeamView(t.code.removeprefix("TEAM:"), t.name, list(db.scalars(
            select(AppUser).join(UserGroupMember, UserGroupMember.user_id == AppUser.id)
            .where(UserGroupMember.group_id == t.id, UserGroupMember.status == ACTIVE)
            .order_by(AppUser.display_name))))
        for t in teams
    ]


def set_team_members(db: Session, actor: AppUser, team_code: str, lan_ids: list[str]) -> TeamView:
    """Make the team's members exactly these people. Commits."""
    group = team(db, team_code)
    wanted = {require_user(db, x).id: require_user(db, x) for x in lan_ids}
    current = {m.user_id: m for m in db.scalars(select(UserGroupMember).where(UserGroupMember.group_id == group.id))}
    before = sorted(m.user.lan_id for m in current.values() if m.status == ACTIVE)
    for user_id, m in current.items():
        if user_id not in wanted and m.status == ACTIVE:
            m.status = INACTIVE
    for user in wanted.values():
        _ensure_member(db, actor, group, user)
    db.flush()
    after = sorted(u.lan_id for u in wanted.values())
    if before != after:
        record(db, actor, "TEAM_MEMBERS_SET", "team", group.code, group.hierarchy_node_id,
               {"before": before, "after": after})
    db.commit()
    return next(t for t in list_teams(db) if t.code == group.code.removeprefix("TEAM:"))


def list_default_grants(db: Session) -> list[DefaultGrantView]:
    rows = db.scalars(select(DefaultGrant).where(DefaultGrant.status == ACTIVE))
    out = []
    for d in rows:
        parent = db.get(HierarchyNode, d.parent_node_id)
        out.append(DefaultGrantView(d.id, system_of(db, parent), d.child_node_type,
                                    d.team.code.removeprefix("TEAM:"), d.team.name, d.role.code))
    return sorted(out, key=lambda d: (d.parent_system, d.team_code, d.role))


def add_default_grant(db: Session, actor: AppUser, system: str, child_type: NodeType, team_code: str,
                      role: str) -> DefaultGrantView:
    """Every `child_type` node under the system's root gets the team with this role: new ones when
    created, existing ones now. Commits."""
    try:
        role_code = RoleCode(role.strip().upper())
    except ValueError:
        raise InvalidRequest(f"Unknown role {role!r}.") from None
    if role_code not in TEAM_ROLES:
        raise InvalidRequest(f"Teams can only be given {', '.join(r.value for r in TEAM_ROLES)}.")
    parent = root_node(db, system)
    if child_type.value not in parent.hierarchy.levels[1:2]:
        raise InvalidRequest(f"{system} has no {child_type.value} nodes directly under its root.")
    group = team(db, team_code)
    rid = role_ids(db)[role_code.value]
    default = db.scalar(select(DefaultGrant).where(
        DefaultGrant.parent_node_id == parent.id, DefaultGrant.child_node_type == child_type.value,
        DefaultGrant.team_group_id == group.id, DefaultGrant.role_id == rid))
    if default is not None and default.status == ACTIVE:
        raise Conflict(f"{group.name} already gets {role_code.value} there.")
    if default is None:
        default = DefaultGrant(parent_node_id=parent.id, child_node_type=child_type.value, team_group_id=group.id,
                               role_id=rid, created_by_id=actor.id)
        db.add(default)
    default.status = ACTIVE
    db.flush()
    db.refresh(default)
    applied = 0
    for child in children(db, parent):
        if child.node_type == child_type.value:
            _apply_default(db, actor, default, child)
            applied += 1
    record(db, actor, "DEFAULT_GRANT_ADDED", "default_grant", str(default.id), parent.id,
           {"team": group.code, "role": role_code.value, "child_node_type": child_type.value,
            "applied_to_existing": applied})
    db.commit()
    return next(d for d in list_default_grants(db) if d.id == default.id)


def remove_default_grant(db: Session, actor: AppUser, default_id: uuid.UUID) -> None:
    """Stop the default and remove the team grants it made. Commits."""
    default = db.get(DefaultGrant, default_id)
    if default is None or default.status != ACTIVE:
        raise NotFound("No such default grant.")
    default.status = INACTIVE
    for grant in db.scalars(select(NodeTeamGrant).where(NodeTeamGrant.default_grant_id == default.id,
                                                        NodeTeamGrant.status == ACTIVE)):
        grant.status = INACTIVE
    record(db, actor, "DEFAULT_GRANT_REMOVED", "default_grant", str(default.id), default.parent_node_id,
           {"team": default.team.code, "role": default.role.code})
    db.commit()


def _apply_default(db: Session, actor: AppUser | None, default: DefaultGrant, node: HierarchyNode) -> None:
    grant = db.scalar(select(NodeTeamGrant).where(
        NodeTeamGrant.hierarchy_node_id == node.id, NodeTeamGrant.team_group_id == default.team_group_id,
        NodeTeamGrant.role_id == default.role_id))
    if grant is None:
        db.add(NodeTeamGrant(hierarchy_node_id=node.id, team_group_id=default.team_group_id, role_id=default.role_id,
                             default_grant_id=default.id, granted_by_id=actor.id if actor else None))
    else:
        grant.status, grant.default_grant_id = ACTIVE, default.id
    db.flush()


# --------------------------------------------------------------------------- users (platform admins)


@dataclass(frozen=True)
class UserView:
    user: AppUser
    platform_admin: bool


def list_users(db: Session) -> list[UserView]:
    admins = {u.id for u in holders_of(db, root_node(db, SystemCode.PLATFORM).id, RoleCode.ADMIN)}
    return [UserView(u, u.id in admins) for u in db.scalars(select(AppUser).order_by(AppUser.lan_id))]


def upsert_user(db: Session, actor: AppUser, lan_id: str, *, display_name: str | None = None,
                email: str | None = None, title: str | None = None, directory_department: str | None = None,
                platform_admin: bool | None = None) -> tuple[UserView, bool]:
    """Add someone before their first sign-in, or update them; optionally set whether they're a
    platform admin. A new user given only a LAN ID gets placeholder details (the directory fills them
    in at their first sign-in) and joins the auto-join groups, as at a first sign-in. Fields left as
    None stay as they are. Commits. Returns (user, created)."""
    lan_id = lan_id.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", lan_id):
        raise InvalidRequest("A LAN ID is letters, digits, dots, dashes and underscores.")
    user = get_user(db, lan_id)
    created = user is None
    fields = ("display_name", "email", "title", "directory_department")
    if user is None:
        user = AppUser(lan_id=lan_id, display_name=lan_id, email=f"{lan_id}@pending.invalid")
        db.add(user)
    before = {f: getattr(user, f) for f in fields}
    if display_name is not None:
        if not display_name.strip():
            raise InvalidRequest("Enter a display name.")
        user.display_name = display_name.strip()
    if email is not None:
        if not email.strip():
            raise InvalidRequest("Enter an email.")
        user.email = email.strip().lower()
    if title is not None:
        user.title = title.strip()
    if directory_department is not None:
        user.directory_department = directory_department.strip()
    db.flush()
    if created:
        _auto_join(db, user)
        record(db, actor, "USER_ADDED", "user", lan_id, None, {})
    elif before != {f: getattr(user, f) for f in fields}:
        record(db, actor, "USER_UPDATED", "user", lan_id, None, audit.diff(before, {f: getattr(user, f) for f in fields}))
    root = root_node(db, SystemCode.PLATFORM)
    is_admin = any(u.id == user.id for u in holders_of(db, root.id, RoleCode.ADMIN))
    if platform_admin is not None and is_admin != platform_admin:
        roles = set(next((m.roles for m in list_members(db, root.id) if m.user.id == user.id), []))
        roles = (roles | {RoleCode.ADMIN.value}) if platform_admin else (roles - {RoleCode.ADMIN.value})
        set_member_roles(db, actor, root, lan_id, sorted(roles))
    db.commit()
    return next(v for v in list_users(db) if v.user.id == user.id), created


def set_user_active(db: Session, actor: AppUser, lan_id: str, active: bool) -> UserView:
    """Switch someone's access off (they can't sign in; their sessions end) or back on. Commits."""
    user = require_user(db, lan_id)
    if user.id == actor.id and not active:
        raise Conflict("You can't switch off your own access.")
    status = ACTIVE if active else INACTIVE
    if user.status != status:
        user.status = status
        if not active:
            revoke_sessions(db, user.lan_id, reason="access_switched_off")
        record(db, actor, "USER_ACTIVATED" if active else "USER_DEACTIVATED", "user", user.lan_id, None, {})
        _roles_changed(db, user_id=user.id)
    db.commit()
    return next(v for v in list_users(db) if v.user.id == user.id)


# --------------------------------------------------------------------------- audit


def record(db: Session, actor: AppUser | None, action: str, target_type: str, target_id: str,
           node_id: uuid.UUID | None, details: dict[str, Any], source_system: str | None = None) -> None:
    """Add an audit event to the caller's transaction (app.audit)."""
    audit.record(db, action, actor=actor, target=(target_type, target_id), node_id=node_id, details=details,
                 source_system=source_system)

