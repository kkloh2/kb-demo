"""Roles: the tables, who may grant what, and the system_roles / org_unit_roles token claims."""

import base64
import json

import pytest
from sqlalchemy.exc import IntegrityError

from app.auth.service import principal_from_token
from app.core.errors import Conflict, Forbidden, InvalidRequest, NotFound
from app.db.session import new_session
from app.users import service
from app.users.models import Role, RoleCode, UserOrgUnitRole, UserSystemRole

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


def _grant(actor, lan_id, dept, role):
    with new_session() as db:
        return service.grant_org_unit_role(db, actor, lan_id, dept, role)


def _revoke(actor, lan_id, dept, role):
    with new_session() as db:
        return service.revoke_org_unit_role(db, actor, lan_id, dept, role)


def _make_department_admins():
    _grant("admin", "risk.admin", "RISK", R.DEPARTMENT_ADMIN)
    _grant("admin", "hr.admin", "HR", R.DEPARTMENT_ADMIN)


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


# --------------------------------------------------------------------------- who may grant what


def test_system_admin_creates_departments(people):
    with new_session() as db:
        dept = service.create_department(db, "admin", " ops ", "Operations")
    assert dept.code == "OPS"
    with new_session() as db, pytest.raises(Conflict):
        service.create_department(db, "admin", "OPS", "Operations again")
    with new_session() as db, pytest.raises(InvalidRequest):
        service.create_department(db, "admin", "", "No code")


def test_others_cannot_create_departments(people):
    _make_department_admins()
    with new_session() as db, pytest.raises(Forbidden):
        service.create_department(db, "risk.admin", "OPS", "Operations")


def test_system_admin_grants_department_admin(people):
    _make_department_admins()
    with new_session() as db:
        risk_admin = service.get_by_lan_id(db, "risk.admin")
        assert service.org_unit_roles(db, risk_admin) == {"RISK": {R.DEPARTMENT_ADMIN}}


def test_department_admin_cannot_create_department_admins(people):
    _make_department_admins()
    with pytest.raises(Forbidden):
        _grant("risk.admin", "analyst", "RISK", R.DEPARTMENT_ADMIN)


@pytest.mark.parametrize("role", [R.MAKER, R.CHECKER, R.VIEWER])
def test_department_admin_grants_maker_checker_viewer_in_own_department(people, role):
    _make_department_admins()
    _grant("risk.admin", "analyst", "RISK", role)
    with new_session() as db:
        assert service.org_unit_roles(db, service.get_by_lan_id(db, "analyst")) == {"RISK": {role}}


def test_department_admin_cannot_grant_in_another_department(people):
    _make_department_admins()
    with pytest.raises(Forbidden):
        _grant("risk.admin", "analyst", "HR", R.VIEWER)


def test_system_admin_does_not_grant_maker_checker_viewer(people):
    with pytest.raises(Forbidden):
        _grant("admin", "analyst", "RISK", R.MAKER)


def test_department_admin_can_grant_to_people_from_any_directory_department(people):
    _make_department_admins()
    _grant("hr.admin", "analyst", "HR", R.VIEWER)  # analyst's directory department is Risk Management


def test_system_roles_cannot_be_granted_as_org_unit_roles(people):
    with pytest.raises(InvalidRequest):
        _grant("admin", "analyst", "RISK", R.SYSTEM_ADMIN)


def test_roles_go_only_to_people_who_have_signed_in(people):
    _make_department_admins()
    with pytest.raises(NotFound, match="sign in"):
        _grant("risk.admin", "never.signed.in", "RISK", R.VIEWER)


def test_unknown_department(people):
    with pytest.raises(NotFound):
        _grant("admin", "risk.admin", "NOPE", R.DEPARTMENT_ADMIN)


def test_maker_and_checker_are_exclusive_in_a_department(people):
    _make_department_admins()
    _grant("risk.admin", "analyst", "RISK", R.MAKER)
    with pytest.raises(Conflict, match="maker and checker"):
        _grant("risk.admin", "analyst", "RISK", R.CHECKER)


def test_maker_in_one_department_can_be_checker_in_another(people):
    _make_department_admins()
    _grant("risk.admin", "analyst", "RISK", R.MAKER)
    _grant("hr.admin", "analyst", "HR", R.CHECKER)


def test_viewer_is_never_implied(people):
    _make_department_admins()
    _grant("risk.admin", "analyst", "RISK", R.CHECKER)
    with new_session() as db:
        assert service.org_unit_roles(db, service.get_by_lan_id(db, "analyst")) == {"RISK": {R.CHECKER}}


def test_granting_twice_is_harmless(people):
    _make_department_admins()
    _grant("risk.admin", "analyst", "RISK", R.VIEWER)
    _grant("risk.admin", "analyst", "RISK", R.VIEWER)


def test_revoke(people):
    _make_department_admins()
    _grant("risk.admin", "analyst", "RISK", R.VIEWER)
    assert _revoke("risk.admin", "analyst", "RISK", R.VIEWER) is True
    assert _revoke("risk.admin", "analyst", "RISK", R.VIEWER) is False
    with pytest.raises(Forbidden):
        _revoke("hr.admin", "analyst", "RISK", R.VIEWER)


def test_grantor_rights_come_from_the_database_not_their_token(people):
    _make_department_admins()
    _revoke("admin", "risk.admin", "RISK", R.DEPARTMENT_ADMIN)
    with pytest.raises(Forbidden):
        _grant("risk.admin", "analyst", "RISK", R.VIEWER)


# --------------------------------------------------------------------------- token claims


def test_token_carries_both_role_claims(client, people):
    _make_department_admins()
    _grant("risk.admin", "analyst", "RISK", R.CHECKER)
    _grant("risk.admin", "analyst", "RISK", R.VIEWER)
    _grant("hr.admin", "analyst", "HR", R.VIEWER)
    claims = _claims(_token(client, "analyst", "datahub123"))
    assert claims["system_roles"] == ["PUBLIC"]
    assert claims["org_unit_roles"] == {"HR": ["VIEWER"], "RISK": ["CHECKER", "VIEWER"]}


def test_roles_are_read_back_from_the_token(client, people):
    _make_department_admins()
    _grant("risk.admin", "analyst", "RISK", R.CHECKER)
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
    _grant("risk.admin", "analyst", "RISK", R.VIEWER)
    r = client.get("/api/auth/me", headers=old)
    assert r.status_code == 401
    # signing in again gives a token with the new role
    assert _claims(_token(client, "analyst", "datahub123"))["org_unit_roles"] == {"RISK": ["VIEWER"]}


def test_changing_roles_leaves_other_peoples_sessions_alone(client, people):
    _make_department_admins()
    admin = {"Authorization": f"Bearer {_token(client, 'admin', 'admin123')}"}
    _grant("risk.admin", "analyst", "RISK", R.VIEWER)
    assert client.get("/api/auth/me", headers=admin).status_code == 200
