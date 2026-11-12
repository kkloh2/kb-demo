"""The documents module's HTTP endpoints, combined into `router` for app.main.

    doc_repos.py   /api/doc-repos, /api/departments/{code}/doc-repos
    documents.py  /api/doc-repos/{id}/fields, /api/doc-repos/{id}/documents...
"""

from fastapi import APIRouter

from app.documents.routers import documents, doc_repos

router = APIRouter()
router.include_router(doc_repos.router)
router.include_router(documents.router)

__all__ = ["router"]
