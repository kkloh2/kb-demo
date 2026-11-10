def _ids(client, h):
    return {kb["id"]: kb["access"] for kb in client.get("/api/knowledge-bases", headers=h).json()}


def test_member_sees_own_department_and_granted(client, login):
    assert _ids(client, login("analyst")) == {"credit-risk": "department", "hr-policies": "granted"}


def test_member_without_grants_sees_only_own_department(client, login):
    assert _ids(client, login("comp.officer")) == {"aml-compliance": "department"}


def test_department_admin_sees_own_department_as_admin(client, login):
    assert _ids(client, login("risk.admin")) == {"credit-risk": "admin"}


def test_system_admin_sees_all(client, login):
    ids = _ids(client, login("admin"))
    assert len(ids) == 4 and set(ids.values()) == {"admin"}


def test_only_system_admin_creates(client, login):
    body = {"name": "Treasury Ops", "description": "FX and liquidity", "department_code": "RISK",
            "admin_lan_id": "risk.admin"}
    assert client.post("/api/knowledge-bases", json=body, headers=login("risk.admin")).status_code == 403
    r = client.post("/api/knowledge-bases", json=body, headers=login("admin"))
    assert r.status_code == 201
    assert r.json()["id"] == "treasury-ops" and r.json()["department"]["code"] == "RISK"
    assert "treasury-ops" in _ids(client, login("risk.maker"))


def test_department_admin_maintains_own_kb_only(client, login):
    h = login("risk.admin")
    assert client.patch("/api/knowledge-bases/credit-risk", json={"description": "Updated"}, headers=h).status_code == 200
    assert client.patch("/api/knowledge-bases/hr-policies", json={"description": "x"}, headers=h).status_code == 404


def test_viewer_cannot_edit(client, login):
    r = client.patch("/api/knowledge-bases/credit-risk", json={"name": "x"}, headers=login("analyst"))
    assert r.status_code == 403


def test_favorites_are_saved(client, login):
    h = login("analyst")
    assert client.put("/api/knowledge-bases/credit-risk/favorite", headers=h).status_code == 204
    favs = {kb["id"] for kb in client.get("/api/knowledge-bases", headers=h).json() if kb["favorite"]}
    assert favs == {"credit-risk", "hr-policies"}
    client.delete("/api/knowledge-bases/hr-policies/favorite", headers=h)
    favs = {kb["id"] for kb in client.get("/api/knowledge-bases", headers=h).json() if kb["favorite"]}
    assert favs == {"credit-risk"}


def test_directory_lists_everything_with_access_and_pending_flags(client, login):
    rows = {kb["id"]: kb for kb in client.get("/api/knowledge-bases/directory", headers=login("analyst")).json()}
    assert len(rows) == 4
    assert rows["aml-compliance"]["access"] is None and rows["aml-compliance"]["request_pending"] is True
    assert rows["data-governance"]["access"] is None and rows["data-governance"]["request_pending"] is False


# --------------------------------------------------------------------------- naming the KB's admin

KB = {"name": "Treasury Ops", "description": "FX and liquidity", "department_code": "RISK"}


def test_create_names_an_existing_department_admin(client, login):
    r = client.post("/api/knowledge-bases", json={**KB, "admin_lan_id": "risk.admin"}, headers=login("admin"))
    assert r.status_code == 201
    assert r.json()["admin"] == {"username": "risk.admin", "display_name": "Risk Admin"}
    detail = client.get("/api/knowledge-bases/treasury-ops", headers=login("risk.maker")).json()
    assert detail["admin"]["username"] == "risk.admin"


def test_create_promotes_a_viewer_to_department_admin(client, login):
    analyst = login("analyst")
    r = client.post("/api/knowledge-bases", json={**KB, "admin_lan_id": "analyst"}, headers=login("admin"))
    assert r.status_code == 201
    users = {u["username"]: u["roles"] for u in client.get("/api/users?department=RISK", headers=login("admin")).json()}
    assert users["analyst"] == ["department_admin"]
    assert client.get("/api/auth/me", headers=analyst).status_code == 401  # old token's roles are stale


def test_create_refuses_makers_and_checkers_and_creates_nothing(client, login):
    h = login("admin")
    r = client.post("/api/knowledge-bases", json={**KB, "admin_lan_id": "risk.maker"}, headers=h)
    assert r.status_code == 409 and "can't be both" in r.json()["detail"]
    assert "treasury-ops" not in {kb["id"] for kb in client.get("/api/knowledge-bases", headers=h).json()}


def test_create_admin_must_be_in_the_department(client, login):
    h = login("admin")
    r = client.post("/api/knowledge-bases", json={**KB, "admin_lan_id": "hr.admin"}, headers=h)
    assert r.status_code == 422 and "isn't in Risk Management" in r.json()["detail"]
    assert client.post("/api/knowledge-bases", json={**KB, "admin_lan_id": "nobody"}, headers=h).status_code == 422
    assert client.post("/api/knowledge-bases", json=KB, headers=h).status_code == 422  # admin is required


def test_seeded_kbs_have_admins(client, login):
    kbs = {kb["id"]: kb["admin"]["username"] for kb in client.get("/api/knowledge-bases", headers=login("admin")).json()}
    assert kbs == {"credit-risk": "risk.admin", "hr-policies": "hr.admin",
                   "aml-compliance": "comp.admin", "data-governance": "data.admin"}
