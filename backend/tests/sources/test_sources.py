"""Source systems: platform admins create them, their hierarchy and root (admins and users groups)."""

import pytest


def _source(client, admin, code="DOC_HUB", name="Document repositories"):
    return client.post("/api/sources", json={"code": code, "name": name}, headers=admin)


def test_only_platform_exists_at_first(client, login):
    sources = client.get("/api/sources", headers=login("admin")).json()
    assert [s["code"] for s in sources] == ["PLATFORM"]
    groups = {g["type"]: g for g in sources[0]["hierarchy"]["groups"]}
    assert set(groups) == {"ADMINS", "USERS"}
    assert [m["lan_id"] for m in groups["ADMINS"]["members"]] == ["admin"]
    assert groups["USERS"]["auto_join_role"] == "VIEWER"


def test_platform_admin_creates_a_source_system_and_its_hierarchy(client, login):
    login("analyst")  # signed in before Doc Hub exists
    admin = login("admin")
    r = _source(client, admin)
    assert r.status_code == 201 and r.json()["hierarchy"] is None
    r = client.post("/api/sources/DOC_HUB/hierarchy", json={"name": "Doc Hub", "levels": ["DOC_REPO"]}, headers=admin)
    assert r.status_code == 201
    h = r.json()["hierarchy"]
    assert h["name"] == "Doc Hub" and h["levels"] == ["ROOT", "DOC_REPO"] and h["child_count"] == 0
    groups = {g["type"]: g for g in h["groups"]}
    assert {m["lan_id"]: m["roles"] for m in groups["ADMINS"]["members"]} == {"admin": ["ADMIN"]}  # platform admins
    assert {m["lan_id"] for m in groups["USERS"]["members"]} == {"admin", "analyst"}  # everyone so far
    assert groups["ADMINS"]["roles"] == ["ADMIN"] and groups["USERS"]["roles"] == ["VIEWER"]


def test_last_updated_follows_changes_to_its_groups(client, login, doc_hub):
    login("ben")
    before = next(s for s in client.get("/api/sources", headers=doc_hub).json() if s["code"] == "DOC_HUB")
    client.put("/api/sources/DOC_HUB/groups/ADMINS/members/ben", json={"roles": ["ADMIN"]}, headers=doc_hub)
    after = next(s for s in client.get("/api/sources", headers=doc_hub).json() if s["code"] == "DOC_HUB")
    assert after["last_updated"] > before["last_updated"] >= after["created_at"]


@pytest.mark.parametrize("code, levels", [("DOC_HUB", ["ROOT", "DOC_REPO"]), ("REPORTS", ["ROOT"])])
def test_a_hierarchy_without_levels_gets_the_ones_data_hub_knows(client, login, code, levels):
    admin = login("admin")
    _source(client, admin, code=code, name="Something")
    h = client.post(f"/api/sources/{code}/hierarchy", json={}, headers=admin).json()["hierarchy"]
    assert h["levels"] == levels and h["name"] == code  # the root is named after the code


def test_people_signing_in_later_join_the_users_group(client, login, doc_hub):
    login("ben")
    users = next(g for g in client.get("/api/sources", headers=doc_hub).json()[1]["hierarchy"]["groups"]
                 if g["type"] == "USERS")
    assert "ben" in {m["lan_id"] for m in users["members"]}


@pytest.mark.parametrize("code, status", [("DOC HUB", 201), ("x", 422), ("1ABC", 422), ("PLATFORM", 409)])
def test_source_codes(client, login, code, status):
    assert _source(client, login("admin"), code=code).status_code == status


def test_a_hierarchy_is_created_once(client, login, doc_hub):
    r = client.post("/api/sources/DOC_HUB/hierarchy", json={"levels": ["DOC_REPO"]}, headers=doc_hub)
    assert r.status_code == 409
    assert client.post("/api/sources/PLATFORM/hierarchy", json={}, headers=doc_hub).status_code == 409


@pytest.mark.parametrize("who", ["analyst", "ben"])
def test_only_platform_admins_manage_sources(client, login, who):
    h = login(who)
    assert client.get("/api/sources", headers=h).status_code == 403
    assert _source(client, h).status_code == 403


def test_root_groups_hold_their_own_roles(client, login, doc_hub):
    login("ben")
    url = "/api/sources/DOC_HUB/groups"
    assert client.put(f"{url}/ADMINS/members/ben", json={"roles": ["VIEWER"]}, headers=doc_hub).status_code == 422
    assert client.put(f"{url}/ADMINS/members/ben", json={"roles": ["ADMIN"]}, headers=doc_hub).status_code == 200
    assert client.get("/api/me/access", headers=login("ben")).json()["system_roles"]["DOC_HUB"] == ["ADMIN", "VIEWER"]
    # taking ben out of admins leaves him a user
    assert client.delete(f"{url}/ADMINS/members/ben", headers=doc_hub).status_code == 204
    assert client.get("/api/me/access", headers=login("ben")).json()["system_roles"]["DOC_HUB"] == ["VIEWER"]


def test_doc_hub_admins_and_platform_admins_create_repositories(client, login, doc_hub):
    login("ben")
    login("andy")
    client.put("/api/sources/DOC_HUB/groups/ADMINS/members/ben", json={"roles": ["ADMIN"]}, headers=doc_hub)
    assert client.post("/api/doc-repos", json={"name": "Ben's"}, headers=login("ben")).status_code == 201
    assert client.post("/api/doc-repos", json={"name": "Platform's"}, headers=doc_hub).status_code == 201
    assert client.post("/api/doc-repos", json={"name": "Andy's"}, headers=login("andy")).status_code == 403


def test_doc_hub_needs_setting_up_first(client, login):
    admin = login("admin")
    r = client.post("/api/doc-repos", json={"name": "Too early"}, headers=login("analyst"))
    assert r.status_code == 404 and "isn't set up yet" in r.json()["detail"]
    _source(client, admin)
    client.post("/api/sources/DOC_HUB/hierarchy", json={"levels": ["SOMETHING_ELSE"]}, headers=admin)
    r = client.post("/api/doc-repos", json={"name": "Wrong levels"}, headers=admin)
    assert r.status_code == 422 and "levels" in r.json()["detail"]
