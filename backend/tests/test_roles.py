def test_system_admin_assigns_department_admin(client, login):
    r = client.put("/api/users/comp.officer/roles/department_admin", headers=login("admin"))
    assert r.status_code == 200
    assert r.json()["roles"] == ["department_admin"]


def test_department_admin_cannot_assign_department_admin(client, login):
    r = client.put("/api/users/analyst/roles/department_admin", headers=login("risk.admin"))
    assert r.status_code == 403


def test_department_admin_assigns_maker_in_own_department(client, login):
    r = client.put("/api/users/analyst/roles/maker", headers=login("risk.admin"))
    assert r.status_code == 200 and r.json()["roles"] == ["maker"]


def test_department_admin_cannot_touch_other_departments(client, login):
    r = client.put("/api/users/comp.officer/roles/maker", headers=login("risk.admin"))
    assert r.status_code == 403


def test_system_admin_cannot_assign_maker(client, login):
    assert client.put("/api/users/analyst/roles/maker", headers=login("admin")).status_code == 403


def test_one_person_cannot_be_maker_and_checker(client, login):
    r = client.put("/api/users/risk.maker/roles/checker", headers=login("risk.admin"))
    assert r.status_code == 409
    assert "can't be both" in r.json()["detail"]


def test_department_admin_cannot_also_be_maker(client, login):
    r = client.put("/api/users/risk.maker/roles/department_admin", headers=login("admin"))
    assert r.status_code == 409


def test_system_admin_and_viewer_roles_are_not_assignable(client, login):
    h = login("admin")
    assert client.put("/api/users/analyst/roles/system_admin", headers=h).status_code == 422
    assert client.put("/api/users/analyst/roles/viewer", headers=h).status_code == 422


def test_role_change_ends_the_users_sessions(client, login):
    analyst = login("analyst")
    client.put("/api/users/analyst/roles/maker", headers=login("risk.admin"))
    assert client.get("/api/auth/me", headers=analyst).status_code == 401
    # Signing in again gives a token with the new role.
    me = client.get("/api/auth/me", headers=login("analyst")).json()
    assert "maker" in me["roles"]


def test_revoke_role(client, login):
    r = client.delete("/api/users/risk.maker/roles/maker", headers=login("risk.admin"))
    assert r.status_code == 200 and r.json()["roles"] == []


def test_users_listing_is_scoped(client, login):
    risk = client.get("/api/users", headers=login("risk.admin")).json()
    assert {u["department"]["code"] for u in risk} == {"RISK"}
    everyone = client.get("/api/users", headers=login("admin")).json()
    assert len(everyone) > len(risk)
    assert client.get("/api/users", headers=login("analyst")).status_code == 403
    assert client.get("/api/users?department=HR", headers=login("risk.admin")).status_code == 403


# --------------------------------------------------------------------------- adding users


NEW = {"lan_id": "new.user", "display_name": "New User", "email": "new.user@example.com",
       "title": "Analyst", "password": "Str0ngpass"}


def test_system_admin_adds_department_admin_to_any_department(client, login):
    r = client.post("/api/users", json={**NEW, "department_code": "HR"}, headers=login("admin"))
    assert r.status_code == 201
    assert r.json()["department"]["code"] == "HR" and r.json()["roles"] == ["department_admin"]
    me = client.post("/api/auth/login", json={"username": "new.user", "password": "Str0ngpass"}).json()["user"]
    assert me["roles"] == ["department_admin"]


def test_system_admin_cannot_add_other_roles(client, login):
    r = client.post("/api/users", json={**NEW, "department_code": "HR", "role": "maker"}, headers=login("admin"))
    assert r.status_code == 422


def test_system_admin_must_choose_department(client, login):
    assert client.post("/api/users", json=NEW, headers=login("admin")).status_code == 422


def test_department_admin_adds_to_own_department(client, login):
    r = client.post("/api/users", json={**NEW, "role": "checker"}, headers=login("risk.admin"))
    assert r.status_code == 201
    assert r.json()["department"]["code"] == "RISK" and r.json()["roles"] == ["checker"]


def test_department_admin_default_is_viewer(client, login):
    r = client.post("/api/users", json=NEW, headers=login("risk.admin"))
    assert r.status_code == 201 and r.json()["roles"] == []
    me = client.post("/api/auth/login", json={"username": "new.user", "password": "Str0ngpass"}).json()["user"]
    assert me["roles"] == ["viewer"]


def test_department_admin_cannot_add_elsewhere_or_add_admins(client, login):
    h = login("risk.admin")
    assert client.post("/api/users", json={**NEW, "department_code": "HR"}, headers=h).status_code == 403
    assert client.post("/api/users", json={**NEW, "role": "department_admin"}, headers=h).status_code == 403


def test_viewers_cannot_add_users(client, login):
    assert client.post("/api/users", json=NEW, headers=login("analyst")).status_code == 403


def test_add_user_validation(client, login):
    h = login("risk.admin")
    assert client.post("/api/users", json={**NEW, "lan_id": "analyst"}, headers=h).status_code == 409
    assert client.post("/api/users", json={**NEW, "email": "analyst@example.com"}, headers=h).status_code == 409
    assert client.post("/api/users", json={**NEW, "password": "short"}, headers=h).status_code == 422
    assert client.post("/api/users", json={**NEW, "email": "not-an-email"}, headers=h).status_code == 422
    assert client.post("/api/users", json={**NEW, "lan_id": "bad id!"}, headers=h).status_code == 422


# --------------------------------------------------------------------------- departments, roles, permissions


def test_system_admin_creates_department(client, login):
    h = login("admin")
    r = client.post("/api/departments", json={"code": "treasury", "name": "Treasury"}, headers=h)
    assert r.status_code == 201 and r.json()["code"] == "TREASURY"
    codes = [d["code"] for d in client.get("/api/departments", headers=h).json()]
    assert "TREASURY" in codes
    assert client.post("/api/departments", json={"code": "TREASURY", "name": "Other"}, headers=h).status_code == 409


def test_department_admin_cannot_create_department(client, login):
    r = client.post("/api/departments", json={"code": "OPS", "name": "Operations"}, headers=login("risk.admin"))
    assert r.status_code == 403


def test_departments_include_counts(client, login):
    risk = next(d for d in client.get("/api/departments", headers=login("admin")).json() if d["code"] == "RISK")
    assert risk == {"code": "RISK", "name": "Risk Management", "members": 4, "knowledge_bases": 1, "admins": ["risk.admin"]}


def test_roles_and_permissions_are_system_admin_only(client, login):
    h = login("admin")
    roles = client.get("/api/roles", headers=h).json()
    assert [r["code"] for r in roles] == ["system_admin", "department_admin", "maker", "checker", "viewer"]
    perms = {p["code"]: p["roles"] for p in client.get("/api/permissions", headers=h).json()}
    assert perms["documents:approve"] == ["checker"]
    assert perms["users:create"] == ["system_admin", "department_admin"]
    for path in ("/api/roles", "/api/permissions"):
        assert client.get(path, headers=login("risk.admin")).status_code == 403


def test_role_sync_is_idempotent_and_reaches_existing_databases(client):
    from sqlalchemy import func, select

    from app.db.models import Permission, RolePermission
    from app.db.seed import sync_roles_and_permissions
    from app.db.session import new_session

    with new_session() as db:
        before = (db.scalar(select(func.count(Permission.id))), db.scalar(select(func.count()).select_from(RolePermission)))
        sync_roles_and_permissions(db)
        db.commit()
        after = (db.scalar(select(func.count(Permission.id))), db.scalar(select(func.count()).select_from(RolePermission)))
    assert before == after
