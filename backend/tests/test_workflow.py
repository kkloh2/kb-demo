"""The approval workflow module, and documents as its first subject."""

import json

import pytest

from app.workflow.builtin import SingleReviewEngine

PDF = b"%PDF-1.4 test"


def _upload(client, h, kb="credit-risk", name="memo.pdf"):
    r = client.post(f"/api/knowledge-bases/{kb}/documents",
                    files=[("files", (name, PDF, "application/pdf"))], headers=h)
    assert r.status_code == 201, r.text
    return r.json()[0]["id"]


# --------------------------------------------------------------------------- engine


def test_single_review_engine():
    e = SingleReviewEngine()
    snap = e.start(None, {"document_id": 1})
    assert [t.lane for t in snap.ready] == ["checker"] and not snap.completed
    done = e.complete(snap.state, "review", {"decision": "reject", "reason": "x"})
    assert done.completed and done.outcome == {"decision": "reject", "reason": "x"} and done.ready == []
    with pytest.raises(ValueError):
        e.complete(done.state, "review", {"decision": "approve"})
    with pytest.raises(ValueError):
        e.validate_definition("<bpmn/>")


# --------------------------------------------------------------------------- lifecycle


def test_upload_starts_a_workflow_with_a_checker_task(client, login):
    doc_id = _upload(client, login("risk.maker"))
    runs = client.get(f"/api/workflow/subjects/document/{doc_id}/instances", headers=login("risk.maker")).json()
    assert len(runs) == 1
    run = runs[0]
    assert run["workflow"] == "document_approval@v1" and run["engine"] == "builtin.single_review"
    assert run["status"] == "running"
    assert [(t["name"], t["lane"], t["status"]) for t in run["tasks"]] == [("review", "checker", "ready")]


def test_checker_inbox_is_scoped_to_their_department(client, login):
    doc_id = _upload(client, login("risk.maker"))
    risk = client.get("/api/workflow/tasks", headers=login("risk.checker")).json()
    assert str(doc_id) in {t["subject_id"] for t in risk}
    mine = next(t for t in risk if t["subject_id"] == str(doc_id))
    assert mine["subject"]["title"] == "memo.pdf" and mine["subject"]["knowledge_base"]["id"] == "credit-risk"
    # seeded pending Risk document is there too; HR's is not
    assert {t["subject"]["knowledge_base"]["id"] for t in risk} == {"credit-risk"}
    hr = client.get("/api/workflow/tasks", headers=login("hr.checker")).json()
    assert {t["subject"]["knowledge_base"]["id"] for t in hr} == {"hr-policies"}
    for who in ("risk.maker", "analyst", "risk.admin", "admin"):
        assert client.get("/api/workflow/tasks", headers=login(who)).json() == [], who


def test_complete_through_generic_endpoint(client, login):
    doc_id = _upload(client, login("risk.maker"))
    h = login("risk.checker")
    task = next(t for t in client.get("/api/workflow/tasks", headers=h).json() if t["subject_id"] == str(doc_id))
    r = client.post(f"/api/workflow/tasks/{task['id']}/complete",
                    json={"data": {"decision": "reject", "reason": "Wrong template"}}, headers=h)
    assert r.status_code == 200
    run = r.json()
    assert run["status"] == "completed" and run["outcome"] == {"decision": "reject", "reason": "Wrong template"}
    assert run["tasks"][0]["completed_by"] == "risk.checker"
    docs = {d["id"]: d for d in client.get("/api/knowledge-bases/credit-risk/documents", headers=h).json()}
    assert docs[doc_id]["status"] == "rejected" and docs[doc_id]["rejection_reason"] == "Wrong template"
    # completing again is refused
    again = client.post(f"/api/workflow/tasks/{task['id']}/complete", json={"data": {"decision": "approve"}}, headers=h)
    assert again.status_code == 409


def test_generic_endpoint_enforces_document_rules(client, login):
    doc_id = _upload(client, login("risk.maker"))
    task = next(t for t in client.get("/api/workflow/tasks", headers=login("risk.checker")).json()
                if t["subject_id"] == str(doc_id))
    body = {"data": {"decision": "approve"}}
    assert client.post(f"/api/workflow/tasks/{task['id']}/complete", json=body, headers=login("hr.checker")).status_code == 404
    assert client.post(f"/api/workflow/tasks/{task['id']}/complete", json=body, headers=login("risk.maker")).status_code == 403
    # can see the KB (as its admin) but isn't a checker
    assert client.post(f"/api/workflow/tasks/{task['id']}/complete", json=body, headers=login("risk.admin")).status_code == 403
    bad = client.post(f"/api/workflow/tasks/{task['id']}/complete", json={"data": {"decision": "maybe"}},
                      headers=login("risk.checker"))
    assert bad.status_code == 422


def test_approve_shortcut_completes_the_workflow(client, login):
    doc_id = _upload(client, login("risk.maker"))
    client.post(f"/api/documents/{doc_id}/approve", json={}, headers=login("risk.checker"))
    run = client.get(f"/api/workflow/subjects/document/{doc_id}/instances", headers=login("risk.checker")).json()[0]
    assert run["status"] == "completed" and run["outcome"]["decision"] == "approve"


def test_seeded_decisions_have_history(client, login):
    docs = client.get("/api/knowledge-bases/credit-risk/documents", headers=login("risk.checker")).json()
    rejected = next(d for d in docs if d["status"] == "rejected")
    run = client.get(f"/api/workflow/subjects/document/{rejected['id']}/instances", headers=login("risk.checker")).json()[0]
    assert run["outcome"]["reason"] == rejected["rejection_reason"]
    assert run["tasks"][0]["completed_by"] == "risk.checker"


def test_history_follows_document_visibility(client, login):
    doc_id = _upload(client, login("risk.maker"))
    path = f"/api/workflow/subjects/document/{doc_id}/instances"
    assert client.get(path, headers=login("analyst")).status_code == 404  # pending: viewers can't see it
    assert client.get(path, headers=login("comp.officer")).status_code == 404
    assert client.get(path, headers=login("risk.admin")).status_code == 404


def test_upload_and_workflow_share_a_transaction(client, login, monkeypatch):
    """If the workflow can't start, the upload is rolled back too."""
    from app.services import document_approval

    def boom(*a, **k):
        raise RuntimeError("engine down")

    monkeypatch.setattr(document_approval, "start_for", boom)
    h = login("risk.maker")
    before = len(client.get("/api/knowledge-bases/credit-risk/documents", headers=h).json())
    with pytest.raises(RuntimeError):
        client.post("/api/knowledge-bases/credit-risk/documents",
                    files=[("files", ("x.pdf", PDF, "application/pdf"))], headers=h)
    assert len(client.get("/api/knowledge-bases/credit-risk/documents", headers=h).json()) == before


def test_definitions_are_system_admin_only(client, login):
    defs = client.get("/api/workflow/definitions", headers=login("admin")).json()
    assert [(d["key"], d["version"], d["engine"], d["is_active"]) for d in defs] == [
        ("document_approval", 1, "builtin.single_review", True)
    ]
    assert client.get("/api/workflow/definitions", headers=login("risk.admin")).status_code == 403


def test_running_instances_keep_their_definition_version(client, login):
    """Activating a new version affects new uploads only."""
    from app.db.session import new_session
    from app.workflow.models import WorkflowDefinition

    old_doc = _upload(client, login("risk.maker"), name="old.pdf")
    with new_session() as db:
        v1 = db.query(WorkflowDefinition).filter_by(key="document_approval", version=1).one()
        v1.is_active = False
        db.flush()
        db.add(WorkflowDefinition(key="document_approval", version=2, engine="builtin.single_review",
                                  name="Document approval", is_active=True))
        db.commit()
    new_doc = _upload(client, login("risk.maker"), name="new.pdf")
    h = login("risk.checker")
    runs = {d: client.get(f"/api/workflow/subjects/document/{d}/instances", headers=h).json()[0]["workflow"]
            for d in (old_doc, new_doc)}
    assert runs == {old_doc: "document_approval@v1", new_doc: "document_approval@v2"}
    # the old one still completes on its own version
    assert client.post(f"/api/documents/{old_doc}/approve", json={}, headers=h).status_code == 200


def test_backfill_starts_workflows_for_old_pending_documents(client, login):
    from sqlalchemy import delete

    from app.db.session import new_session
    from app.services import document_approval
    from app.workflow.models import WorkflowInstance

    with new_session() as db:  # simulate data from before the workflow module
        db.execute(delete(WorkflowInstance))
        db.commit()
        assert document_approval.backfill(db) == 2  # the two seeded pending documents
        db.commit()
        assert document_approval.backfill(db) == 0  # idempotent
    assert len(client.get("/api/workflow/tasks", headers=login("risk.checker")).json()) == 1


def test_task_data_is_recorded(client, login):
    from app.db.session import new_session
    from app.workflow.models import WorkflowTask

    doc_id = _upload(client, login("risk.maker"))
    client.post(f"/api/documents/{doc_id}/reject", json={"reason": "Needs a cover page"}, headers=login("risk.checker"))
    with new_session() as db:
        t = db.query(WorkflowTask).order_by(WorkflowTask.id.desc()).first()
        assert json.loads(t.data) == {"decision": "reject", "reason": "Needs a cover page"}
