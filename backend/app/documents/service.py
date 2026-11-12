"""Doc-repos: who can see and manage them, and their members.

Department roles come from the caller's token (org_unit_roles); doc-repo roles from the database
(doc_repo_members), since they are per resource and checked on every request. Changing someone's
doc-repo roles therefore takes effect immediately, without signing them out.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth.identity import Principal
from app.core.errors import Conflict, InvalidRequest, NotFound
from app.documents.models import DEPARTMENT_METADATA_KEYS, DOC_REPO_ROLE_ORDER, DocRepo, DocRepoMember, DocRepoRole
from app.users.models import Department, User
from app.users.service import get_by_lan_id, get_department, org_unit_roles_of

# Department roles that open a department's doc-repos (their page; documents need more).
DETAIL_DEPARTMENT_ROLES = frozenset({"VIEWER", "DEPARTMENT_ADMIN"})


@dataclass(frozen=True)
class DocRepoAccess:
    """What the caller can do with one doc-repo."""

    department_roles: frozenset[str]  # the caller's roles in the doc-repo's department (token)
    doc_repo_roles: frozenset[str]  # the caller's roles in the doc-repo itself (database)

    @property
    def manage(self) -> bool:
        """Edit or delete the doc-repo and manage its members."""
        return "DEPARTMENT_ADMIN" in self.department_roles

    @property
    def view_details(self) -> bool:
        """Open the doc-repo's page: any doc-repo role, or VIEWER / DEPARTMENT_ADMIN of its department.
        (Everyone with the PUBLIC system role sees it in the list.)"""
        return bool(self.doc_repo_roles) or bool(DETAIL_DEPARTMENT_ROLES & self.department_roles)

    @property
    def view_documents(self) -> bool:
        """Any doc-repo role, or the department admin (a viewer of every doc-repo by default)."""
        return bool(self.doc_repo_roles) or self.manage

    @property
    def upload(self) -> bool:
        return DocRepoRole.MAKER.value in self.doc_repo_roles

    @property
    def review(self) -> bool:
        return DocRepoRole.CHECKER.value in self.doc_repo_roles


@dataclass(frozen=True)
class DocRepoWithAccess:
    doc_repo: DocRepo
    access: DocRepoAccess


# --------------------------------------------------------------------------- lookups & access


def get_doc_repo(db: Session, doc_repo_id: int) -> DocRepo:
    doc_repo = db.scalar(select(DocRepo).where(DocRepo.id == doc_repo_id).options(selectinload(DocRepo.department)))
    if doc_repo is None:
        raise NotFound(f"No document repository {doc_repo_id}.")
    return doc_repo


def doc_repo_roles_of(db: Session, lan_id: str, doc_repo_id: int) -> frozenset[str]:
    """The user's roles in the doc-repo, from the database."""
    return frozenset(db.scalars(
        select(DocRepoMember.role)
        .join(User, User.id == DocRepoMember.user_id)
        .where(DocRepoMember.doc_repo_id == doc_repo_id, User.lan_id == lan_id.strip().lower())
    ))


def access_to(db: Session, principal: Principal, doc_repo: DocRepo) -> DocRepoAccess:
    return DocRepoAccess(
        department_roles=org_unit_roles_of(principal).get(doc_repo.department.code, frozenset()),
        doc_repo_roles=doc_repo_roles_of(db, principal.lan_id, doc_repo.id),
    )


def list_doc_repos(db: Session, principal: Principal) -> list[DocRepoWithAccess]:
    """Every doc-repo, most recently updated first, with what the caller can do with each. The
    endpoint lets in callers with the PUBLIC system role; opening one needs more (see view_details)."""
    department_roles = org_unit_roles_of(principal)
    my_roles: dict[int, set[str]] = {}
    for doc_repo_id, role in db.execute(
        select(DocRepoMember.doc_repo_id, DocRepoMember.role)
        .join(User, User.id == DocRepoMember.user_id)
        .where(User.lan_id == principal.lan_id)
    ):
        my_roles.setdefault(doc_repo_id, set()).add(role)

    doc_repos = db.scalars(
        select(DocRepo)
        .options(selectinload(DocRepo.department))
        .order_by(DocRepo.updated_at.desc(), DocRepo.id.desc())
    ).all()
    return [
        DocRepoWithAccess(p, DocRepoAccess(
            department_roles=department_roles.get(p.department.code, frozenset()),
            doc_repo_roles=frozenset(my_roles.get(p.id, ())),
        ))
        for p in doc_repos
    ]


def manageable_departments(db: Session, principal: Principal) -> list[Department]:
    """Departments the caller administers, i.e. can create doc-repos in. Sorted by code."""
    codes = [code for code, roles in org_unit_roles_of(principal).items() if "DEPARTMENT_ADMIN" in roles]
    return list(db.scalars(select(Department).where(Department.code.in_(codes)).order_by(Department.code)))


# --------------------------------------------------------------------------- doc-repos
#
# Called from endpoints guarded by @OrgUnitRoles / @DocRepoRoles: they check the caller.


@dataclass(frozen=True)
class DocRepoFields:
    name: str
    description: str = ""
    department_metadata: dict[str, str] | None = None  # DEPARTMENT_METADATA_KEYS

    def cleaned(self) -> "DocRepoFields":
        name = self.name.strip()
        if not name:
            raise InvalidRequest("Enter a repository name.")
        return DocRepoFields(
            name=name,
            description=self.description.strip(),
            department_metadata=clean_department_metadata(self.department_metadata or {}),
        )


def create_doc_repo(db: Session, actor_lan_id: str, department_code: str, fields: DocRepoFields) -> DocRepo:
    """Create a doc-repo in the department. Callers must be its DEPARTMENT_ADMIN."""
    department = get_department(db, department_code)
    if department is None:
        raise NotFound(f"No department {department_code.strip().upper()!r}.")
    f = fields.cleaned()
    _require_unique_name(db, department.id, f.name)
    if not f.department_metadata["department"]:
        f.department_metadata["department"] = department.name
    actor = get_by_lan_id(db, actor_lan_id)
    doc_repo = DocRepo(department_id=department.id, created_by_id=actor.id if actor else None, **_columns(f))
    db.add(doc_repo)
    db.commit()
    return get_doc_repo(db, doc_repo.id)


def update_doc_repo(db: Session, doc_repo_id: int, fields: DocRepoFields) -> DocRepo:
    """Replace the doc-repo's name, description and department metadata."""
    doc_repo = get_doc_repo(db, doc_repo_id)
    f = fields.cleaned()
    if f.name != doc_repo.name:
        _require_unique_name(db, doc_repo.department_id, f.name, other_than=doc_repo.id)
    for column, value in _columns(f).items():
        setattr(doc_repo, column, value)
    db.commit()
    return get_doc_repo(db, doc_repo.id)


def delete_doc_repo(db: Session, doc_repo_id: int) -> None:
    """Delete the doc-repo with its members, fields and documents (stored files included)."""
    from app.documents.documents import delete_doc_repo_files  # local import: avoids a cycle

    db.delete(get_doc_repo(db, doc_repo_id))
    db.commit()
    delete_doc_repo_files(doc_repo_id)


def _columns(f: DocRepoFields) -> dict:
    return {
        "name": f.name, "description": f.description, "department_metadata": f.department_metadata,
    }


def clean_department_metadata(values: dict[str, str | None]) -> dict[str, str]:
    """Every key of DEPARTMENT_METADATA_KEYS, trimmed ("" when missing); other keys are refused."""
    unknown = set(values) - set(DEPARTMENT_METADATA_KEYS)
    if unknown:
        raise InvalidRequest(f"Department metadata is {', '.join(DEPARTMENT_METADATA_KEYS)}, "
                             f"not {', '.join(sorted(unknown))}.")
    return {k: (values.get(k) or "").strip() for k in DEPARTMENT_METADATA_KEYS}


def _require_unique_name(db: Session, department_id: int, name: str, other_than: int | None = None) -> None:
    query = select(DocRepo.id).where(DocRepo.department_id == department_id, DocRepo.name == name)
    if other_than is not None:
        query = query.where(DocRepo.id != other_than)
    if db.scalar(query) is not None:
        raise Conflict(f"This department already has a document repository called {name!r}.")


# --------------------------------------------------------------------------- members


@dataclass(frozen=True)
class Member:
    user: User
    roles: list[str]  # in DOC_REPO_ROLE_ORDER


def list_members(db: Session, doc_repo_id: int) -> list[Member]:
    """The doc-repo's members with their roles, sorted by name."""
    get_doc_repo(db, doc_repo_id)
    by_user: dict[int, tuple[User, set[str]]] = {}
    for member in db.scalars(
        select(DocRepoMember).where(DocRepoMember.doc_repo_id == doc_repo_id).options(selectinload(DocRepoMember.user))
    ):
        by_user.setdefault(member.user_id, (member.user, set()))[1].add(member.role)
    members = [Member(user, _ordered(roles)) for user, roles in by_user.values()]
    return sorted(members, key=lambda m: (m.user.display_name.lower(), m.user.lan_id))


def set_member_roles(db: Session, actor_lan_id: str, doc_repo_id: int, lan_id: str, roles: list[str]) -> Member:
    """Make the user's roles in the doc-repo exactly `roles` ([] removes them from the doc-repo).
    MAKER and CHECKER can't be held together in one doc-repo."""
    wanted = _parse_doc_repo_roles(roles)
    if {DocRepoRole.MAKER.value, DocRepoRole.CHECKER.value} <= wanted:
        raise Conflict("One person can't be both maker and checker in a document repository.")
    get_doc_repo(db, doc_repo_id)
    user = get_by_lan_id(db, lan_id)
    if user is None:
        raise NotFound(
            f"No user with LAN ID {lan_id.strip().lower()!r}. They get one when they first sign in, "
            f"or a system admin can add them."
        )
    actor = get_by_lan_id(db, actor_lan_id)
    current = {m.role: m for m in db.scalars(
        select(DocRepoMember).where(DocRepoMember.doc_repo_id == doc_repo_id, DocRepoMember.user_id == user.id)
    )}
    for role in set(current) - wanted:
        db.delete(current[role])
    db.flush()
    for role in wanted - set(current):
        db.add(DocRepoMember(doc_repo_id=doc_repo_id, user_id=user.id, role=role,
                             granted_by_id=actor.id if actor else None))
    db.commit()
    return Member(user, _ordered(wanted))


def _parse_doc_repo_roles(names: list[str]) -> set[str]:
    roles = set()
    for name in names:
        code = name.strip().upper()
        if code not in DocRepoRole.__members__:
            raise InvalidRequest(f"Repository roles are MAKER, CHECKER and VIEWER, not {name!r}.")
        roles.add(code)
    return roles


def _ordered(roles: set[str]) -> list[str]:
    return [r.value for r in DOC_REPO_ROLE_ORDER if r.value in roles]
