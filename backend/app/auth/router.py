from fastapi import APIRouter, Request, Response, status

from app.auth import service as auth_service
from app.auth.dependencies import CurrentUser, client_ip
from app.auth.identity import Identity
from app.auth.schemas import LoginRequest, LoginResponse, UserOut
from app.db.session import Db

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(who: Identity) -> UserOut:
    return UserOut(
        username=who.lan_id,
        display_name=who.display_name,
        email=who.email,
        department=who.department,
        title=who.title,
    )


@router.post(
    "/login",
    response_model=LoginResponse,
    responses={
        401: {"description": "Wrong LAN ID or password (or the directory refused the account)"},
        503: {"description": "Directory unavailable"},
    },
)
def login(body: LoginRequest, request: Request, db: Db) -> LoginResponse:
    """Sign in with LAN ID and password. Returns a JWT for the Authorization header."""
    result = auth_service.authenticate(
        db, body.username, body.password, ip=client_ip(request), user_agent=request.headers.get("user-agent")
    )
    return LoginResponse(access_token=result.token, expires_in=result.expires_in, user=_user_out(result.identity))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(p: CurrentUser, db: Db) -> Response:
    """End this session on the server. The token stops working immediately."""
    auth_service.logout(db, p)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
def me(p: CurrentUser) -> UserOut:
    """The signed-in user, as the directory described them at sign-in (read from the token)."""
    return _user_out(p)
