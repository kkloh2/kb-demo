"""Bulk submit (makers) and bulk decisions (checkers): all or none."""

from sqlalchemy import update

from app.approvals.models import ApprovalTask
from tests.approvals.test_approvals import PDF, decide, doc, inbox
from tests.helpers import GROUPS_FLOW, set_roles, use_workflow


def upload(client, hub, names, who="marcus", repo=None):
    return [d["id"] for d in client.post(
        f"/api/doc-repos/{repo or hub['repo']}/documents", headers=hub[who],
        files=[("files", (n, PDF, "application/pdf")) for n in names]).json()]


def submit(client, hub, ids, statuses=None, who="marcus", repo=None):
    body = {"ids": ids, **({"statuses": statuses} if statuses is not None else {})}
    return client.post(f"/api/doc-repos/{repo or hub['repo']}/documents/submit", json=body, headers=hub[who])


def decide_many(client, hub, who, task_ids, decision, comment=""):
    return client.post("/api/approvals/decisions", json={"task_ids": task_ids, "decision": decision, "comment": comment},
                       headers=hub[who])


def statuses(client, hub, ids, repo=None):
    return [client.get(f"/api/doc-repos/{repo or hub['repo']}/documents/{i}", headers=hub["marcus"]).json()["status"]
            for i in ids]


# --------------------------------------------------------------------------- makers


def test_a_maker_submits_several_documents_at_once(client, hub):
    ids = upload(client, hub, ["a.pdf", "b.pdf", "c.pdf"])
    r = submit(client, hub, ids, {i: "draft" for i in ids})
    assert r.status_code == 200, r.text
    assert [d["status"] for d in r.json()["done"]] == ["pending_approval"] * 3 and r.json()["skipped"] == []
    assert sorted(i["title"] for i in inbox(client, hub, "cara")) == ["a.pdf", "b.pdf", "c.pdf"]


def test_drafts_and_changes_requested_go_together(client, hub):
    [first] = upload(client, hub, ["first.pdf"])
    submit(client, hub, [first])
    decide(client, hub, "cara", inbox(client, hub, "cara")[0]["id"], "request_changes", "Add a date")
    [second] = upload(client, hub, ["second.pdf"])
    r = submit(client, hub, [first, second], {first: "changes_requested", second: "draft"})
    assert r.status_code == 200, r.text
    rounds = {i["title"]: i["round"] for i in inbox(client, hub, "cara")}
    assert rounds == {"first.pdf": 2, "second.pdf": 1}


def test_if_one_was_submitted_meanwhile_nothing_is_submitted(client, hub):
    ids = upload(client, hub, ["a.pdf", "b.pdf", "c.pdf"])
    seen = {i: "draft" for i in ids}
    assert submit(client, hub, [ids[1]], who="mia").status_code == 200  # another maker got there first
    r = submit(client, hub, ids, seen)
    assert r.status_code == 409 and "b.pdf is now pending approval" in r.json()["detail"]
    assert statuses(client, hub, ids) == ["draft", "pending_approval", "draft"]
    assert [i["title"] for i in inbox(client, hub, "cara")] == ["b.pdf"]


def test_a_status_that_changed_and_came_back_round_is_still_refused(client, hub):
    [d] = upload(client, hub, ["a.pdf"])
    r = submit(client, hub, [d], {d: "changes_requested"})  # what the maker saw is out of date
    assert r.status_code == 409 and statuses(client, hub, [d]) == ["draft"]


def test_if_one_was_deleted_meanwhile_nothing_is_submitted(client, hub):
    ids = upload(client, hub, ["a.pdf", "b.pdf"])
    client.post(f"/api/doc-repos/{hub['repo']}/documents/delete", json={"ids": [ids[0]]}, headers=hub["mia"])
    r = submit(client, hub, ids, {i: "draft" for i in ids})
    assert r.status_code == 409 and "a.pdf was deleted" in r.json()["detail"]
    assert statuses(client, hub, ids[1:]) == ["draft"] and inbox(client, hub, "cara") == []


def test_a_refusal_for_one_refuses_the_batch(client, hub, monkeypatch):
    from app.approvals import service as approvals
    ids = upload(client, hub, ["a.pdf", "b.pdf"])
    real = approvals.request_approval

    def refuse_b(db, type_code, **kw):
        if kw["title"] == "b.pdf":
            raise approvals.Refused("not today")
        return real(db, type_code, **kw)

    monkeypatch.setattr(approvals, "request_approval", refuse_b)
    r = submit(client, hub, ids)
    assert r.status_code == 409 and "b.pdf: not today" in r.json()["detail"]
    assert statuses(client, hub, ids) == ["draft", "draft"] and inbox(client, hub, "cara") == []


# --------------------------------------------------------------------------- checkers


def _second_repo(client, hub):
    r = client.post("/api/doc-repos", json={"name": "Treasury"}, headers=hub["ben"])
    assert r.status_code == 201, r.text
    repo = r.json()["id"]
    for n, roles in {"marcus": ["MAKER"], "cara": ["CHECKER"]}.items():
        assert set_roles(client, repo, n, roles, hub["ben"]).status_code == 200
    use_workflow(client, repo, GROUPS_FLOW, hub["admin"], hub["ben"])
    return repo


def test_a_checker_decides_items_from_several_repositories_at_once(client, hub):
    ids = upload(client, hub, ["a.pdf", "b.pdf"])
    submit(client, hub, ids)
    other = _second_repo(client, hub)
    [t] = upload(client, hub, ["t.pdf"], repo=other)
    assert submit(client, hub, [t], repo=other).status_code == 200
    tasks = [i["id"] for i in inbox(client, hub, "cara")]
    assert len(tasks) == 3
    r = decide_many(client, hub, "cara", tasks, "request_changes", "  Add the effective date  ")
    assert r.status_code == 200 and r.json() == {"decided": 3}, r.text
    assert statuses(client, hub, ids) == ["changes_requested"] * 2 and statuses(client, hub, [t], repo=other) == ["changes_requested"]
    for d in ids:  # the one comment, recorded on each
        assert doc(client, hub, d)["last_decision"]["comment"] == "Add the effective date"
    assert inbox(client, hub, "cara") == [] and inbox(client, hub, "chris") == []


def test_bulk_approve_needs_no_comment_but_reject_does(client, hub):
    ids = upload(client, hub, ["a.pdf", "b.pdf"])
    submit(client, hub, ids)
    tasks = [i["id"] for i in inbox(client, hub, "cara")]
    assert decide_many(client, hub, "cara", tasks, "reject").status_code == 422
    assert decide_many(client, hub, "cara", tasks, "approve").status_code == 200
    assert statuses(client, hub, ids) == ["approved", "approved"]


def test_if_one_was_decided_meanwhile_nothing_is_decided(client, hub):
    ids = upload(client, hub, ["a.pdf", "b.pdf"])
    submit(client, hub, ids)
    tasks = {i["title"]: i["id"] for i in inbox(client, hub, "cara")}
    assert decide(client, hub, "chris", tasks["b.pdf"], "approve").status_code == 204  # another checker
    r = decide_many(client, hub, "cara", list(tasks.values()), "reject", "Out of date")
    assert r.status_code == 409 and "b.pdf is no longer waiting for you" in r.json()["detail"]
    assert statuses(client, hub, ids) == ["pending_approval", "approved"]
    assert [i["title"] for i in inbox(client, hub, "cara")] == ["a.pdf"]


def test_a_task_decided_while_the_batch_runs_rolls_the_batch_back(client, hub, monkeypatch):
    from app.approvals import service as approvals
    ids = upload(client, hub, ["a.pdf", "b.pdf"])
    submit(client, hub, ids)
    tasks = {i["title"]: i["id"] for i in inbox(client, hub, "cara")}
    real = approvals._record_decision

    def race(db, user, item, decision, comment):
        if item.request.title == "b.pdf":  # another checker's decision lands after the checks (SQLite
            # allows one writer, so it's simulated in the batch's own transaction)
            db.execute(update(ApprovalTask).where(ApprovalTask.id == item.task.id).values(status="COMPLETED"))
        return real(db, user, item, decision, comment)

    monkeypatch.setattr(approvals, "_record_decision", race)
    r = decide_many(client, hub, "cara", [tasks["a.pdf"], tasks["b.pdf"]], "approve")
    assert r.status_code == 409 and "already decided b.pdf" in r.json()["detail"]
    assert statuses(client, hub, ids) == ["pending_approval", "pending_approval"]  # a.pdf rolled back too


def test_a_checker_cannot_bulk_decide_what_isnt_theirs(client, hub):
    ids = upload(client, hub, ["a.pdf"])
    submit(client, hub, ids)
    tasks = [i["id"] for i in inbox(client, hub, "cara")]
    assert decide_many(client, hub, "marcus", tasks, "approve").status_code == 409
    assert decide_many(client, hub, "eve", tasks, "approve").status_code == 409
    assert statuses(client, hub, ids) == ["pending_approval"]
