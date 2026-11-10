import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import access_requests, auth, documents, knowledge_bases, people, workflow
from app.core.config import DEV_JWT_SECRET, get_settings
from app.core.security import warm_up
from app.db.session import init_db
from app.services.errors import DomainError

log = logging.getLogger("datahub")
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.jwt_secret == DEV_JWT_SECRET:
        log.warning("Using the development JWT secret. Set DATAHUB_JWT_SECRET outside local development.")
    init_db()
    warm_up()
    yield


app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(DomainError)
async def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    return JSONResponse({"detail": exc.message}, status_code=exc.status_code, headers=headers)


for router in (
    auth.router, people.router, knowledge_bases.router, access_requests.router, documents.router, workflow.router
):
    app.include_router(router, prefix="/api")


@app.get("/api/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
