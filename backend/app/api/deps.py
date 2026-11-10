from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.permissions import Perm
from app.db.session import get_db
from app.services.auth import Principal, principal_from_token
from app.services.errors import Forbidden, Unauthenticated

_bearer = HTTPBearer(auto_error=False, description="Access token from POST /api/auth/login")

Db = Annotated[Session, Depends(get_db)]


def current_principal(
    db: Db, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> Principal:
    if creds is None:
        raise Unauthenticated("Not signed in.")
    return principal_from_token(db, creds.credentials)


CurrentUser = Annotated[Principal, Depends(current_principal)]


def require(perm: Perm):
    """Dependency factory: 403 unless the token carries the permission."""

    def _check(p: CurrentUser) -> Principal:
        if not p.has(perm):
            raise Forbidden("You don't have permission to do this.")
        return p

    return Depends(_check)


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
