"""The documents module's HTTP endpoints, combined into `router` for app.main.

    projects.py   /api/projects, /api/departments/{code}/projects
    documents.py  /api/projects/{id}/fields, /api/projects/{id}/documents...
"""

from fastapi import APIRouter

from app.documents.routers import documents, projects

router = APIRouter()
router.include_router(projects.router)
router.include_router(documents.router)

__all__ = ["router"]
