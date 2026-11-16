import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.access import router as access_router
from app.access.service import add_access_claim, on_roles_changed, record_sign_in
from app.approvals import service as approvals_service
from app.workflows import engine as workflow_engine
from app.workflows import router as workflows_router
from app.approvals import router as approvals_router
from app.audit import context as audit_context
from app.audit import router as audit_router
from app.approvals.hooks import approval_kind
from app.auth import router as auth_router
from app.auth.dependencies import client_ip
from app.auth.hooks import on_sign_in
from app.core.config import DEV_JWT_SECRET, get_settings
from app.core.errors import DomainError
from app.db.session import init_db
from app.documents import documents as doc_hub_documents
from app.documents import routers as documents_routers
from app.sources import router as sources_router

log = logging.getLogger("datahub")
settings = get_settings()

# Wiring between features happens here, so features don't import each other in both directions.
on_sign_in(record_sign_in)  # access: create or refresh the person; join the auto-join groups
on_sign_in(add_access_claim)  # access: put the roles held at each system's root in the token
approval_kind(doc_hub_documents.KIND)  # Doc Hub: documents go through Approvals (DOCUMENT_UPLOAD)
workflow_engine.on_end(approvals_service.SUBJECT, approvals_service.on_flow_end)  # approvals: a request's flow ended
on_roles_changed(approvals_service.on_roles_changed)  # approvals: keep who each waiting task is assigned to current


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.jwt_secret == DEV_JWT_SECRET:
        log.warning("Using the development JWT secret. Set DATAHUB_JWT_SECRET outside local development.")
    init_db()
    yield


app = FastAPI(title=settings.app_name, version="0.4.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _audit_context(request: Request, call_next):
    """Every audit event recorded while handling this request carries its id and client address."""
    rid = audit_context.request_id.set(request.headers.get("x-request-id") or str(uuid.uuid4()))
    ip = audit_context.client_ip.set(client_ip(request))
    try:
        return await call_next(request)
    finally:
        audit_context.request_id.reset(rid)
        audit_context.client_ip.reset(ip)


@app.exception_handler(DomainError)
async def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    return JSONResponse({"detail": exc.message}, status_code=exc.status_code, headers=headers)


app.include_router(auth_router.router, prefix="/api")
app.include_router(access_router.router, prefix="/api")
app.include_router(sources_router.router, prefix="/api")
app.include_router(documents_routers.router, prefix="/api")
app.include_router(approvals_router.router, prefix="/api")
app.include_router(workflows_router.router, prefix="/api")
app.include_router(audit_router.router, prefix="/api")


@app.get("/api/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
