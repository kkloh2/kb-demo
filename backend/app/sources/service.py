"""Source systems, their hierarchies and their roots' groups (platform admins only).

    create_source       a new source system, e.g. DOC_HUB
    create_hierarchy    its tree: the levels (ROOT, then e.g. DOC_REPO) and the root node, with
                        the root's admins and users groups (app.access.service.create_root)
    set_group_roles     who is in a root's admins or users group, with which roles

The PLATFORM system is seeded at start-up and can't be created here.
"""

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.access import service as access
from app.access.catalog import CHILD_LEVELS, GROUP_ROLES, NodeType, RoleCode, SystemCode
from app.access.models import AppUser, UserGroup, UserGroupMember, UserGroupMemberRole
from app.core.errors import Conflict, InvalidRequest, NotFound
from app.sources.models import Hierarchy, HierarchyNode, SourceSystem

_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,31}$")


def _code(raw: str, what: str) -> str:
    code = re.sub(r"[\s-]+", "_", raw.strip().upper())
    if not _CODE.match(code):
        raise InvalidRequest(f"A {what} is 2 to 32 letters, digits or underscores, starting with a letter "
                             f"(e.g. DOC_HUB).")
    return code


def get_source(db: Session, code: str) -> SourceSystem:
    system = db.scalar(select(SourceSystem).where(SourceSystem.code == code.strip().upper()))
    if system is None:
        raise NotFound(f"No source system {code.strip().upper()!r}.")
    return system


def create_source(db: Session, actor: AppUser, code: str, name: str) -> SourceSystem:
    """Commits."""
    code, name = _code(code, "source system code"), " ".join(name.split())
    if not name:
        raise InvalidRequest("Enter a name.")
    if db.scalar(select(SourceSystem.id).where(SourceSystem.code == code)) is not None:
        raise Conflict(f"There's already a source system {code}.")
    system = SourceSystem(code=code, name=name)
    db.add(system)
    db.flush()
    access.record(db, actor, "SOURCE_SYSTEM_CREATED", "source_system", code, None, {"name": name})
    db.commit()
    return system


def create_hierarchy(db: Session, actor: AppUser, code: str, name: str = "",
                     child_levels: list[str] | None = None) -> HierarchyNode:
    """The system's hierarchy and root node (named `name`, by default the system's code), with
    `child_levels` below the root. Left out, the levels are the ones the code defines for that
    system (DOC_HUB: DOC_REPO), or none. Platform admins join the root's admins group and everyone
    joins its users group. Commits."""
    system = get_source(db, code)
    if system.code == SystemCode.PLATFORM.value:
        raise Conflict("PLATFORM's hierarchy is set up by Data Hub itself.")
    name = " ".join(name.split()) or system.code
    if child_levels is None:
        child_levels = list(CHILD_LEVELS.get(system.code, ()))
    levels = [NodeType.ROOT.value] + [_code(level, "level") for level in child_levels]
    if len(set(levels)) != len(levels):
        raise InvalidRequest("Each level needs its own name.")
    root = access.create_root(db, actor, system, name, levels)
    db.commit()
    return root


def set_group_roles(db: Session, actor: AppUser, code: str, group_type: str, lan_id: str, roles: list[str]) -> None:
    """Make the person's roles in one of the root's groups exactly `roles` ([] removes them from
    that group); their roles in the root's other groups stay. Commits."""
    root = access.root_node(db, code)
    group = access.node_group(db, root.id, group_type.strip().upper())
    allowed = {r.value for r in GROUP_ROLES.get(group.group_type, ())}
    wanted = {r.strip().upper() for r in roles}
    if wanted - allowed:
        raise InvalidRequest(f"The {group.group_type.lower()} group holds {', '.join(sorted(allowed))}.")
    user = access.require_user(db, lan_id)
    elsewhere = access.roles_held_in_groups(db, user.id, root.id) - allowed - {RoleCode.OWNER.value}
    access.set_member_roles(db, actor, root, lan_id, sorted(elsewhere | wanted))


# --------------------------------------------------------------------------- reading


@dataclass(frozen=True)
class GroupView:
    group: UserGroup
    grantable: list[str]
    auto_join_role: str | None
    members: list[access.Member]


@dataclass(frozen=True)
class SourceView:
    system: SourceSystem
    hierarchy: Hierarchy | None
    root: HierarchyNode | None
    groups: list[GroupView]
    child_count: int
    last_updated: datetime  # the latest change to the system, its hierarchy, root, or who is in its root groups


def _last_updated(db: Session, system: SourceSystem, hierarchy: Hierarchy | None, root: HierarchyNode | None) -> datetime:
    times = [system.updated_at] + ([hierarchy.updated_at] if hierarchy else []) + ([root.updated_at] if root else [])
    if root is not None:
        groups = select(UserGroup.id).where(UserGroup.hierarchy_node_id == root.id)
        times += [t for t in (
            db.scalar(select(func.max(UserGroup.updated_at)).where(UserGroup.hierarchy_node_id == root.id)),
            db.scalar(select(func.max(UserGroupMember.updated_at)).where(UserGroupMember.group_id.in_(groups))),
            db.scalar(select(func.max(UserGroupMemberRole.updated_at)).join(UserGroupMember)
                      .where(UserGroupMember.group_id.in_(groups))),
        ) if t is not None]
    return max(times)


def list_sources(db: Session) -> list[SourceView]:
    codes = {rid: code for code, rid in access.role_ids(db).items()}
    out = []
    for system in db.scalars(select(SourceSystem).order_by(SourceSystem.created_at)):
        hierarchy = db.scalar(select(Hierarchy).where(Hierarchy.source_system_id == system.id))
        root = db.scalar(select(HierarchyNode).where(HierarchyNode.hierarchy_id == hierarchy.id,
                                                     HierarchyNode.parent_id.is_(None))) if hierarchy else None
        groups = []
        if root is not None:
            for g in access.node_groups(db, root.id):
                groups.append(GroupView(g, [r.value for r in GROUP_ROLES.get(g.group_type, ())],
                                        codes.get(g.auto_join_role_id) if g.auto_join_role_id else None,
                                        access.list_members(db, root.id, g.group_type)))
        children = len(access.children(db, root)) if root is not None else 0
        out.append(SourceView(system, hierarchy, root, groups, children, _last_updated(db, system, hierarchy, root)))
    return out
