"""Roles in the service layer: the tables, the rules about roles, and the token claims.

Who may call what is the endpoints' job (tests/users/test_authorization.py); these call the
service directly as a system admin or department admin would through an endpoint.
"""

import base64
import json

import pytest
from sqlalchemy.exc import IntegrityError

from app.auth.service import principal_from_token
from app.core.errors import Conflict, InvalidRequest, NotFound
from app.db.session import new_session
from app.users import service
from app.users.models import Role, RoleCode, User, UserOrgUnitRole, UserSystemRole

R = RoleCode
EXTRA_DIRECTORY_USERS = """
  risk.admin:
    password: demo123
    display_name: Rita Lim
    email: rita.lim@datahub.local
    department: Risk Management
    title: Risk Lead
  hr.admin:
    password: demo123
    display_name: Hari Kumar
    email: hari.kumar@datahub.local
    department: Human Resources
    title: HR Lead
"""


@pytest.fixture
def people(client, directory, login):
    """admin (system admin), analyst, risk.admin, hr.admin: all signed in once."""
    directory.write_text(directory.read_text() + EXTRA_DIRECTORY_USERS)
    for lan_id in ("admin", "analyst", "risk.admin", "hr.admin"):
        login(lan_id, "demo123" if "." in lan_id else None)


def _claims(token: str) -> dict:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def _token(client, lan_id: str, password: str) -> str:
    r = client.post("/api/auth/login", json={"username": lan_id, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _create_department(code, name):
    with new_session() as db:
        return service.create_department(db, "admin", code, name)


def _update_department(code, new_code, name):
    with new_session() as db:
        return service.update_department(db, code, new_code, name)


def _upsert_user(lan_id, *, system_roles=("PUBLIC",), admin_of=(), actor="admin", **profile):
    with new_session() as db:
        existing = service.get_by_lan_id(db, lan_id)
        profile.setdefault("display_name", existing.display_name if existing else lan_id.title())
        profile.setdefault("email", existing.email if existing else f"{lan_id}@datahub.local")
        return service.upsert_user(db, actor, lan_id, system_roles=list(system_roles),
                                   department_admin_of=list(admin_of), **profile)


def _set(lan_id, code, roles, actor="risk.admin"):
    with new_session() as db:
        return service.set_department_roles(db, actor, lan_id, code, list(roles))


def _roles(lan_id):
    with new_session() as db:
        user = service.get_by_lan_id(db, lan_id)
        return service.system_roles(db, user), service.org_unit_roles(db, user)


def _make_department_admins():
    _upsert_user("risk.admin", admin_of=["RISK"])
    _upsert_user("hr.admin", admin_of=["HR"])


# --------------------------------------------------------------------------- reference data & tables


def test_roles_table_lists_every_role_with_its_scope(client):
    with new_session() as db:
        scopes = {r.code: r.scope for r in db.query(Role)}
    assert scopes == {
        "SYSTEM_ADMIN": "system", "PUBLIC": "system",
        "DEPARTMENT_ADMIN": "org_unit", "MAKER": "org_unit", "CHECKER": "org_unit", "VIEWER": "org_unit",
    }


def test_tables_refuse_a_role_in_the_wrong_scope(people):
    with new_session() as db:
        analyst = service.get_by_lan_id(db, "analyst")
        db.add(UserSystemRole(user_id=analyst.id, role_code="MAKER"))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
        risk = service.get_department(db, "RISK")
        db.add(UserOrgUnitRole(user_id=analyst.id, department_id=risk.id, role_code="SYSTEM_ADMIN"))
        with pytest.raises(IntegrityError):
            db.flush()


# --------------------------------------------------------------------------- sign-in


def test_new_user_gets_public_and_nothing_else(client):
    claims = _claims(_token(client, "analyst", "datahub123"))
    assert claims["system_roles"] == ["PUBLIC"]
    assert claims["org_unit_roles"] == {}
    assert "roles" not in claims


def test_bootstrap_lan_id_becomes_system_admin(client):
    assert _claims(_token(client, "admin", "admin123"))["system_roles"] == ["PUBLIC", "SYSTEM_ADMIN"]


def test_public_is_given_once_not_restored_at_every_sign_in(client, login):
    login("analyst")
    with new_session() as db:
        db.query(UserSystemRole).filter_by(role_code="PUBLIC").delete()
        db.commit()
    assert _claims(_token(client, "analyst", "datahub123"))["system_roles"] == []


# --------------------------------------------------------------------------- departments


def test_create_department(people):
    dept = _create_department(" ops ", "Operations")
    assert (dept.code, dept.name) == ("OPS", "Operations")
    with pytest.raises(Conflict):
        _create_department("ops", "Again")
    with pytest.raises(InvalidRequest):
        _create_department("", "No code")


def test_update_department_name_and_code(people):
    dept_id = _create_department("OPS", "Operations").id
    dept = _update_department("ops", "OPS", "Operations & Support")
    assert (dept.id, dept.code, dept.name) == (dept_id, "OPS", "Operations & Support")
    dept = _update_department("OPS", "opx", "Operations X")
    assert (dept.id, dept.code, dept.name) == (dept_id, "OPX", "Operations X")
    with new_session() as db:
        assert service.get_department(db, "OPS") is None
    with pytest.raises(Conflict):
        _update_department("OPX", "RISK", "Clash")
    with pytest.raises(NotFound):
        _update_department("NOPE", "NOPE", "x")


def test_code_change_keeps_roles_and_ends_holders_sessions(client, people):
    _make_department_admins()
    _set("analyst", "RISK", ["VIEWER"])
    analyst = {"Authorization": f"Bearer {_token(client, 'analyst', 'datahub123')}"}
    _update_department("RISK", "CRM", "Credit Risk Management")
    assert client.get("/api/auth/me", headers=analyst).status_code == 401
    assert _claims(_token(client, "analyst", "datahub123"))["org_unit_roles"] == {"CRM": ["VIEWER"]}


def test_delete_department_removes_every_role_in_it(people):
    _make_department_admins()
    _set("analyst", "RISK", ["VIEWER"])
    _set("analyst", "HR", ["VIEWER"], actor="hr.admin")
    with new_session() as db:
        service.delete_department(db, "risk")
    assert _roles("analyst")[1] == {"HR": {R.VIEWER}}
    assert _roles("risk.admin")[1] == {}
    with new_session() as db, pytest.raises(NotFound):
        service.delete_department(db, "RISK")


# --------------------------------------------------------------------------- users (system admins)


def test_upsert_user_creates_a_user_before_their_first_sign_in(client, people, directory):
    result = _upsert_user("new.joiner", display_name="New Joiner", admin_of=["HR"])
    assert result.created
    assert _roles("new.joiner") == ({R.PUBLIC}, {"HR": {R.DEPARTMENT_ADMIN}})
    # at first sign-in the directory fills in the details and the roles are already there
    directory.write_text(directory.read_text() + """
  new.joiner:
    password: demo123
    display_name: Nora Joiner
    email: nora.joiner@datahub.local
    department: Human Resources
    title: HR Partner
""")
    claims = _claims(_token(client, "new.joiner", "demo123"))
    assert claims["name"] == "Nora Joiner"
    assert claims["org_unit_roles"] == {"HR": ["DEPARTMENT_ADMIN"]}


def test_created_user_gets_public_even_when_not_listed(client, people, directory):
    result = _upsert_user("new.joiner", system_roles=[])
    assert result.created
    assert _roles("new.joiner")[0] == {R.PUBLIC}
    assert _upsert_user("other.joiner", system_roles=["SYSTEM_ADMIN"]).created
    assert _roles("other.joiner")[0] == {R.PUBLIC, R.SYSTEM_ADMIN}
    # their first sign-in keeps it
    directory.write_text(directory.read_text() + """
  new.joiner:
    password: demo123
    display_name: Nora Joiner
    email: new.joiner@datahub.local
    department: Human Resources
    title: HR Partner
""")
    assert _claims(_token(client, "new.joiner", "demo123"))["system_roles"] == ["PUBLIC"]


def test_public_can_be_removed_on_update(people):
    _upsert_user("new.joiner", system_roles=[])
    assert not _upsert_user("new.joiner", system_roles=[]).created
    assert _roles("new.joiner")[0] == set()


def test_upsert_user_sets_exactly_the_roles_given(people):
    _upsert_user("analyst", system_roles=["PUBLIC", "SYSTEM_ADMIN"], admin_of=["RISK", "HR"])
    assert _roles("analyst") == ({R.PUBLIC, R.SYSTEM_ADMIN}, {"RISK": {R.DEPARTMENT_ADMIN}, "HR": {R.DEPARTMENT_ADMIN}})
    result = _upsert_user("analyst", system_roles=[], admin_of=["hr"])
    assert not result.created
    assert _roles("analyst") == (set(), {"HR": {R.DEPARTMENT_ADMIN}})


def test_upsert_user_leaves_maker_checker_viewer_alone(people):
    _make_department_admins()
    _set("analyst", "RISK", ["CHECKER", "VIEWER"])
    _upsert_user("analyst", admin_of=["HR"])
    assert _roles("analyst")[1] == {"RISK": {R.CHECKER, R.VIEWER}, "HR": {R.DEPARTMENT_ADMIN}}
    _upsert_user("analyst", admin_of=[])
    assert _roles("analyst")[1] == {"RISK": {R.CHECKER, R.VIEWER}}


@pytest.mark.parametrize("roles", [["CHECKER"], ["SUPER"]])
def test_upsert_user_refuses_wrong_system_roles(people, roles):
    with pytest.raises(InvalidRequest):
        _upsert_user("analyst", system_roles=roles)


def test_upsert_user_refuses_unknown_departments_and_changes_nothing(people):
    with pytest.raises(NotFound, match="NOPE"):
        _upsert_user("analyst", system_roles=["PUBLIC", "SYSTEM_ADMIN"], admin_of=["RISK", "NOPE"])
    assert _roles("analyst") == ({R.PUBLIC}, {})


def test_upsert_user_refuses_an_email_used_by_someone_else(people):
    with pytest.raises(Conflict, match="risk.admin"):
        _upsert_user("analyst", email="rita.lim@datahub.local")


def test_system_admin_cannot_remove_their_own_system_admin(people):
    with pytest.raises(Conflict):
        _upsert_user("admin", system_roles=["PUBLIC"])


def test_delete_user(client, people):
    _make_department_admins()
    _set("analyst", "RISK", ["VIEWER"])
    analyst = {"Authorization": f"Bearer {_token(client, 'analyst', 'datahub123')}"}
    with new_session() as db:
        service.delete_user(db, "admin", "analyst")
    with new_session() as db:
        assert service.get_by_lan_id(db, "analyst") is None
        assert db.query(UserOrgUnitRole).join(User, User.id == UserOrgUnitRole.user_id).filter(
            User.lan_id == "analyst").count() == 0
    assert client.get("/api/auth/me", headers=analyst).status_code == 401
    # the directory still lets them in: they come back as a new user with PUBLIC only
    claims = _claims(_token(client, "analyst", "datahub123"))
    assert (claims["system_roles"], claims["org_unit_roles"]) == (["PUBLIC"], {})
    with new_session() as db, pytest.raises(NotFound):
        service.delete_user(db, "admin", "nobody")
    with new_session() as db, pytest.raises(Conflict):
        service.delete_user(db, "admin", "admin")


# --------------------------------------------------------------------------- department roles (department admins)


@pytest.mark.parametrize("roles", [["MAKER"], ["CHECKER"], ["VIEWER"], ["CHECKER", "VIEWER"]])
def test_set_department_roles(people, roles):
    _make_department_admins()
    _set("analyst", "RISK", roles)
    assert _roles("analyst")[1] == {"RISK": {R(r) for r in roles}}


def test_set_department_roles_replaces_and_clears(people):
    _make_department_admins()
    _set("analyst", "RISK", ["MAKER", "VIEWER"])
    _set("analyst", "RISK", ["CHECKER"])  # MAKER -> CHECKER swap in one call
    assert _roles("analyst")[1] == {"RISK": {R.CHECKER}}
    _set("analyst", "RISK", [])
    assert _roles("analyst")[1] == {}


def test_set_department_roles_leaves_department_admin_alone(people):
    _make_department_admins()
    _set("risk.admin", "RISK", ["VIEWER"])
    _set("risk.admin", "RISK", [])
    assert _roles("risk.admin")[1] == {"RISK": {R.DEPARTMENT_ADMIN}}


def test_maker_and_checker_are_exclusive_in_a_department(people):
    _make_department_admins()
    with pytest.raises(Conflict, match="maker and checker"):
        _set("analyst", "RISK", ["MAKER", "CHECKER"])


def test_maker_in_one_department_can_be_checker_in_another(people):
    _make_department_admins()
    _set("analyst", "RISK", ["MAKER"])
    _set("analyst", "HR", ["CHECKER"], actor="hr.admin")
    assert _roles("analyst")[1] == {"RISK": {R.MAKER}, "HR": {R.CHECKER}}


def test_viewer_is_never_implied(people):
    _make_department_admins()
    _set("analyst", "RISK", ["CHECKER"])
    assert _roles("analyst")[1] == {"RISK": {R.CHECKER}}


@pytest.mark.parametrize("roles", [["DEPARTMENT_ADMIN"], ["SYSTEM_ADMIN"], ["OWNER"]])
def test_set_department_roles_refuses_other_roles(people, roles):
    _make_department_admins()
    with pytest.raises(InvalidRequest):
        _set("analyst", "RISK", roles)


def test_set_department_roles_unknown_user_or_department(people):
    _make_department_admins()
    with pytest.raises(NotFound):
        _set("nobody", "RISK", ["VIEWER"])
    with pytest.raises(NotFound):
        _set("analyst", "NOPE", ["VIEWER"])


# --------------------------------------------------------------------------- token claims & sessions


def test_token_carries_both_role_claims(client, people):
    _make_department_admins()
    _set("analyst", "RISK", ["CHECKER", "VIEWER"])
    _set("analyst", "HR", ["VIEWER"], actor="hr.admin")
    claims = _claims(_token(client, "analyst", "datahub123"))
    assert claims["system_roles"] == ["PUBLIC"]
    assert claims["org_unit_roles"] == {"HR": ["VIEWER"], "RISK": ["CHECKER", "VIEWER"]}


def test_roles_are_read_back_from_the_token(client, people):
    _make_department_admins()
    _set("analyst", "RISK", ["CHECKER"])
    token = _token(client, "analyst", "datahub123")
    with new_session() as db:
        p = principal_from_token(db, token)
    assert service.system_roles_of(p) == {"PUBLIC"}
    assert service.org_unit_roles_of(p) == {"RISK": {"CHECKER"}}
    assert service.has_org_unit_role(p, "risk", R.CHECKER)
    assert not service.has_org_unit_role(p, "RISK", R.MAKER)
    assert not service.has_system_role(p, R.SYSTEM_ADMIN)


def test_changing_roles_ends_the_persons_sessions(client, people):
    _make_department_admins()
    old = {"Authorization": f"Bearer {_token(client, 'analyst', 'datahub123')}"}
    _set("analyst", "RISK", ["VIEWER"])
    assert client.get("/api/auth/me", headers=old).status_code == 401
    assert _claims(_token(client, "analyst", "datahub123"))["org_unit_roles"] == {"RISK": ["VIEWER"]}


def test_changing_system_roles_ends_the_persons_sessions(client, people):
    old = {"Authorization": f"Bearer {_token(client, 'analyst', 'datahub123')}"}
    _upsert_user("analyst", system_roles=["PUBLIC", "SYSTEM_ADMIN"])
    assert client.get("/api/auth/me", headers=old).status_code == 401


def test_unchanged_roles_leave_sessions_alone(client, people):
    _make_department_admins()
    _set("analyst", "RISK", ["VIEWER"])
    current = {"Authorization": f"Bearer {_token(client, 'analyst', 'datahub123')}"}
    _set("analyst", "RISK", ["VIEWER"])
    _upsert_user("analyst", display_name="Alex T")  # profile only
    assert client.get("/api/auth/me", headers=current).status_code == 200


def test_changing_roles_leaves_other_peoples_sessions_alone(client, people):
    _make_department_admins()
    admin = {"Authorization": f"Bearer {_token(client, 'admin', 'admin123')}"}
    _set("analyst", "RISK", ["VIEWER"])
    assert client.get("/api/auth/me", headers=admin).status_code == 200
