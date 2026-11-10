"""Departments, users and role assignment."""

from fastapi import APIRouter, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, Db
from app.core.permissions import Perm, RoleCode
from app.db.models import Department, KnowledgeBase, Permission, Role, User, UserRole
from app.schemas.auth import DepartmentOut
from app.schemas.people import (
    DepartmentCreate,
    DepartmentWithCounts,
    PermissionOut,
    RoleOut,
    UserCreate,
    UserSummary,
)
from app.services import authz, people, roles
from app.services.errors import Forbidden, NotFound

router = APIRouter(tags=["people"])


def user_summary(u: User) -> UserSummary:
    return UserSummary(
        username=u.lan_id,
        display_name=u.display_name,
        title=u.title,
        email=u.email,
        department=DepartmentOut(code=u.department.code, name=u.department.name) if u.department else None,
        roles=sorted(link.role.code for link in u.role_links),
        is_active=u.is_active,
    )


@router.get("/departments", response_model=list[DepartmentWithCounts])
def list_departments(p: CurrentUser, db: Db) -> list[DepartmentWithCounts]:
    """System admins: all departments. Department admins: their own."""
    if not p.has(Perm.USERS_VIEW):
        raise Forbidden("You don't have permission to do this.")
    q = select(Department).order_by(Department.name)
    if not p.has_role(RoleCode.SYSTEM_ADMIN):
        q = q.where(Department.id == p.department_id)
    out = []
    for d in db.scalars(q):
        members = db.scalar(select(func.count(User.id)).where(User.department_id == d.id)) or 0
        kbs = db.scalar(select(func.count(KnowledgeBase.id)).where(KnowledgeBase.department_id == d.id)) or 0
        admins = db.scalars(
            select(User.lan_id)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(User.department_id == d.id, Role.code == RoleCode.DEPARTMENT_ADMIN.value)
            .order_by(User.lan_id)
        ).all()
        out.append(
            DepartmentWithCounts(code=d.code, name=d.name, members=members, knowledge_bases=kbs, admins=list(admins))
        )
    return out


@router.post("/departments", response_model=DepartmentWithCounts, status_code=status.HTTP_201_CREATED)
def create_department(body: DepartmentCreate, p: CurrentUser, db: Db) -> DepartmentWithCounts:
    """System admins only."""
    d = people.create_department(db, p, body.code, body.name)
    return DepartmentWithCounts(code=d.code, name=d.name, members=0, knowledge_bases=0, admins=[])


@router.get("/users", response_model=list[UserSummary])
def list_users(p: CurrentUser, db: Db, department: str | None = None) -> list[UserSummary]:
    """System admins: everyone (optionally one department). Department admins: their department."""
    if not p.has(Perm.USERS_VIEW):
        raise Forbidden("You don't have permission to do this.")
    q = (
        select(User)
        .options(selectinload(User.department), selectinload(User.role_links).selectinload(UserRole.role))
        .order_by(User.display_name)
    )
    if department:
        dept = db.scalar(select(Department).where(Department.code == department.upper()))
        if dept is None:
            raise NotFound(f"Department '{department}' not found.")
        if not authz.can_view_users(p, dept.id):
            raise Forbidden("You can only see users in your own department.")
        q = q.where(User.department_id == dept.id)
    elif not p.has_role(RoleCode.SYSTEM_ADMIN):
        q = q.where(User.department_id == p.department_id)
    return [user_summary(u) for u in db.scalars(q)]


@router.post("/users", response_model=UserSummary, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, p: CurrentUser, db: Db) -> UserSummary:
    """System admins add department admins to any department. Department admins add viewers,
    makers or checkers to their own department."""
    return user_summary(people.create_user(
        db, p,
        lan_id=body.lan_id, display_name=body.display_name, email=body.email, title=body.title,
        password=body.password, department_code=body.department_code, role=body.role,
    ))


@router.get("/roles", response_model=list[RoleOut])
def list_roles(p: CurrentUser, db: Db) -> list[RoleOut]:
    """System admins only."""
    if not p.has(Perm.ROLES_VIEW):
        raise Forbidden("You don't have permission to do this.")
    order = [r.value for r in RoleCode]
    rows = sorted(db.scalars(select(Role).options(selectinload(Role.permissions))), key=lambda r: order.index(r.code))
    return [
        RoleOut(code=r.code, name=r.name, description=r.description, scope=r.scope, assignable=r.assignable,
                permissions=sorted(x.code for x in r.permissions))
        for r in rows
    ]


@router.get("/permissions", response_model=list[PermissionOut])
def list_permissions(p: CurrentUser, db: Db) -> list[PermissionOut]:
    """System admins only."""
    if not p.has(Perm.ROLES_VIEW):
        raise Forbidden("You don't have permission to do this.")
    perm_roles: dict[str, list[str]] = {}
    for r in db.scalars(select(Role).options(selectinload(Role.permissions))):
        for x in r.permissions:
            perm_roles.setdefault(x.code, []).append(r.code)
    order = [r.value for r in RoleCode]
    return [
        PermissionOut(code=x.code, description=x.description,
                      roles=sorted(perm_roles.get(x.code, []), key=order.index))
        for x in db.scalars(select(Permission).order_by(Permission.code))
    ]


@router.put("/users/{lan_id}/roles/{role}", response_model=UserSummary)
def assign_role(lan_id: str, role: str, p: CurrentUser, db: Db) -> UserSummary:
    """Assign department_admin (system admins) or maker / checker (department admins).

    The user's active sessions end, so their next token carries the new role.
    """
    return user_summary(roles.assign_role(db, p, lan_id, role))


@router.delete("/users/{lan_id}/roles/{role}", response_model=UserSummary)
def revoke_role(lan_id: str, role: str, p: CurrentUser, db: Db) -> UserSummary:
    return user_summary(roles.revoke_role(db, p, lan_id, role))
