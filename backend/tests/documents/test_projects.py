"""Projects: who sees, creates and manages them; project members; the @ProjectRoles guard."""

import pytest

from app.db.session import new_session
from app.users import service as users

EXTRA_DIRECTORY_USERS = """
  risk.admin:
    password: demo123
    display_name: Rita Lim
    email: rita.lim@datahub.local
    department: Risk Management
    title: Risk Lead
  risk.viewer:
    password: demo123
    display_name: Victor Ng
    email: victor.ng@datahub.local
    department: Risk Management
    title: Risk Analyst
  hr.admin:
    password: demo123
    display_name: Hari Kumar
    email: hari.kumar@datahub.local
    department: Human Resources
    title: HR Lead
  outsider:
    password: demo123
    display_name: Olive Out
    email: olive.out@datahub.local
    department: Operations
    title: Ops Analyst
"""

ROLES = {
    "risk.admin": {"RISK": ["DEPARTMENT_ADMIN"]},
    "risk.viewer": {"RISK": ["VIEWER"]},
    "hr.admin": {"HR": ["DEPARTMENT_ADMIN"]},
    "outsider": {},
}


@pytest.fixture
def people(client, directory, login):
    """Signed-in callers with department roles set first, so each token is current."""
    directory.write_text(directory.read_text() + EXTRA_DIRECTORY_USERS)
    admin = login("admin")
    for lan_id in ROLES:
        login(lan_id, "demo123")
    with new_session() as db:
        for lan_id, org in ROLES.items():
            u = users.get_by_lan_id(db, lan_id)
            users.upsert_user(db, "admin", lan_id, display_name=u.display_name, email=u.email,
                              system_roles=["PUBLIC"], org_unit_roles=org)
    return {"admin": admin, **{lan_id: login(lan_id, "demo123") for lan_id in ROLES}}


CARD_POLICIES = {"name": "Card Policies", "description": "Credit card policy documents", "country": "Singapore",
                 "business_unit": "Consumer Banking", "purpose": "Credit card", "valid_till": "2027-12-31"}


def _create(client, people, who="risk.admin", dept="RISK", body=CARD_POLICIES):
    return client.post(f"/api/departments/{dept}/projects", json=body, headers=people[who])


def _project_id(client, people):
    r = _create(client, people)
    assert r.status_code == 201, r.text
    return r.json()["id"]


# --------------------------------------------------------------------------- create


def test_department_admin_creates_a_project_with_base_metadata(client, people):
    r = _create(client, people, dept="risk")
    assert r.status_code == 201
    body = r.json()
    assert r.headers["location"] == f"/api/projects/{body['id']}"
    assert {k: body[k] for k in CARD_POLICIES} == CARD_POLICIES
    assert body["department"] == {"code": "RISK", "name": "Risk Management"}
    assert body["created_by"] == "Rita Lim"
    assert body["access"] == {"manage": True, "view_documents": True, "upload": False, "review": False,
                              "project_roles": []}


def test_project_names_are_unique_within_a_department(client, people):
    assert _create(client, people).status_code == 201
    assert _create(client, people).status_code == 409
    other = {**CARD_POLICIES, "name": "card policies "}  # names are trimmed, case matters
    assert _create(client, people, body=other).status_code == 201


@pytest.mark.parametrize("who", ["hr.admin", "risk.viewer", "outsider", "admin"])
def test_only_that_departments_admin_creates_projects(client, people, who):
    assert _create(client, people, who=who).status_code == 403


def test_creatable_departments(client, people):
    assert client.get("/api/projects/departments", headers=people["risk.admin"]).json() == [
        {"code": "RISK", "name": "Risk Management"}]
    assert client.get("/api/projects/departments", headers=people["risk.viewer"]).json() == []


# --------------------------------------------------------------------------- see


def test_who_sees_the_project_list(client, people):
    _project_id(client, people)
    names = lambda who: [p["name"] for p in client.get("/api/projects", headers=people[who]).json()]  # noqa: E731
    assert names("risk.admin") == ["Card Policies"]
    assert names("risk.viewer") == ["Card Policies"]  # department VIEWER sees the list
    assert names("hr.admin") == []  # other department
    assert names("outsider") == []
    assert names("admin") == []  # system admin holds no department role


def test_department_viewer_sees_the_project_but_not_its_documents(client, people):
    pid = _project_id(client, people)
    r = client.get(f"/api/projects/{pid}", headers=people["risk.viewer"])
    assert r.status_code == 200
    assert r.json()["access"] == {"manage": False, "view_documents": False, "upload": False, "review": False,
                                  "project_roles": []}


def test_department_admin_is_a_viewer_of_every_project(client, people):
    pid = _project_id(client, people)
    assert client.get(f"/api/projects/{pid}", headers=people["risk.admin"]).json()["access"]["view_documents"]


@pytest.mark.parametrize("who", ["hr.admin", "outsider", "admin"])
def test_others_cannot_see_the_project(client, people, who):
    pid = _project_id(client, people)
    assert client.get(f"/api/projects/{pid}", headers=people[who]).status_code == 403


def test_missing_project(client, people):
    assert client.get("/api/projects/999", headers=people["risk.admin"]).status_code == 404


def test_projects_need_sign_in(client):
    assert client.get("/api/projects").status_code == 401
    assert client.get("/api/projects/1").status_code == 401


# --------------------------------------------------------------------------- update & delete


def test_department_admin_updates_and_deletes(client, people):
    pid = _project_id(client, people)
    body = {**CARD_POLICIES, "name": "Card Policies 2027", "purpose": "Credit card", "valid_till": None}
    r = client.put(f"/api/projects/{pid}", json=body, headers=people["risk.admin"])
    assert (r.status_code, r.json()["name"], r.json()["valid_till"]) == (200, "Card Policies 2027", None)
    assert client.delete(f"/api/projects/{pid}", headers=people["risk.admin"]).status_code == 204
    assert client.get(f"/api/projects/{pid}", headers=people["risk.admin"]).status_code == 404


@pytest.mark.parametrize("who", ["risk.viewer", "hr.admin", "outsider"])
def test_others_cannot_update_or_delete(client, people, who):
    pid = _project_id(client, people)
    assert client.put(f"/api/projects/{pid}", json=CARD_POLICIES, headers=people[who]).status_code == 403
    assert client.delete(f"/api/projects/{pid}", headers=people[who]).status_code == 403


def test_department_with_projects_cannot_be_deleted(client, people):
    _project_id(client, people)
    r = client.delete("/api/departments/RISK", headers=people["admin"])
    assert r.status_code == 409
    assert "projects" in r.json()["detail"]
    with new_session() as db:  # nothing was removed, roles included
        assert users.get_department(db, "RISK") is not None
        assert users.org_unit_roles(db, users.get_by_lan_id(db, "risk.admin")) == {"RISK": {"DEPARTMENT_ADMIN"}}


# --------------------------------------------------------------------------- members


def _set(client, people, pid, lan_id, roles, who="risk.admin"):
    return client.put(f"/api/projects/{pid}/members/{lan_id}", json={"roles": roles}, headers=people[who])


def test_department_admin_gives_project_roles(client, people):
    pid = _project_id(client, people)
    r = _set(client, people, pid, "risk.viewer", ["checker", "VIEWER"])
    assert (r.status_code, r.json()["roles"]) == (200, ["CHECKER", "VIEWER"])
    assert _set(client, people, pid, "outsider", ["MAKER"]).status_code == 200
    members = client.get(f"/api/projects/{pid}/members", headers=people["risk.admin"]).json()
    assert [(m["lan_id"], m["roles"]) for m in members] == [("outsider", ["MAKER"]), ("risk.viewer", ["CHECKER", "VIEWER"])]


def test_project_roles_take_effect_without_signing_in_again(client, people):
    pid = _project_id(client, people)
    assert client.get(f"/api/projects/{pid}", headers=people["outsider"]).status_code == 403
    _set(client, people, pid, "outsider", ["MAKER"])
    r = client.get(f"/api/projects/{pid}", headers=people["outsider"])  # same token as before
    assert r.status_code == 200
    assert r.json()["access"] == {"manage": False, "view_documents": True, "upload": True, "review": False,
                                  "project_roles": ["MAKER"]}
    assert [p["name"] for p in client.get("/api/projects", headers=people["outsider"]).json()] == ["Card Policies"]


def test_member_roles_replace_and_remove(client, people):
    pid = _project_id(client, people)
    _set(client, people, pid, "risk.viewer", ["MAKER"])
    assert _set(client, people, pid, "risk.viewer", ["CHECKER"]).json()["roles"] == ["CHECKER"]  # swap
    assert client.delete(f"/api/projects/{pid}/members/risk.viewer", headers=people["risk.admin"]).status_code == 204
    assert client.get(f"/api/projects/{pid}/members", headers=people["risk.admin"]).json() == []


@pytest.mark.parametrize("roles, status", [(["MAKER", "CHECKER"], 409), (["OWNER"], 422), (["DEPARTMENT_ADMIN"], 422)])
def test_member_role_rules(client, people, roles, status):
    pid = _project_id(client, people)
    assert _set(client, people, pid, "risk.viewer", roles).status_code == status


def test_unknown_member(client, people):
    pid = _project_id(client, people)
    assert _set(client, people, pid, "nobody", ["VIEWER"]).status_code == 404


@pytest.mark.parametrize("who", ["risk.viewer", "hr.admin", "outsider"])
def test_only_the_department_admin_manages_members(client, people, who):
    pid = _project_id(client, people)
    assert client.get(f"/api/projects/{pid}/members", headers=people[who]).status_code == 403
    assert _set(client, people, pid, "risk.viewer", ["VIEWER"], who=who).status_code == 403


def test_project_members_cannot_manage_the_project(client, people):
    pid = _project_id(client, people)
    _set(client, people, pid, "outsider", ["CHECKER"])
    assert client.put(f"/api/projects/{pid}", json=CARD_POLICIES, headers=people["outsider"]).status_code == 403
    assert _set(client, people, pid, "outsider", ["MAKER"], who="outsider").status_code == 403


# --------------------------------------------------------------------------- the guard itself


def test_project_roles_guard_validates_when_the_module_loads():
    from app.documents.authorization import ProjectRoles

    with pytest.raises(ValueError):
        ProjectRoles("OWNER")
    with pytest.raises(ValueError):
        ProjectRoles(department_roles=("SYSTEM_ADMIN",))
    with pytest.raises(ValueError):
        ProjectRoles()
    with pytest.raises(TypeError, match="'project_id'"):

        @ProjectRoles("VIEWER")
        def endpoint(code: str):
            return code
