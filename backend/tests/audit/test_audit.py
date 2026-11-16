"""The audit trail: every area records through app.audit; platform admins read it with filters."""

import ast
import pathlib

import pytest

from tests.approvals.test_approvals import PDF, decide, inbox, submit


def events(client, admin, **params):
    r = client.get("/api/audit", params=params, headers=admin)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def test_audit_core_imports_no_feature():
    """models, catalog, context and service use only core, db and the tree models; only the router
    reaches into access (for the platform-admin guard)."""
    import app.audit

    for path in pathlib.Path(app.audit.__file__).parent.glob("*.py"):
        if path.name == "router.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            for name in names:
                if name.startswith("app."):
                    assert name.split(".")[1] in {"audit", "core", "db"} or name == "app.sources.models", \
                        f"{path.name} imports {name}"


def test_only_platform_admins_read_the_trail(client, hub):
    assert client.get("/api/audit", headers=hub["ben"]).status_code == 403
    assert events(client, hub["admin"])  # the fixture's set-up was recorded


def test_every_event_has_its_area_category_label_and_request(client, hub):
    e = events(client, hub["admin"], action="GROUP_CREATED")[0]
    assert e["source_system"] == "DOC_HUB" and e["category"] == "access" and e["label"] == "User group created"
    assert e["actor"] == "ben" and e["node_path"].startswith("/DOC_HUB/") and e["request_id"]


def test_sign_ins_succeed_fail_and_are_refused(client, hub):
    client.post("/api/auth/login", json={"username": "eve", "password": "wrong"})
    client.post("/api/users/eve/active", json={"active": False}, headers=hub["admin"])  # ends her sessions
    client.post("/api/auth/login", json={"username": "eve", "password": "pw"})  # right password, but switched off
    trail = events(client, hub["admin"], target_type="user", target_id="eve")
    codes = [e["action"] for e in trail]
    assert {"SIGN_IN", "SIGN_IN_FAILED", "SIGN_IN_REFUSED", "SESSIONS_ENDED", "USER_DEACTIVATED"} <= set(codes)
    failed = next(e for e in trail if e["action"] == "SIGN_IN_FAILED")
    assert failed["actor"] == "eve" and failed["category"] == "security" and failed["source_system"] == "PLATFORM"
    ended = next(e for e in trail if e["action"] == "SESSIONS_ENDED")
    assert ended["actor"] is None and ended["details"]["reason"] == "access_switched_off"


def test_platform_admin_granted_and_revoked_and_user_details(client, hub):
    admin = hub["admin"]
    client.put("/api/users/eve", json={"platform_admin": True}, headers=admin)
    client.put("/api/users/eve", json={"platform_admin": False, "title": "Risk analyst"}, headers=admin)
    codes = [e["action"] for e in events(client, admin, source_system="PLATFORM")]
    assert {"PLATFORM_ADMIN_GRANTED", "PLATFORM_ADMIN_REVOKED"} <= set(codes)
    [updated] = events(client, admin, action="USER_UPDATED", target_type="user", target_id="eve")
    assert updated["details"]["after"] == {"title": "Risk analyst"}


def test_documents_and_approvals_are_audited_at_the_repository(client, hub):
    [doc_id] = submit(client, hub)
    task = inbox(client, hub, "cara")[0]["id"]
    assert decide(client, hub, "cara", task, "approve").status_code == 204
    client.get(f"/api/doc-repos/{hub['repo']}/documents/{doc_id}/download", headers=hub["cara"])
    node = client.get(f"/api/doc-repos/{hub['repo']}", headers=hub["ben"]).json()["node_id"]
    trail = events(client, hub["admin"], node_id=node)
    codes = [e["action"] for e in trail]
    for code in ("DOCUMENTS_UPLOADED", "APPROVAL_SUBMITTED", "APPROVAL_DECIDED", "APPROVAL_COMPLETED",
                 "DOCUMENT_DOWNLOADED"):
        assert code in codes, code
    assert {e["source_system"] for e in trail if e["action"].startswith("APPROVAL_")} == {"APPROVALS"}
    decided = next(e for e in trail if e["action"] == "APPROVAL_DECIDED")
    assert decided["actor"] == "cara" and decided["details"]["decision"] == "APPROVED"


def test_a_refused_submission_is_audited_though_nothing_else_is_kept(client, hub):
    url = f"/api/doc-repos/{hub['repo']}"
    default = next(o for o in client.get(f"{url}/workflow", headers=hub["ben"]).json()["options"]
                   if o["code"] == "DOC_HUB.DOCUMENT_APPROVAL")
    client.put(f"{url}/workflow", json={"workflow_id": default["id"]}, headers=hub["ben"])  # names a "default" group
    [doc_id] = [d["id"] for d in client.post(f"{url}/documents", headers=hub["marcus"],
                                             files=[("files", ("r.pdf", PDF, "application/pdf"))]).json()]
    r = client.post(f"{url}/documents/submit", json={"ids": [doc_id]}, headers=hub["marcus"])
    assert r.json()["done"] == [] and r.json()["skipped"]
    [refused] = events(client, hub["admin"], action="APPROVAL_REFUSED")
    assert "no user group named default" in refused["details"]["reason"] and refused["source_system"] == "APPROVALS"
    assert events(client, hub["admin"], action="APPROVAL_SUBMITTED") == []  # rolled back with the attempt


def test_workflow_changes_are_audited(client, hub):
    from tests.helpers import GROUPS_FLOW
    admin = hub["admin"]
    wf = next(w for w in client.get("/api/approval-workflows", headers=admin).json() if w["code"] == GROUPS_FLOW["code"])
    changed = {**GROUPS_FLOW, "steps": [GROUPS_FLOW["steps"][0], {**GROUPS_FLOW["steps"][1], "name": "Checker sign-off"}]}
    client.post(f"/api/approval-workflows/{wf['id']}/versions", json={"definition": changed}, headers=admin)
    trail = events(client, admin, source_system="WORKFLOWS")
    codes = [e["action"] for e in trail]
    assert {"WORKFLOW_CREATED", "WORKFLOW_DEFAULT_CREATED", "WORKFLOW_PUBLISHED", "REPO_WORKFLOW_SET"} <= set(codes)
    published = next(e for e in trail if e["action"] == "WORKFLOW_PUBLISHED")
    assert published["details"]["steps"]["changed"] == ["checker_review"]
    switched = next(e for e in trail if e["action"] == "REPO_WORKFLOW_SET")
    assert switched["details"]["before"] == "DOC_HUB.DOCUMENT_APPROVAL" and switched["details"]["after"] == GROUPS_FLOW["code"]


def test_paging_continues_from_the_last_event(client, hub):
    first = events(client, hub["admin"], limit=3)
    second = events(client, hub["admin"], limit=3, before_id=first[-1]["id"])
    assert len(first) == 3 and second and not {e["id"] for e in first} & {e["id"] for e in second}
    assert second[0]["at"] <= first[-1]["at"]


def test_pages_by_offset_with_the_total(client, hub):
    everything = client.get("/api/audit", params={"limit": 1000}, headers=hub["admin"]).json()
    page = client.get("/api/audit", params={"offset": 2, "limit": 2}, headers=hub["admin"]).json()
    assert page["total"] == everything["total"] == len(everything["items"]) > 4
    assert [e["id"] for e in page["items"]] == [e["id"] for e in everything["items"][2:4]]


def test_recording_an_unregistered_action_is_an_error(client):
    from app.audit import service as audit
    from app.db.session import new_session
    with new_session() as db, pytest.raises(RuntimeError, match="isn't registered"):
        audit.record(db, "NOT_A_THING")


def test_repository_activity_for_its_owner_admins_and_auditors(client, hub):
    url = f"/api/doc-repos/{hub['repo']}"
    node = client.get(url, headers=hub["ben"]).json()["node_id"]
    submit(client, hub)
    assert decide(client, hub, "cara", inbox(client, hub, "cara")[0]["id"], "approve").status_code == 204
    for who in ("ben", "dana"):  # owner, admin
        assert client.get(url, headers=hub[who]).json()["access"]["activity"] is True
        trail = client.get(f"/api/audit/nodes/{node}", headers=hub[who]).json()["items"]
        assert {"DOCUMENTS_UPLOADED", "APPROVAL_SUBMITTED", "APPROVAL_DECIDED", "APPROVAL_COMPLETED"} \
            <= {e["action"] for e in trail}
    for who in ("marcus", "cara", "eve", "outsider"):  # maker, checker, viewer, nobody
        assert client.get(f"/api/audit/nodes/{node}", headers=hub[who]).status_code == 403
    assert client.get(url, headers=hub["marcus"]).json()["access"]["activity"] is False
    client.post("/api/default-grants", json={"team": "AUDIT", "role": "AUDITOR"}, headers=hub["admin"])
    assert client.get(f"/api/audit/nodes/{node}", headers=hub["ivan"]).status_code == 200  # the Audit team
    assert events(client, hub["admin"], action="DEFAULT_GRANT_ADDED")


def test_search_by_part_of_a_lan_id_in_any_case(client, hub):
    submit(client, hub)  # marcus uploads and submits
    found = events(client, hub["admin"], actor="ARC")
    assert found and all("arc" in e["actor"] for e in found)
    assert "DOCUMENTS_UPLOADED" in {e["action"] for e in found}
    assert events(client, hub["admin"], actor="nobody-like-this") == []
    assert events(client, hub["admin"], actor="%") == []  # wildcards are matched literally
