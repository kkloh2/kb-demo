"""The access model: sign-in, system roots, platform admins, teams, default grants, audit."""

import ast
import pathlib

import jwt
import pytest

from app.access import service as access
from app.access.catalog import RoleCode, SystemCode
from app.db.session import new_session


def _claims(headers: dict[str, str]) -> dict:
    return jwt.decode(headers["Authorization"].removeprefix("Bearer "), options={"verify_signature": False})


def test_first_sign_in_joins_the_platform_as_viewer(client, login):
    h = login("analyst")
    assert _claims(h)["system_roles"] == {"PLATFORM": ["VIEWER"]}
    me = client.get("/api/me/access", headers=h).json()
    assert me["platform_admin"] is False and me["can_decide"] is False
    assert {(n["system"], n["node_type"], tuple(n["roles"])) for n in me["nodes"]} == {("PLATFORM", "ROOT", ("VIEWER",))}


def test_once_doc_hub_exists_everyone_is_a_user_of_it(client, login, doc_hub):
    assert _claims(login("analyst"))["system_roles"] == {"DOC_HUB": ["VIEWER"], "PLATFORM": ["VIEWER"]}


def test_the_bootstrap_admin_is_a_platform_admin(client, login):
    h = login("admin")
    assert _claims(h)["system_roles"] == {"PLATFORM": ["ADMIN", "VIEWER"]}  # admins, and users like everyone
    assert client.get("/api/me/access", headers=h).json()["platform_admin"] is True


@pytest.mark.parametrize("path", ["/api/users", "/api/roles", "/api/sources", "/api/teams", "/api/default-grants",
                                  "/api/audit", "/api/doc-repos/deleted"])
def test_platform_admin_pages_are_for_platform_admins(client, login, path):
    assert client.get(path, headers=login("analyst")).status_code == 403
    assert client.get(path, headers=login("admin")).status_code == 200
    assert client.get(path).status_code == 401


def test_roles_list_every_role_with_its_permissions(client, login):
    body = client.get("/api/roles", headers=login("admin")).json()
    assert [r["code"] for r in body["roles"]] == ["OWNER", "ADMIN", "MAKER", "CHECKER", "VIEWER", "APPROVER", "AUDITOR"]
    checker = next(r for r in body["roles"] if r["code"] == "CHECKER")
    assert "docs.document.approve" in checker["permissions"]


def test_nobody_removes_their_own_platform_admin_role(client, login):
    r = client.put("/api/sources/PLATFORM/groups/ADMINS/members/admin", json={"roles": []}, headers=login("admin"))
    assert r.status_code == 409


def test_platform_admin_adds_and_promotes_users(client, login):
    admin = login("admin")
    r = client.put("/api/users/newbie", json={"display_name": "New Bie", "email": "newbie@datahub.local"}, headers=admin)
    assert r.status_code == 201 and r.json()["platform_admin"] is False
    r = client.put("/api/users/newbie", json={"display_name": "New Bie", "email": "newbie@datahub.local",
                                              "platform_admin": True}, headers=admin)
    assert r.status_code == 200 and r.json()["platform_admin"] is True


def test_a_user_can_be_added_with_just_a_lan_id(client, login):
    admin = login("admin")
    r = client.put("/api/users/ben", json={}, headers=admin)
    assert r.status_code == 201
    assert (r.json()["display_name"], r.json()["email"]) == ("ben", "ben@pending.invalid")
    login("ben")  # the directory fills in their details at first sign-in
    ben = next(u for u in client.get("/api/users", headers=admin).json() if u["lan_id"] == "ben")
    assert (ben["display_name"], ben["email"]) == ("Ben Ong", "ben@datahub.local")
    # an update that leaves fields out keeps them
    client.put("/api/users/ben", json={"platform_admin": True}, headers=admin)
    ben = next(u for u in client.get("/api/users", headers=admin).json() if u["lan_id"] == "ben")
    assert ben["display_name"] == "Ben Ong" and ben["platform_admin"] is True


def test_switching_access_off_ends_sessions_and_refuses_sign_in(client, login):
    h = login("analyst")
    admin = login("admin")
    assert client.post("/api/users/analyst/active", json={"active": False}, headers=admin).json()["status"] == "INACTIVE"
    assert client.get("/api/me/access", headers=h).status_code == 401
    r = client.post("/api/auth/login", json={"username": "analyst", "password": "datahub123"})
    assert r.status_code == 401 and "switched off" in r.json()["detail"]
    client.post("/api/users/analyst/active", json={"active": True}, headers=admin)
    login("analyst")
    assert client.post("/api/users/admin/active", json={"active": False}, headers=admin).status_code == 409


def test_someone_removed_from_doc_hub_stays_removed(client, login, doc_hub):
    login("analyst")
    r = client.put("/api/sources/DOC_HUB/groups/USERS/members/analyst", json={"roles": []}, headers=doc_hub)
    assert r.status_code == 200
    h = login("analyst")  # signing in again doesn't re-add them
    assert "DOC_HUB" not in _claims(h)["system_roles"]
    assert client.get("/api/doc-repos", headers=h).status_code == 403


def test_teams_are_set_by_platform_admins(client, login):
    login("ivan")
    admin = login("admin")
    r = client.put("/api/teams/AUDIT/members", json={"lan_ids": ["ivan"]}, headers=admin)
    assert r.status_code == 200 and [m["lan_id"] for m in r.json()["members"]] == ["ivan"]
    assert {t["code"] for t in client.get("/api/teams", headers=admin).json()} == {"AUDIT", "COMPLIANCE"}
    assert client.put("/api/teams/NOPE/members", json={"lan_ids": []}, headers=admin).status_code == 404


def test_default_grants_take_read_only_roles_only(client, login, doc_hub):
    admin = login("admin")
    r = client.post("/api/default-grants", json={"team": "AUDIT", "role": "MAKER"}, headers=admin)
    assert r.status_code == 422
    r = client.post("/api/default-grants", json={"team": "AUDIT", "role": "AUDITOR"}, headers=admin)
    assert r.status_code == 201 and r.json()["role"] == "AUDITOR"
    assert client.post("/api/default-grants", json={"team": "AUDIT", "role": "AUDITOR"}, headers=admin).status_code == 409


def test_access_changes_are_audited(client, login, doc_hub):
    login("ben")
    admin = doc_hub
    client.put("/api/sources/DOC_HUB/groups/ADMINS/members/ben", json={"roles": ["ADMIN"]}, headers=admin)
    events = client.get("/api/audit", headers=admin).json()["items"]
    assert any(e["action"] == "ROOT_GROUP_ROLES_SET" and e["target_id"] == "ben" and e["actor"] == "admin"
               and e["source_system"] == "DOC_HUB" and e["category"] == "access" for e in events)


def test_seeding_gives_a_platform_admin_only_when_there_is_none(client):
    with new_session() as db:
        assert access.seed_platform_admins(db) == []  # admin already is one
        root = access.root_node(db, SystemCode.PLATFORM)
        assert [u.lan_id for u in access.holders_of(db, root.id, RoleCode.ADMIN)] == ["admin"]


def test_access_imports_no_feature():
    """Access stays below the features: only auth, core, db, audit and the tree models in app.sources."""
    import app.access

    for path in pathlib.Path(app.access.__file__).parent.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            for name in names:
                if name.startswith("app."):
                    assert name.split(".")[1] in {"access", "audit", "auth", "core", "db"} or name == "app.sources.models", \
                        f"{path.name} imports {name}"


def test_approvals_never_imports_doc_hub():
    import app.approvals

    for path in pathlib.Path(app.approvals.__file__).parent.glob("*.py"):
        assert "app.documents" not in path.read_text(), path.name
