"""Projects: who can see and manage them, and their members.

Department roles come from the caller's token (org_unit_roles); project roles from the database
(project_members), since they are per resource and checked on every request. Changing someone's
project roles therefore takes effect immediately, without signing them out.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.auth.identity import Principal
from app.core.errors import Conflict, InvalidRequest, NotFound
from app.documents.models import PROJECT_ROLE_ORDER, Project, ProjectMember, ProjectRole
from app.users.models import Department, User
from app.users.service import get_by_lan_id, get_department, org_unit_roles_of

# Department roles that put a department's projects in someone's list.
LISTING_DEPARTMENT_ROLES = frozenset({"VIEWER", "DEPARTMENT_ADMIN"})


@dataclass(frozen=True)
class ProjectAccess:
    """What the caller can do with one project."""

    department_roles: frozenset[str]  # the caller's roles in the project's department (token)
    project_roles: frozenset[str]  # the caller's roles in the project itself (database)

    @property
    def manage(self) -> bool:
        """Edit or delete the project and manage its members."""
        return "DEPARTMENT_ADMIN" in self.department_roles

    @property
    def listed(self) -> bool:
        return bool(self.project_roles) or bool(LISTING_DEPARTMENT_ROLES & self.department_roles)

    @property
    def view_documents(self) -> bool:
        """Any project role, or the department admin (a viewer of every project by default)."""
        return bool(self.project_roles) or self.manage

    @property
    def upload(self) -> bool:
        return ProjectRole.MAKER.value in self.project_roles

    @property
    def review(self) -> bool:
        return ProjectRole.CHECKER.value in self.project_roles


@dataclass(frozen=True)
class ProjectWithAccess:
    project: Project
    access: ProjectAccess


# --------------------------------------------------------------------------- lookups & access


def get_project(db: Session, project_id: int) -> Project:
    project = db.scalar(select(Project).where(Project.id == project_id).options(selectinload(Project.department)))
    if project is None:
        raise NotFound(f"No project {project_id}.")
    return project


def project_roles_of(db: Session, lan_id: str, project_id: int) -> frozenset[str]:
    """The user's roles in the project, from the database."""
    return frozenset(db.scalars(
        select(ProjectMember.role)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id, User.lan_id == lan_id.strip().lower())
    ))


def access_to(db: Session, principal: Principal, project: Project) -> ProjectAccess:
    return ProjectAccess(
        department_roles=org_unit_roles_of(principal).get(project.department.code, frozenset()),
        project_roles=project_roles_of(db, principal.lan_id, project.id),
    )


def list_projects(db: Session, principal: Principal) -> list[ProjectWithAccess]:
    """Projects the caller can see: their departments' (as VIEWER or DEPARTMENT_ADMIN), plus any
    project they hold a role in. Most recently updated first."""
    department_roles = org_unit_roles_of(principal)
    codes = [code for code, roles in department_roles.items() if LISTING_DEPARTMENT_ROLES & roles]
    my_roles: dict[int, set[str]] = {}
    for project_id, role in db.execute(
        select(ProjectMember.project_id, ProjectMember.role)
        .join(User, User.id == ProjectMember.user_id)
        .where(User.lan_id == principal.lan_id)
    ):
        my_roles.setdefault(project_id, set()).add(role)

    projects = db.scalars(
        select(Project)
        .join(Department, Department.id == Project.department_id)
        .where(or_(Department.code.in_(codes), Project.id.in_(my_roles)))
        .options(selectinload(Project.department))
        .order_by(Project.updated_at.desc(), Project.id.desc())
    ).all()
    return [
        ProjectWithAccess(p, ProjectAccess(
            department_roles=department_roles.get(p.department.code, frozenset()),
            project_roles=frozenset(my_roles.get(p.id, ())),
        ))
        for p in projects
    ]


def manageable_departments(db: Session, principal: Principal) -> list[Department]:
    """Departments the caller administers, i.e. can create projects in. Sorted by code."""
    codes = [code for code, roles in org_unit_roles_of(principal).items() if "DEPARTMENT_ADMIN" in roles]
    return list(db.scalars(select(Department).where(Department.code.in_(codes)).order_by(Department.code)))


# --------------------------------------------------------------------------- projects
#
# Called from endpoints guarded by @OrgUnitRoles / @ProjectRoles: they check the caller.


@dataclass(frozen=True)
class ProjectFields:
    name: str
    description: str = ""
    country: str = ""
    business_unit: str = ""
    purpose: str = ""
    valid_till: date | None = None

    def cleaned(self) -> "ProjectFields":
        name = self.name.strip()
        if not name:
            raise InvalidRequest("Enter a project name.")
        return ProjectFields(
            name=name,
            description=self.description.strip(),
            country=self.country.strip(),
            business_unit=self.business_unit.strip(),
            purpose=self.purpose.strip(),
            valid_till=self.valid_till,
        )


def create_project(db: Session, actor_lan_id: str, department_code: str, fields: ProjectFields) -> Project:
    """Create a project in the department. Callers must be its DEPARTMENT_ADMIN."""
    department = get_department(db, department_code)
    if department is None:
        raise NotFound(f"No department {department_code.strip().upper()!r}.")
    f = fields.cleaned()
    _require_unique_name(db, department.id, f.name)
    actor = get_by_lan_id(db, actor_lan_id)
    project = Project(department_id=department.id, created_by_id=actor.id if actor else None, **_columns(f))
    db.add(project)
    db.commit()
    return get_project(db, project.id)


def update_project(db: Session, project_id: int, fields: ProjectFields) -> Project:
    """Replace the project's name, description and base metadata."""
    project = get_project(db, project_id)
    f = fields.cleaned()
    if f.name != project.name:
        _require_unique_name(db, project.department_id, f.name, other_than=project.id)
    for column, value in _columns(f).items():
        setattr(project, column, value)
    db.commit()
    return get_project(db, project.id)


def delete_project(db: Session, project_id: int) -> None:
    """Delete the project with its members, fields and documents (stored files included)."""
    from app.documents.documents import delete_project_files  # local import: avoids a cycle

    db.delete(get_project(db, project_id))
    db.commit()
    delete_project_files(project_id)


def _columns(f: ProjectFields) -> dict:
    return {
        "name": f.name, "description": f.description, "country": f.country,
        "business_unit": f.business_unit, "purpose": f.purpose, "valid_till": f.valid_till,
    }


def _require_unique_name(db: Session, department_id: int, name: str, other_than: int | None = None) -> None:
    query = select(Project.id).where(Project.department_id == department_id, Project.name == name)
    if other_than is not None:
        query = query.where(Project.id != other_than)
    if db.scalar(query) is not None:
        raise Conflict(f"This department already has a project called {name!r}.")


# --------------------------------------------------------------------------- members


@dataclass(frozen=True)
class Member:
    user: User
    roles: list[str]  # in PROJECT_ROLE_ORDER


def list_members(db: Session, project_id: int) -> list[Member]:
    """The project's members with their roles, sorted by name."""
    get_project(db, project_id)
    by_user: dict[int, tuple[User, set[str]]] = {}
    for member in db.scalars(
        select(ProjectMember).where(ProjectMember.project_id == project_id).options(selectinload(ProjectMember.user))
    ):
        by_user.setdefault(member.user_id, (member.user, set()))[1].add(member.role)
    members = [Member(user, _ordered(roles)) for user, roles in by_user.values()]
    return sorted(members, key=lambda m: (m.user.display_name.lower(), m.user.lan_id))


def set_member_roles(db: Session, actor_lan_id: str, project_id: int, lan_id: str, roles: list[str]) -> Member:
    """Make the user's roles in the project exactly `roles` ([] removes them from the project).
    MAKER and CHECKER can't be held together in one project."""
    wanted = _parse_project_roles(roles)
    if {ProjectRole.MAKER.value, ProjectRole.CHECKER.value} <= wanted:
        raise Conflict("One person can't be both maker and checker in a project.")
    get_project(db, project_id)
    user = get_by_lan_id(db, lan_id)
    if user is None:
        raise NotFound(
            f"No user with LAN ID {lan_id.strip().lower()!r}. They get one when they first sign in, "
            f"or a system admin can add them."
        )
    actor = get_by_lan_id(db, actor_lan_id)
    current = {m.role: m for m in db.scalars(
        select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.user_id == user.id)
    )}
    for role in set(current) - wanted:
        db.delete(current[role])
    db.flush()
    for role in wanted - set(current):
        db.add(ProjectMember(project_id=project_id, user_id=user.id, role=role,
                             granted_by_id=actor.id if actor else None))
    db.commit()
    return Member(user, _ordered(wanted))


def _parse_project_roles(names: list[str]) -> set[str]:
    roles = set()
    for name in names:
        code = name.strip().upper()
        if code not in ProjectRole.__members__:
            raise InvalidRequest(f"Project roles are MAKER, CHECKER and VIEWER, not {name!r}.")
        roles.add(code)
    return roles


def _ordered(roles: set[str]) -> list[str]:
    return [r.value for r in PROJECT_ROLE_ORDER if r.value in roles]
