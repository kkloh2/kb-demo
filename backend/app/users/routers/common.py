"""Pieces shared by the users module's routers."""

from typing import Annotated

from fastapi import Path

from app.db.session import Db
from app.users import service
from app.users.models import User
from app.users.schemas import UserOut

DepartmentCode = Annotated[str, Path(min_length=1, max_length=32, description='e.g. "RISK" (case-insensitive)')]
LanId = Annotated[str, Path(min_length=1, max_length=64, description="LAN ID (case-insensitive)")]

FORBIDDEN_403 = {403: {"description": "Caller lacks the required role"}}


def user_out_from(item: service.UserWithRoles) -> UserOut:
    u = item.user
    return UserOut(
        lan_id=u.lan_id,
        display_name=u.display_name,
        email=u.email,
        department=u.department,
        title=u.title,
        system_roles=item.system_roles,
        org_unit_roles=item.org_unit_roles,
    )


def user_out(db: Db, user: User) -> UserOut:
    roles = service.user_roles(db, user)
    return UserOut(
        lan_id=user.lan_id,
        display_name=user.display_name,
        email=user.email,
        department=user.department,
        title=user.title,
        system_roles=roles[service.SYSTEM_ROLES_CLAIM],
        org_unit_roles=roles[service.ORG_UNIT_ROLES_CLAIM],
    )
