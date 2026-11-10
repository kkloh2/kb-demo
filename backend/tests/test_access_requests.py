def test_request_and_approve_grants_view_only_access(client, login):
    officer = login("comp.officer")
    r = client.post("/api/knowledge-bases/credit-risk/access-requests", json={"reason": "audit"}, headers=officer)
    assert r.status_code == 201 and r.json()["status"] == "pending"
    req_id = r.json()["id"]

    # Not visible until approved.
    assert "credit-risk" not in {kb["id"] for kb in client.get("/api/knowledge-bases", headers=officer).json()}

    r = client.post(f"/api/access-requests/{req_id}/approve", json={}, headers=login("risk.admin"))
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert r.json()["decided_by"] == "risk.admin"

    kbs = {kb["id"]: kb["access"] for kb in client.get("/api/knowledge-bases", headers=officer).json()}
    assert kbs["credit-risk"] == "granted"
    docs = client.get("/api/knowledge-bases/credit-risk/documents", headers=officer).json()
    assert {d["status"] for d in docs} == {"approved"}


def test_only_the_kbs_department_admin_decides(client, login):
    r = client.post("/api/knowledge-bases/credit-risk/access-requests", json={}, headers=login("comp.officer"))
    req_id = r.json()["id"]
    for who in ("hr.admin", "admin", "risk.checker"):
        assert client.post(f"/api/access-requests/{req_id}/approve", json={}, headers=login(who)).status_code == 403


def test_reject(client, login):
    req_id = client.post("/api/knowledge-bases/credit-risk/access-requests", json={}, headers=login("comp.officer")).json()["id"]
    r = client.post(f"/api/access-requests/{req_id}/reject", json={"note": "Not needed"}, headers=login("risk.admin"))
    assert r.json()["status"] == "rejected" and r.json()["decision_note"] == "Not needed"
    assert client.post(f"/api/access-requests/{req_id}/approve", json={}, headers=login("risk.admin")).status_code == 409


def test_cannot_request_own_department_or_duplicate(client, login):
    h = login("analyst")
    assert client.post("/api/knowledge-bases/credit-risk/access-requests", json={}, headers=h).status_code == 409
    assert client.post("/api/knowledge-bases/hr-policies/access-requests", json={}, headers=h).status_code == 409  # already granted
    assert client.post("/api/knowledge-bases/aml-compliance/access-requests", json={}, headers=h).status_code == 409  # already pending


def test_admins_cannot_request_access(client, login):
    assert client.post("/api/knowledge-bases/credit-risk/access-requests", json={}, headers=login("hr.admin")).status_code == 403


def test_listing_is_scoped(client, login):
    mine = client.get("/api/access-requests", headers=login("analyst")).json()
    assert {r["kb_id"] for r in mine} == {"hr-policies", "aml-compliance"}
    comp = client.get("/api/access-requests?status=pending", headers=login("comp.admin")).json()
    assert [r["kb_id"] for r in comp] == ["aml-compliance"]
    assert client.get("/api/access-requests", headers=login("risk.admin")).json() == []


def test_department_admin_revokes_a_viewer(client, login):
    hr = login("hr.admin")
    viewers = client.get("/api/knowledge-bases/hr-policies/viewers", headers=hr).json()
    assert [v["username"] for v in viewers] == ["analyst"]
    assert client.delete("/api/knowledge-bases/hr-policies/viewers/analyst", headers=hr).status_code == 204
    assert "hr-policies" not in {kb["id"] for kb in client.get("/api/knowledge-bases", headers=login("analyst")).json()}
