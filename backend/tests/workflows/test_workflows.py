"""Standalone workflows: the engine on its own, Doc Hub's default flow, and each repository's choice."""

import copy
import uuid

import pytest
from sqlalchemy import select

from app.core.errors import InvalidRequest
from app.db.session import new_session
from app.documents.workflow_steps import DEFAULT_WORKFLOW
from app.workflows import engine, flow
from app.workflows.models import StepInstance, WorkflowInstance
from tests.approvals.test_approvals import PDF, decide, doc, inbox
from tests.helpers import GROUPS_FLOW, use_workflow

# ----------------------------------------------------------------------------- the engine on its own

ended: list[tuple[str, str]] = []
flow.register_step_type(flow.StepType(
    code="TEST_COIN", kind="TEST.THING", kind_label="Thing", outcomes=("HEADS", "TAILS"),
    enter=lambda db, ctx: ctx.data.get("toss") if not ctx.reentry else None,
    signal=lambda db, ctx: ctx.data.get("toss")))
engine.on_end("TEST_SUBJECT", lambda db, inst, outcome, actor, data: ended.append((inst.subject_id, outcome)))
COIN = {"code": "TEST.COIN", "start": "toss", "steps": [
    {"id": "toss", "type": "TEST_COIN", "name": "Toss", "on": {"HEADS": "END:WON", "TAILS": "toss"}}]}


def test_the_engine_runs_any_flow_for_any_subject_without_approvals(client):  # client: a fresh database
    with new_session() as db:
        wf = engine.ensure_definition(db, COIN)
        node = uuid.uuid4()
        engine.bind(db, node, wf.id)
        inst = engine.start(db, node, "TEST.THING", "TEST_SUBJECT", "s-1", None, {"toss": "TAILS"})
        assert inst.status == "RUNNING" and inst.round == 2 and inst.current_step == "toss"  # back to itself: round 2
        engine.signal(db, inst, None, {"toss": "HEADS"})
        assert inst.status == "COMPLETED" and inst.outcome == "WON" and ended[-1] == ("s-1", "WON")
        steps = db.scalars(select(StepInstance).where(StepInstance.workflow_instance_id == inst.id)
                           .order_by(StepInstance.round)).all()
        assert [(s.round, s.outcome) for s in steps] == [(1, "TAILS"), (2, "HEADS")]
        db.rollback()


@pytest.mark.parametrize("change, message", [
    (lambda f: f.update(start="nowhere"), "isn't a step"),
    (lambda f: f["steps"][1]["on"].update(APPROVED="nowhere"), "isn't a step or END"),
    (lambda f: f["steps"][1].update(type="NO_SUCH_TYPE"), "no step type"),
    (lambda f: f["steps"][1]["on"].pop("REJECTED"), '"on" needs exactly'),
    (lambda f: f["steps"][1]["role"].update(role="BOSS"), "unknown role"),
    (lambda f: f["steps"][0].pop("role"), 'needs "role"'),
])
def test_invalid_flows_are_refused(change, message):
    definition = copy.deepcopy(DEFAULT_WORKFLOW)
    change(definition)
    with pytest.raises(InvalidRequest, match=message):
        flow.parse(definition)


# ----------------------------------------------------------------------------- Doc Hub: the default flow


def _new_repo(client, hub, name="Other"):
    repo = client.post("/api/doc-repos", json={"name": name}, headers=hub["andy"]).json()
    return repo["id"]


def _groups(client, hub, repo, who="andy"):
    return {g["name"]: g["id"] for g in client.get(f"/api/doc-repos/{repo}/groups", headers=hub[who]).json()["groups"]}


def _upload_and_submit(client, hub, repo, who="marcus", name="p.pdf"):
    [doc_id] = [d["id"] for d in client.post(f"/api/doc-repos/{repo}/documents", headers=hub[who],
                                             files=[("files", (name, PDF, "application/pdf"))]).json()]
    r = client.post(f"/api/doc-repos/{repo}/documents/submit", json={"ids": [doc_id]}, headers=hub[who])
    return doc_id, r.json()


def test_a_new_repository_uses_the_default_flow_which_names_a_default_group(client, hub):
    repo = _new_repo(client, hub)
    w = client.get(f"/api/doc-repos/{repo}/workflow", headers=hub["andy"]).json()
    assert w["current"]["code"] == "DOC_HUB.DOCUMENT_APPROVAL" and w["current"]["version"] == 1
    assert [(s["id"], s["type"], s["user_group"], s["role"]) for s in w["current"]["steps"]] == [
        ("maker_upload", "DOCUMENT_UPLOAD", "default", "MAKER"), ("checker_review", "DOCUMENT_REVIEW", "default", "CHECKER")]
    assert w["missing_groups"] == ["default"]
    assert {o["code"] for o in w["options"]} == {"DOC_HUB.DOCUMENT_APPROVAL", "TEST.MAKERS_AND_CHECKERS"}


def test_without_a_default_group_the_maker_is_refused(client, hub):
    repo = _new_repo(client, hub)
    url = f"/api/doc-repos/{repo}"
    makers = client.post(f"{url}/groups", json={"name": "Makers"}, headers=hub["andy"]).json()
    client.put(f"{url}/members/marcus", json={"groups": [{"id": makers["id"], "roles": ["MAKER"]}]}, headers=hub["andy"])
    doc_id, result = _upload_and_submit(client, hub, repo)
    assert result["done"] == [] and "no user group named default" in result["skipped"][0]["reason"]


def test_the_default_flow_with_a_default_group(client, hub):
    repo = _new_repo(client, hub)
    url = f"/api/doc-repos/{repo}"
    default = client.post(f"{url}/groups", json={"name": "default"}, headers=hub["andy"]).json()
    for who, role in (("marcus", "MAKER"), ("cara", "CHECKER")):  # one group, each with their own role
        client.put(f"{url}/members/{who}", json={"groups": [{"id": default["id"], "roles": [role]}]}, headers=hub["andy"])
    assert client.get(f"{url}/workflow", headers=hub["andy"]).json()["missing_groups"] == []
    doc_id, result = _upload_and_submit(client, hub, repo)
    assert result["skipped"] == []
    assert inbox(client, hub, "marcus") == []  # never their own
    [task] = [i for i in inbox(client, hub, "cara") if i["title"] == "p.pdf"]
    assert task["metadata"]["step"] == {"id": "checker_review", "name": "Checker review"}
    assert decide(client, hub, "cara", task["id"], "approve").status_code == 204
    r = client.get(f"{url}/documents/{doc_id}", headers=hub["marcus"]).json()
    assert r["status"] == "approved"


def _steps(doc_id):
    with new_session() as db:
        from app.approvals.models import ApprovalRequest
        req = db.scalars(select(ApprovalRequest).where(ApprovalRequest.subject_id == doc_id)).first()
        inst = db.get(WorkflowInstance, req.workflow_instance_id)
        rows = db.scalars(select(StepInstance).where(StepInstance.workflow_instance_id == inst.id)
                          .order_by(StepInstance.started_at)).all()
        return [(s.round, s.step_id, s.status, s.outcome) for s in rows], inst


def test_changes_requested_go_back_to_the_maker_step_and_resubmitting_runs_it_again(client, hub):
    [doc_id] = [d["id"] for d in client.post(f"/api/doc-repos/{hub['repo']}/documents", headers=hub["marcus"],
                                             files=[("files", ("c.pdf", PDF, "application/pdf"))]).json()]
    submit = lambda: client.post(f"/api/doc-repos/{hub['repo']}/documents/submit", json={"ids": [doc_id]},
                                 headers=hub["marcus"])
    submit()
    task = inbox(client, hub, "cara")[0]["id"]
    assert decide(client, hub, "cara", task, "request_changes", "Add a date").status_code == 204
    steps, inst = _steps(doc_id)
    assert steps == [(1, "maker_upload", "COMPLETED", "PASSED"), (1, "checker_review", "COMPLETED", "CHANGES_REQUESTED"),
                     (2, "maker_upload", "ACTIVE", None)]
    assert doc(client, hub, doc_id)["status"] == "changes_requested"
    assert submit().json()["skipped"] == []
    steps, inst = _steps(doc_id)
    assert steps[-2:] == [(2, "maker_upload", "COMPLETED", "PASSED"), (2, "checker_review", "ACTIVE", None)]
    assert inbox(client, hub, "cara")[0]["metadata"]["round"] == 2


def test_owners_and_admins_choose_the_workflow_and_running_requests_keep_theirs(client, hub):
    two_step = copy.deepcopy(GROUPS_FLOW) | {"code": "TEST.TWO_STEP", "name": "Checkers then admins"}
    two_step["steps"][1]["on"]["APPROVED"] = "admin_review"
    two_step["steps"].append({"id": "admin_review", "type": "DOCUMENT_REVIEW", "name": "Admin sign-off",
                              "role": {"user_group": "Admins", "role": "ADMIN"},
                              "on": {"APPROVED": "END:APPROVED", "REJECTED": "END:REJECTED",
                                     "CHANGES_REQUESTED": "maker_upload"}})
    [old_doc] = [d["id"] for d in client.post(f"/api/doc-repos/{hub['repo']}/documents", headers=hub["marcus"],
                                              files=[("files", ("old.pdf", PDF, "application/pdf"))]).json()]
    client.post(f"/api/doc-repos/{hub['repo']}/documents/submit", json={"ids": [old_doc]}, headers=hub["marcus"])
    assert client.put(f"/api/doc-repos/{hub['repo']}/workflow", json={"workflow_id": str(uuid.uuid4())},
                      headers=hub["marcus"]).status_code == 403
    use_workflow(client, hub["repo"], two_step, hub["admin"], hub["dana"])  # dana: a repository admin
    [new_doc] = [d["id"] for d in client.post(f"/api/doc-repos/{hub['repo']}/documents", headers=hub["marcus"],
                                              files=[("files", ("new.pdf", PDF, "application/pdf"))]).json()]
    client.post(f"/api/doc-repos/{hub['repo']}/documents/submit", json={"ids": [new_doc]}, headers=hub["marcus"])
    new_task = [i for i in inbox(client, hub, "cara") if i["title"] == "new.pdf"][0]
    assert decide(client, hub, "cara", new_task["id"], "approve").status_code == 204
    assert doc(client, hub, new_doc)["status"] == "pending_approval"
    [admin_task] = inbox(client, hub, "dana")
    assert admin_task["metadata"]["step"]["id"] == "admin_review"
    assert decide(client, hub, "dana", admin_task["id"], "approve").status_code == 204
    assert doc(client, hub, new_doc)["status"] == "approved"
    old_task = [i for i in inbox(client, hub, "cara") if i["title"] == "old.pdf"][0]
    assert decide(client, hub, "cara", old_task["id"], "approve").status_code == 204  # still one review
    assert doc(client, hub, old_doc)["status"] == "approved"
    assert "REPO_WORKFLOW_SET" in [e["action"] for e in client.get("/api/audit", headers=hub["admin"]).json()["items"]]


def test_a_repository_only_takes_a_document_workflow(client, hub):
    with new_session() as db:
        engine.ensure_definition(db, COIN)
        db.commit()
    coin = next(w for w in client.get("/api/approval-workflows", headers=hub["admin"]).json() if w["code"] == "TEST.COIN")
    r = client.put(f"/api/doc-repos/{hub['repo']}/workflow", json={"workflow_id": coin["id"]}, headers=hub["ben"])
    assert r.status_code == 422


# ----------------------------------------------------------------------------- the API (platform admins)


def test_only_platform_admins_manage_workflows(client, hub):
    for who in ("ben", "dana", "cara"):
        assert client.get("/api/approval-workflows", headers=hub[who]).status_code == 403
        assert client.post("/api/approval-workflows", json={"definition": GROUPS_FLOW}, headers=hub[who]).status_code == 403
    items = {w["code"]: w for w in client.get("/api/approval-workflows", headers=hub["admin"]).json()}
    assert items["DOC_HUB.DOCUMENT_APPROVAL"]["kind_label"] == "Document"
    assert items["TEST.MAKERS_AND_CHECKERS"]["used_by"] == 1
    types = {t["code"]: t["outcomes"] for t in client.get("/api/approval-workflows/step-types", headers=hub["admin"]).json()}
    assert types["DOCUMENT_UPLOAD"] == ["PASSED", "FAILED"]


def test_admins_check_create_and_publish_flows(client, hub):
    admin = hub["admin"]
    bad = copy.deepcopy(DEFAULT_WORKFLOW) | {"start": "nowhere"}
    r = client.post("/api/approval-workflows/validate", json={"definition": bad}, headers=admin)
    assert r.status_code == 422 and "isn't a step" in r.text
    r = client.post("/api/approval-workflows/validate", json={"definition": GROUPS_FLOW}, headers=admin)
    assert r.json() == {"ok": True, "steps": 2, "start": "maker_upload", "kind": "DOC_HUB.DOCUMENT"}
    assert client.post("/api/approval-workflows", json={"definition": GROUPS_FLOW}, headers=admin).status_code == 409
    new = copy.deepcopy(GROUPS_FLOW) | {"code": "TEST.NEW", "name": "New one"}
    created = client.post("/api/approval-workflows", json={"definition": new}, headers=admin).json()
    assert created["latest_version"] == 1 and created["used_by"] == 0
    new["steps"][1]["name"] = "Checker sign-off"
    r = client.post(f"/api/approval-workflows/{created['id']}/versions", json={"definition": new}, headers=admin)
    assert r.status_code == 201 and r.json()["version"] == 2
    renamed = new | {"code": "TEST.OTHER"}
    assert client.post(f"/api/approval-workflows/{created['id']}/versions", json={"definition": renamed},
                       headers=admin).status_code == 422
    actions = [e["action"] for e in client.get("/api/audit", headers=admin).json()["items"]]
    assert {"WORKFLOW_CREATED", "WORKFLOW_PUBLISHED"} <= set(actions)
