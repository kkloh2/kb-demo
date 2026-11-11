"""The users module's HTTP endpoints, one router per resource, combined into `router` for app.main.

    departments.py   /api/departments, and a user's roles in a department
    users.py         /api/users
    roles.py         /api/roles (read-only)
    common.py        shared path parameters and response helpers
"""

from fastapi import APIRouter

from app.users.routers import departments, roles, users

router = APIRouter()
router.include_router(departments.router)
router.include_router(users.router)
router.include_router(roles.router)

__all__ = ["router"]
