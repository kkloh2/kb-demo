"""@SystemRoles and @OrgUnitRoles: the decorators, how they combine, and the endpoints they guard."""

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import CurrentUser
from app.core.errors import DomainError
from app.db.session import new_session
from app.main import _domain_error
from app.users import service
from app.users.authorization import OrgUnitRoles, SystemRole, SystemRoles

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
    """Signed-in callers. risk.admin and hr.admin are department admins of RISK and HR.

    Department admins are made first, then everyone signs in, so each token is current.
    """
    directory.write_text(directory.read_text() + EXTRA_DIRECTORY_USERS)
    admin = login("admin")  # system admin (bootstrap)
    for lan_id in ("risk.admin", "hr.admin"):
        login(lan_id, "demo123")
    with new_session() as db:
        for lan_id, code in (("risk.admin", "RISK"), ("hr.admin", "HR")):
            user = service.get_by_lan_id(db, lan_id)
            service.upsert_user(db, "admin", lan_id, display_name=user.display_name, email=user.email,
                                system_roles=["PUBLIC"], org_unit_roles={code: ["DEPARTMENT_ADMIN"]})
    return {
        "admin": admin,
        "analyst": login("analyst"),  # PUBLIC only
        "risk.admin": login("risk.admin", "demo123"),
        "hr.admin": login("hr.admin", "demo123"),
    }


# --------------------------------------------------------------------------- the decorators


def test_unknown_or_wrong_scope_roles_fail_when_the_module_loads():
    with pytest.raises(ValueError):
        SystemRoles("SUPER_ADMIN")
    with pytest.raises(ValueError, match="not a system role"):
        SystemRoles("CHECKER")
    with pytest.raises(ValueError, match="not a org unit role"):
        OrgUnitRoles("SYSTEM_ADMIN")
    with pytest.raises(ValueError):
        SystemRoles()


def test_org_unit_roles_needs_the_department_parameter():
    with pytest.raises(TypeError, match="'dept'"):

        @OrgUnitRoles("DEPARTMENT_ADMIN", department="dept")
        def endpoint(code: str):
            return code


def test_system_role_is_the_old_name():
    assert SystemRole is SystemRoles


def test_stacked_decorators_wrap_once_and_list_every_guard():
    @SystemRoles("SYSTEM_ADMIN")
    @OrgUnitRoles("DEPARTMENT_ADMIN", department="code")
    def endpoint(code: str):
        return code

    assert [repr(g) for g in endpoint.role_guards] == [
        "OrgUnitRoles(DEPARTMENT_ADMIN, department='code')", "SystemRoles(SYSTEM_ADMIN)",
    ]
    assert list(__import__("inspect").signature(endpoint).parameters) == ["code", "_authorized_principal"]


def _app(*guards, use_async: bool = False) -> TestClient:
    """A throwaway app with one route under the given guards (outermost first), sharing real auth."""
    router = APIRouter()

    if use_async:

        async def endpoint(code: str, p: CurrentUser):
            return {"ok": True, "code": code, "lan_id": p.lan_id}

    else:

        def endpoint(code: str, p: CurrentUser):
            return {"ok": True, "code": code, "lan_id": p.lan_id}

    for guard in reversed(guards):
        endpoint = guard(endpoint)
    router.get("/things/{code}")(endpoint)
    app = FastAPI()
    app.add_exception_handler(DomainError, _domain_error)
    app.include_router(router)
    return TestClient(app)


@pytest.mark.parametrize("use_async", [False, True])
def test_system_roles_alone_must_hold(people, use_async):
    client = _app(SystemRoles("SYSTEM_ADMIN"), use_async=use_async)
    assert client.get("/things/RISK", headers=people["admin"]).json()["ok"] is True
    for who in ("analyst", "risk.admin"):
        r = client.get("/things/RISK", headers=people[who])
        assert r.status_code == 403
        assert r.json() == {"detail": "You don't have permission to do this."}


@pytest.mark.parametrize("use_async", [False, True])
def test_org_unit_roles_alone_must_hold_in_that_department(people, use_async):
    client = _app(OrgUnitRoles("DEPARTMENT_ADMIN", department="code"), use_async=use_async)
    assert client.get("/things/RISK", headers=people["risk.admin"]).status_code == 200
    assert client.get("/things/risk", headers=people["risk.admin"]).status_code == 200  # case-insensitive
    assert client.get("/things/HR", headers=people["risk.admin"]).status_code == 403  # other department
    assert client.get("/things/RISK", headers=people["admin"]).status_code == 403  # system admin alone isn't enough
    assert client.get("/things/RISK", headers=people["analyst"]).status_code == 403


def test_stacked_decorators_combine_with_or(people):
    client = _app(SystemRoles("SYSTEM_ADMIN"), OrgUnitRoles("DEPARTMENT_ADMIN", department="code"))
    assert client.get("/things/RISK", headers=people["admin"]).status_code == 200  # system admin
    assert client.get("/things/RISK", headers=people["risk.admin"]).status_code == 200  # RISK admin
    assert client.get("/things/RISK", headers=people["hr.admin"]).status_code == 403  # neither
    assert client.get("/things/RISK", headers=people["analyst"]).status_code == 403


def test_stacking_order_does_not_matter(people):
    client = _app(OrgUnitRoles("DEPARTMENT_ADMIN", department="code"), SystemRoles("SYSTEM_ADMIN"))
    assert client.get("/things/RISK", headers=people["admin"]).status_code == 200
    assert client.get("/things/RISK", headers=people["risk.admin"]).status_code == 200
    assert client.get("/things/RISK", headers=people["hr.admin"]).status_code == 403


def test_several_roles_in_one_decorator_are_any_of(people):
    client = _app(SystemRoles("SYSTEM_ADMIN", "PUBLIC"))
    assert client.get("/things/RISK", headers=people["analyst"]).status_code == 200


def test_guarded_endpoints_require_sign_in(people):
    assert _app(SystemRoles("SYSTEM_ADMIN")).get("/things/RISK").status_code == 401
    assert _app(OrgUnitRoles("DEPARTMENT_ADMIN")).get("/things/RISK").status_code == 401


def test_endpoint_still_gets_the_principal(people):
    r = _app(SystemRoles("SYSTEM_ADMIN")).get("/things/RISK", headers=people["admin"])
    assert r.json() == {"ok": True, "code": "RISK", "lan_id": "admin"}


# --------------------------------------------------------------------------- who may call which endpoint

CALLERS = ["admin", "risk.admin", "hr.admin", "analyst"]


def _status(client, people, who, method, url, body=None):
    return client.request(method, url, json=body, headers=people[who]).status_code


@pytest.mark.parametrize("who, allowed", [("admin", True), ("risk.admin", False), ("analyst", False)])
def test_departments_are_system_admin_only(client, people, who, allowed):
    post = _status(client, people, who, "POST", "/api/departments", {"code": "OPS", "name": "Operations"})
    put = _status(client, people, who, "PUT", "/api/departments/RISK", {"code": "RISK", "name": "Risk"})
    delete = _status(client, people, who, "DELETE", "/api/departments/HR")
    assert (post, put, delete) == ((201, 200, 204) if allowed else (403, 403, 403))


@pytest.mark.parametrize("who, allowed", [("admin", True), ("risk.admin", False), ("analyst", False)])
def test_users_are_system_admin_only(client, people, who, allowed):
    body = {"display_name": "New Joiner", "email": "new.joiner@datahub.local",
            "system_roles": ["PUBLIC"], "org_unit_roles": {}}
    put = _status(client, people, who, "PUT", "/api/users/new.joiner", body)
    delete = _status(client, people, who, "DELETE", "/api/users/analyst")
    assert (put, delete) == ((201, 204) if allowed else (403, 403))


@pytest.mark.parametrize("who, allowed", [("admin", True), ("risk.admin", True), ("hr.admin", False), ("analyst", False)])
def test_department_roles_are_system_admin_or_that_departments_admin(client, people, who, allowed):
    put = _status(client, people, who, "PUT", "/api/departments/RISK/users/analyst", {"roles": ["VIEWER"]})
    delete = _status(client, people, who, "DELETE", "/api/departments/RISK/users/analyst")
    assert (put, delete) == ((200, 204) if allowed else (403, 403))


def test_all_endpoints_need_sign_in(client):
    for method, url, body in [
        ("POST", "/api/departments", {"code": "OPS", "name": "Ops"}),
        ("PUT", "/api/departments/RISK", {"code": "RISK", "name": "Risk"}),
        ("DELETE", "/api/departments/RISK", None),
        ("PUT", "/api/users/x", {"display_name": "X", "email": "x@x", "system_roles": [], "org_unit_roles": {}}),
        ("DELETE", "/api/users/x", None),
        ("PUT", "/api/departments/RISK/users/x", {"roles": []}),
        ("DELETE", "/api/departments/RISK/users/x", None),
    ]:
        assert client.request(method, url, json=body).status_code == 401, (method, url)


# --------------------------------------------------------------------------- endpoint behaviour


def test_post_put_delete_department(client, people):
    h = people["admin"]
    r = client.post("/api/departments", json={"code": "ops", "name": "Operations"}, headers=h)
    assert r.status_code == 201
    assert r.headers["location"] == "/api/departments/OPS"
    created = r.json()
    assert (created["code"], created["name"]) == ("OPS", "Operations")
    assert client.post("/api/departments", json={"code": "OPS", "name": "Again"}, headers=h).status_code == 409

    r = client.put("/api/departments/ops", json={"code": "OPX", "name": "Ops"}, headers=h)
    assert (r.status_code, r.json()) == (200, {"id": created["id"], "code": "OPX", "name": "Ops"})
    assert client.put("/api/departments/OPS", json={"code": "OPS", "name": "x"}, headers=h).status_code == 404
    assert client.put("/api/departments/OPX", json={"code": "RISK", "name": "x"}, headers=h).status_code == 409
    assert client.put("/api/departments/OPX", json={"name": "only name"}, headers=h).status_code == 422

    assert client.delete("/api/departments/OPX", headers=h).status_code == 204
    assert client.delete("/api/departments/OPX", headers=h).status_code == 404


def test_old_department_routes_are_gone(client, people):
    assert client.put("/api/departments", json={"code": "OPS", "name": "Ops"}, headers=people["admin"]).status_code == 405


def test_put_user_creates_then_updates(client, people):
    body = {"display_name": "New Joiner", "email": "new.joiner@datahub.local", "title": "Analyst",
            "system_roles": [], "org_unit_roles": {"hr": ["DEPARTMENT_ADMIN"], "RISK": ["maker", "VIEWER"]}}
    r = client.put("/api/users/New.Joiner", json=body, headers=people["admin"])
    assert r.status_code == 201
    assert r.json() == {
        "lan_id": "new.joiner", "display_name": "New Joiner", "email": "new.joiner@datahub.local",
        "department": "", "title": "Analyst", "system_roles": ["PUBLIC"],
        "org_unit_roles": {"HR": ["DEPARTMENT_ADMIN"], "RISK": ["MAKER", "VIEWER"]},
    }
    r = client.put("/api/users/new.joiner", json={**body, "org_unit_roles": {"RISK": ["CHECKER"]}},
                   headers=people["admin"])
    assert (r.status_code, r.json()["org_unit_roles"]) == (200, {"RISK": ["CHECKER"]})


def test_put_user_validation(client, people):
    body = {"display_name": "X", "email": "x@datahub.local", "system_roles": ["PUBLIC"], "org_unit_roles": {}}
    put = lambda b: client.put("/api/users/x", json=b, headers=people["admin"]).status_code  # noqa: E731
    assert put({k: v for k, v in body.items() if k != "system_roles"}) == 422  # role fields are required
    assert put({k: v for k, v in body.items() if k != "org_unit_roles"}) == 422
    assert put({**body, "system_roles": ["MAKER"]}) == 422
    assert put({**body, "org_unit_roles": {"RISK": ["SYSTEM_ADMIN"]}}) == 422
    assert put({**body, "org_unit_roles": {"NOPE": ["VIEWER"]}}) == 404
    assert put({**body, "org_unit_roles": {"RISK": ["MAKER", "CHECKER"]}}) == 409
    assert put({**body, "email": "rita.lim@datahub.local"}) == 409
    own = {"display_name": "Data Hub Admin", "email": "admin@datahub.local", "system_roles": ["PUBLIC"],
           "org_unit_roles": {}}
    assert client.put("/api/users/admin", json=own, headers=people["admin"]).status_code == 409


def test_put_department_roles_returns_the_user(client, people):
    r = client.put("/api/departments/risk/users/analyst", json={"roles": ["checker", "VIEWER"]},
                   headers=people["risk.admin"])
    assert r.status_code == 200
    assert r.json()["org_unit_roles"] == {"RISK": ["CHECKER", "VIEWER"]}
    r = client.put("/api/departments/RISK/users/analyst", json={"roles": ["MAKER", "CHECKER"]},
                   headers=people["risk.admin"])
    assert r.status_code == 409
    r = client.put("/api/departments/RISK/users/analyst", json={"roles": ["DEPARTMENT_ADMIN"]},
                   headers=people["risk.admin"])
    assert r.status_code == 422


def test_delete_user_endpoint(client, people):
    assert client.delete("/api/users/analyst", headers=people["admin"]).status_code == 204
    assert client.delete("/api/users/analyst", headers=people["admin"]).status_code == 404
    assert client.delete("/api/users/admin", headers=people["admin"]).status_code == 409
