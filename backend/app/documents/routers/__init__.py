"""Doc Hub endpoints, combined into `router` for app.main."""

from fastapi import APIRouter

from app.documents.routers import doc_repos, documents

router = APIRouter()
router.include_router(doc_repos.router)
router.include_router(documents.router)

__all__ = ["router"]
