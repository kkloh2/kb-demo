"""FastAPI dependencies for signed-in requests. Other modules require sign-in with `p: CurrentUser`."""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.errors import Unauthenticated
from app.auth.service import Principal, principal_from_token
from app.db.session import Db

_bearer = HTTPBearer(auto_error=False, description="Access token from POST /api/auth/login")


def current_principal(
    db: Db, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> Principal:
    if creds is None:
        raise Unauthenticated("Not signed in.")
    return principal_from_token(db, creds.credentials)


CurrentUser = Annotated[Principal, Depends(current_principal)]


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
