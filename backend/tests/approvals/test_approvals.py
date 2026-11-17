"""Approvals (CAMS): submit, inbox, approve / reject / request changes, rounds, history, withdrawal."""

import pytest

from app.approvals import service as approvals
from app.db.session import new_session
from tests.helpers import set_roles

PDF = b"%PDF-1.4 demo"


def submit(client, hub, names=("policy.pdf",), who="marcus"):
    ids = [d["id"] for d in client.post(
        f"/api/doc-repos/{hub['repo']}/documents", headers=hub[who],
        files=[("files", (n, PDF, "application/pdf")) for n in names]).json()]
    r = client.post(f"/api/doc-repos/{hub['repo']}/documents/submit", json={"ids": ids}, headers=hub[who])
    assert r.status_code == 200 and r.json()["skipped"] == [], r.text
    return ids


def inbox(client, hub, who):
    return client.get("/api/approvals", headers=hub[who]).json()


def opened(client, hub, who, task):
    r = client.get(f"/api/approvals/{task}", headers=hub[who])
    assert r.status_code == 200, r.text
    return r.json()


def decide(client, hub, who, task, decision, comment=""):
    return client.post(f"/api/approvals/{task}/decision", json={"decision": decision, "comment": comment},
                       headers=hub[who])


def doc(client, hub, doc_id, who="marcus"):
    return client.get(f"/api/doc-repos/{hub['repo']}/documents/{doc_id}", headers=hub[who]).json()


def test_submitting_puts_the_document_in_the_repository_checkers_inbox(client, hub):
    submit(client, hub)
    items = inbox(client, hub, "cara")
    assert len(items) == 1 and items[0]["title"] == "policy.pdf" and items[0]["kind_label"] == "Document"
    assert items[0]["round"] == 1 and items[0]["requested_by"]["lan_id"] == "marcus"
    assert items[0]["resource_name"] == "Loan Risks"
    m = items[0]["metadata"]  # the list comes from the task's metadata only
    assert m["type"] == "DOCUMENT_UPLOAD" and m["subject"]["type"] == "DOCUMENT" and m["document"]["folder"] == ""
    assert m["document"]["uploaded_by"]["lan_id"] == "marcus" and m["submitted_by"]["lan_id"] == "marcus"
    assert "summary" not in items[0]
    s = opened(client, hub, "cara", items[0]["id"])["summary"]  # the summary comes when it's opened
    assert s["subtitle"] == "Loan Risks" and s["download"]["href"].endswith("/download")
    assert s["sections"][0]["items"][0] == {"label": "Department", "value": "Risk Management", "note": ""}
    assert inbox(client, hub, "chris") == items  # every checker of the repository
    for who in ("marcus", "eve", "dana", "ben", "outsider"):
        assert inbox(client, hub, who) == []


def test_checkers_of_another_repository_see_nothing(client, hub):
    other = client.post("/api/doc-repos", json={"name": "Other"}, headers=hub["andy"]).json()
    set_roles(client, other['id'], "outsider", ["CHECKER"], hub["andy"])
    submit(client, hub)
    assert inbox(client, hub, "outsider") == []
    assert client.get("/api/me/access", headers=hub["outsider"]).json()["can_decide"] is True


def test_approve_locks_the_document_and_its_metadata(client, hub):
    [doc_id] = submit(client, hub)
    task = inbox(client, hub, "cara")[0]["id"]
    assert decide(client, hub, "cara", task, "approve").status_code == 204
    d = doc(client, hub, doc_id)
    assert d["status"] == "approved" and d["last_decision"]["decided_by"]["lan_id"] == "cara"
    assert d["actions"] == {"edit": False, "submit": False, "delete": False, "discard": False, "versions": True}
    assert client.get(f"/api/doc-repos/{hub['repo']}/documents/{doc_id}", headers=hub["eve"]).status_code == 200
    # the repository's values change; the approved document keeps what was checked
    client.put(f"/api/doc-repos/{hub['repo']}/metadata", json=[{"label": "Country", "value": "Japan"}], headers=hub["ben"])
    assert {m["label"]: m["value"] for m in doc(client, hub, doc_id)["metadata"]} == {
        "Department": "Risk Management", "Country": "Singapore"}
    r = client.put(f"/api/doc-repos/{hub['repo']}/documents/{doc_id}/metadata", json={"own": []}, headers=hub["marcus"])
    assert r.status_code == 409
    assert inbox(client, hub, "cara") == [] and inbox(client, hub, "chris") == []


@pytest.mark.parametrize("decision", ["reject", "request_changes"])
def test_reject_and_request_changes_need_a_reason(client, hub, decision):
    submit(client, hub)
    task = inbox(client, hub, "cara")[0]["id"]
    assert decide(client, hub, "cara", task, decision, "  ").status_code == 422
    assert decide(client, hub, "cara", task, "maybe").status_code == 422


def test_rejected_goes_back_and_resubmitting_is_a_new_request(client, hub):
    [doc_id] = submit(client, hub)
    decide(client, hub, "cara", inbox(client, hub, "cara")[0]["id"], "reject", "Wrong template")
    d = doc(client, hub, doc_id)
    assert d["status"] == "rejected" and d["last_decision"]["comment"] == "Wrong template"
    client.post(f"/api/doc-repos/{hub['repo']}/documents/submit", json={"ids": [doc_id]}, headers=hub["marcus"])
    assert inbox(client, hub, "cara")[0]["round"] == 1
    history = client.get(f"/api/doc-repos/{hub['repo']}/documents/{doc_id}/history", headers=hub["marcus"]).json()
    assert [(h["reference"].split(":")[-1], h["status"]) for h in history] == [("2", "PENDING"), ("1", "REJECTED")]


def test_changes_requested_continue_the_same_request_in_a_new_round(client, hub):
    [doc_id] = submit(client, hub)
    first = opened(client, hub, "cara", inbox(client, hub, "cara")[0]["id"])
    decide(client, hub, "cara", first["id"], "request_changes", "Add the effective date")
    d = doc(client, hub, doc_id)
    assert d["status"] == "changes_requested" and d["actions"]["edit"] is True
    assert d["last_decision"]["decision"] == "CHANGES_REQUESTED"
    client.put(f"/api/doc-repos/{hub['repo']}/documents/{doc_id}/metadata",
               json={"own": [{"label": "Effective", "value": "2027-01-01"}]}, headers=hub["marcus"])
    client.post(f"/api/doc-repos/{hub['repo']}/documents/submit", json={"ids": [doc_id]}, headers=hub["marcus"])
    second = inbox(client, hub, "cara")[0]
    second = opened(client, hub, "cara", second["id"])
    assert second["request_id"] == first["request_id"] and second["round"] == 2
    assert any(i["label"] == "Effective" for s in second["summary"]["sections"] for i in s["items"])
    assert decide(client, hub, "cara", second["id"], "approve").status_code == 204  # the same checker again
    [h] = client.get(f"/api/doc-repos/{hub['repo']}/documents/{doc_id}/history", headers=hub["eve"]).json()
    assert h["status"] == "APPROVED" and [(r["round"], r["outcome"]) for r in h["rounds"]] == [
        (1, "CHANGES_REQUESTED"), (2, "APPROVED")]


def test_each_round_records_what_was_reviewed(client, hub):
    [doc_id] = submit(client, hub)
    with new_session() as db:
        [h] = approvals.history(db, "DOCUMENT", doc_id)
        snap = h.rounds[0][0].subject_snapshot
    assert snap["filename"] == "policy.pdf" and len(snap["content_hash"]) == 64
    assert {m["label"]: m["value"] for m in snap["metadata"]} == {"Department": "Risk Management", "Country": "Singapore"}


def test_a_task_is_decided_once(client, hub):
    submit(client, hub)
    task = inbox(client, hub, "cara")[0]["id"]
    assert decide(client, hub, "chris", task, "approve").status_code == 204
    assert decide(client, hub, "cara", task, "reject", "late").status_code == 404


def test_a_checker_never_sees_their_own_submission(client, hub):
    set_roles(client, hub['repo'], "cara", ["MAKER"], hub["ben"])
    submit(client, hub, who="cara")
    set_roles(client, hub['repo'], "cara", ["CHECKER"], hub["ben"])
    assert inbox(client, hub, "cara") == [] and len(inbox(client, hub, "chris")) == 1


def test_removing_the_checker_role_empties_the_inbox_at_once(client, hub):
    submit(client, hub)
    task = inbox(client, hub, "cara")[0]["id"]
    set_roles(client, hub['repo'], "cara", ["VIEWER"], hub["ben"])
    assert inbox(client, hub, "cara") == []
    assert decide(client, hub, "cara", task, "approve").status_code == 404


def test_submitting_twice_is_refused(client, hub):
    [doc_id] = submit(client, hub)
    r = client.post(f"/api/doc-repos/{hub['repo']}/documents/submit", json={"ids": [doc_id]}, headers=hub["marcus"])
    assert r.status_code == 409 and "policy.pdf is now pending approval" in r.json()["detail"]


def test_deleting_a_document_withdraws_its_request(client, hub):
    [doc_id] = submit(client, hub)
    decide(client, hub, "cara", inbox(client, hub, "cara")[0]["id"], "request_changes", "Fix it")
    client.post(f"/api/doc-repos/{hub['repo']}/documents/delete", json={"ids": [doc_id]}, headers=hub["marcus"])
    with new_session() as db:
        assert approvals.history(db, "DOCUMENT", doc_id)[0].request.status == "CANCELLED"


def test_deleting_the_repository_withdraws_its_requests(client, hub):
    submit(client, hub, ("a.pdf", "b.pdf"))
    assert len(inbox(client, hub, "cara")) == 2
    client.delete(f"/api/doc-repos/{hub['repo']}", headers=hub["ben"])
    assert inbox(client, hub, "cara") == []
    client.post(f"/api/doc-repos/{hub['repo']}/restore", headers=hub["admin"])
    assert {d["status"] for d in client.get(f"/api/doc-repos/{hub['repo']}/documents", headers=hub["marcus"]).json()} == {"draft"}


def test_the_inbox_is_oldest_first(client, hub):
    submit(client, hub, ("first.pdf",))
    submit(client, hub, ("second.pdf",), who="mia")
    assert [i["title"] for i in inbox(client, hub, "cara")] == ["first.pdf", "second.pdf"]


def test_auditors_see_every_status_and_the_history_but_cannot_act(client, hub):
    client.post("/api/default-grants", json={"team": "AUDIT", "role": "AUDITOR"}, headers=hub["admin"])
    [doc_id] = submit(client, hub)
    client.post(f"/api/doc-repos/{hub['repo']}/documents", headers=hub["marcus"],
                files=[("files", ("draft.pdf", PDF, "application/pdf"))])
    seen = {d["filename"]: d["status"] for d in client.get(f"/api/doc-repos/{hub['repo']}/documents", headers=hub["ivan"]).json()}
    assert seen == {"policy.pdf": "pending_approval", "draft.pdf": "draft"}
    assert client.get(f"/api/doc-repos/{hub['repo']}/documents/{doc_id}/history", headers=hub["ivan"]).status_code == 200
    assert inbox(client, hub, "ivan") == []
    assert client.get("/api/me/access", headers=hub["ivan"]).json()["can_decide"] is False


def _maker_and_checker(client, hub, *people):
    """Put these people in the Makers group as makers and the Checkers group as checkers."""
    url = f"/api/doc-repos/{hub['repo']}"
    groups = {g["name"]: g["id"] for g in client.get(f"{url}/groups", headers=hub["ben"]).json()["groups"]}
    for who in people:
        r = client.put(f"{url}/members/{who}", json={"groups": [{"id": groups["Makers"], "roles": ["MAKER"]},
                                                                {"id": groups["Checkers"], "roles": ["CHECKER"]}]},
                       headers=hub["ben"])
        assert r.status_code == 200, r.text


def test_the_maker_never_approves_their_document_even_when_someone_else_submits_it(client, hub):
    _maker_and_checker(client, hub, "marcus")
    [doc_id] = [d["id"] for d in client.post(
        f"/api/doc-repos/{hub['repo']}/documents", headers=hub["marcus"],
        files=[("files", ("mine.pdf", PDF, "application/pdf"))]).json()]
    r = client.post(f"/api/doc-repos/{hub['repo']}/documents/submit", json={"ids": [doc_id]}, headers=hub["mia"])
    assert r.status_code == 200 and r.json()["skipped"] == []
    task = inbox(client, hub, "cara")[0]["id"]
    assert inbox(client, hub, "marcus") == []
    assert decide(client, hub, "marcus", task, "approve").status_code == 404
    assert decide(client, hub, "cara", task, "approve").status_code == 204


def test_whoever_resubmits_never_decides_the_next_round(client, hub):
    [doc_id] = submit(client, hub)
    task = inbox(client, hub, "cara")[0]["id"]
    assert decide(client, hub, "cara", task, "request_changes", "Fix the title").status_code == 204
    _maker_and_checker(client, hub, "mia")
    r = client.post(f"/api/doc-repos/{hub['repo']}/documents/submit", json={"ids": [doc_id]}, headers=hub["mia"])
    assert r.status_code == 200 and r.json()["skipped"] == []
    assert inbox(client, hub, "mia") == [] and len(inbox(client, hub, "chris")) == 1


def _groups(client, hub):
    url = f"/api/doc-repos/{hub['repo']}/groups"
    return {g["name"]: g["id"] for g in client.get(url, headers=hub["ben"]).json()["groups"]}


def test_someone_made_a_checker_after_submission_gets_the_waiting_task(client, hub):
    submit(client, hub)
    assert inbox(client, hub, "eve") == []
    url = f"/api/doc-repos/{hub['repo']}"
    client.put(f"{url}/members/eve", json={"groups": [{"id": _groups(client, hub)["Checkers"], "roles": ["CHECKER"]}]},
               headers=hub["ben"])
    assert len(inbox(client, hub, "eve")) == 1


def test_losing_the_checker_role_in_the_group_empties_that_persons_inbox(client, hub):
    submit(client, hub)
    checkers = _groups(client, hub)["Checkers"]
    url = f"/api/doc-repos/{hub['repo']}/members/cara"
    client.put(url, json={"groups": [{"id": checkers, "roles": ["VIEWER"]}]}, headers=hub["ben"])
    assert inbox(client, hub, "cara") == [] and len(inbox(client, hub, "chris")) == 1
    client.put(url, json={"groups": [{"id": checkers, "roles": ["CHECKER"]}]}, headers=hub["ben"])
    assert len(inbox(client, hub, "cara")) == 1


def test_a_decided_task_leaves_every_inbox(client, hub):
    submit(client, hub)
    task = inbox(client, hub, "cara")[0]["id"]
    assert decide(client, hub, "chris", task, "approve").status_code == 204
    assert inbox(client, hub, "cara") == [] and inbox(client, hub, "chris") == []


def test_switching_a_checker_off_and_on_moves_their_assignments(client, hub):
    from sqlalchemy import select

    from app.approvals.models import ApprovalTaskAssignee
    from app.db.session import new_session

    submit(client, hub)
    def active_rows():
        with new_session() as db:
            return len(db.scalars(select(ApprovalTaskAssignee).where(ApprovalTaskAssignee.status == "ACTIVE")).all())
    assert active_rows() == 2  # cara and chris
    assert client.post("/api/users/cara/active", json={"active": False}, headers=hub["admin"]).status_code == 200
    assert active_rows() == 1
    assert client.post("/api/users/cara/active", json={"active": True}, headers=hub["admin"]).status_code == 200
    assert active_rows() == 2
