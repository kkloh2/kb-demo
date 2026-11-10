import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth import router as auth_router
from app.auth.security import warm_up
from app.core.config import DEV_JWT_SECRET, get_settings
from app.core.errors import DomainError
from app.db.session import init_db

log = logging.getLogger("datahub")
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.jwt_secret == DEV_JWT_SECRET:
        log.warning("Using the development JWT secret. Set DATAHUB_JWT_SECRET outside local development.")
    init_db()
    warm_up()
    yield


app = FastAPI(title=settings.app_name, version="0.3.0", lifespan=lifespan)
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


app.include_router(auth_router.router, prefix="/api")


@app.get("/api/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
