from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, Db, client_ip
from app.db.models import User, UserRole
from app.schemas.auth import DepartmentOut, LoginRequest, LoginResponse, UserOut
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(user: User, roles: list[str], perms: list[str]) -> UserOut:
    return UserOut(
        username=user.lan_id,
        display_name=user.display_name,
        title=user.title,
        email=user.email,
        department=DepartmentOut(code=user.department.code, name=user.department.name) if user.department else None,
        roles=roles,
        permissions=perms,
    )


@router.post(
    "/login",
    response_model=LoginResponse,
    responses={401: {"description": "Wrong LAN ID or password"}, 423: {"description": "Account locked"}},
)
def login(body: LoginRequest, request: Request, db: Db) -> LoginResponse:
    """Sign in with LAN ID and password. Returns a JWT carrying department, roles and permissions."""
    result = auth_service.authenticate(
        db, body.username, body.password, ip=client_ip(request), user_agent=request.headers.get("user-agent")
    )
    return LoginResponse(
        access_token=result.token,
        expires_in=result.expires_in,
        user=_user_out(result.user, result.roles, result.permissions),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(p: CurrentUser, request: Request, db: Db) -> Response:
    """End this session on the server. The token stops working immediately."""
    auth_service.logout(db, p, ip=client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
def me(p: CurrentUser, db: Db) -> UserOut:
    """The signed-in user. Roles and permissions are those in the current token."""
    user = db.scalar(
        select(User)
        .where(User.id == p.user_id)
        .options(selectinload(User.department), selectinload(User.role_links).selectinload(UserRole.role))
    )
    return _user_out(user, sorted(r.value for r in p.roles), sorted(x.value for x in p.permissions))
