PDF = b"%PDF-1.4 test"


def _upload(client, h, kb="credit-risk", files=(("stress-test.pdf", PDF),)):
    return client.post(
        f"/api/knowledge-bases/{kb}/documents",
        files=[("files", (name, data, "application/pdf")) for name, data in files],
        headers=h,
    )


def _statuses(client, h, kb="credit-risk"):
    r = client.get(f"/api/knowledge-bases/{kb}/documents", headers=h)
    return r.status_code, sorted({d["status"] for d in r.json()}) if r.status_code == 200 else None


def test_viewers_see_only_approved(client, login):
    assert _statuses(client, login("analyst")) == (200, ["approved"])
    assert _statuses(client, login("analyst"), "hr-policies") == (200, ["approved"])  # granted access


def test_makers_and_checkers_see_all_statuses_in_their_department(client, login):
    everything = ["approved", "pending_approval", "rejected"]
    assert _statuses(client, login("risk.maker")) == (200, everything)
    assert _statuses(client, login("risk.checker")) == (200, everything)


def test_admins_cannot_view_documents(client, login):
    assert _statuses(client, login("risk.admin"))[0] == 403
    assert _statuses(client, login("admin"))[0] == 403


def test_no_access_looks_like_not_found(client, login):
    assert _statuses(client, login("comp.officer"))[0] == 404


def test_maker_uploads_checker_approves(client, login):
    r = _upload(client, login("risk.maker"))
    assert r.status_code == 201
    doc = r.json()[0]
    assert doc["status"] == "pending_approval" and doc["filename"] == "stress-test.pdf"
    assert doc["title"] == "stress-test" and doc["size_bytes"] == len(PDF) and doc["has_file"]
    assert doc["maker"] == {"username": "risk.maker", "display_name": "Risk Maker"}
    r = client.post(f"/api/documents/{doc['id']}/approve", json={}, headers=login("risk.checker"))
    assert r.status_code == 200
    assert r.json()["status"] == "approved" and r.json()["checker"]["username"] == "risk.checker"


def test_upload_several_files_at_once(client, login):
    r = _upload(client, login("risk.maker"), files=(("a.pdf", PDF), ("b.txt", b"notes"), ("c.xlsx", b"xx")))
    assert r.status_code == 201 and [d["filename"] for d in r.json()] == ["a.pdf", "b.txt", "c.xlsx"]


def test_upload_rejects_bad_files_and_keeps_nothing(client, login):
    h = login("risk.maker")
    before = len(client.get("/api/knowledge-bases/credit-risk/documents", headers=h).json())
    r = _upload(client, h, files=(("ok.pdf", PDF), ("run.exe", b"MZ")))
    assert r.status_code == 422 and "not allowed" in r.json()["detail"]
    assert _upload(client, h, files=(("empty.pdf", b""),)).status_code == 422
    assert _upload(client, h, files=(("big.pdf", b"x" * (1024 * 1024 + 1)),)).status_code == 422
    assert len(client.get("/api/knowledge-bases/credit-risk/documents", headers=h).json()) == before


def test_upload_filename_is_sanitised(client, login):
    r = _upload(client, login("risk.maker"), files=(("../../etc/passwd.txt", b"x"),))
    assert r.json()[0]["filename"] == "passwd.txt"


def test_download_follows_visibility(client, login):
    doc_id = _upload(client, login("risk.maker")).json()[0]["id"]
    # pending: maker and checker can download; a viewer can't even see it
    r = client.get(f"/api/documents/{doc_id}/download", headers=login("risk.maker"))
    assert r.status_code == 200 and r.content == PDF
    assert 'filename="stress-test.pdf"' in r.headers["content-disposition"]
    assert client.get(f"/api/documents/{doc_id}/download", headers=login("analyst")).status_code == 404
    client.post(f"/api/documents/{doc_id}/approve", json={}, headers=login("risk.checker"))
    assert client.get(f"/api/documents/{doc_id}/download", headers=login("analyst")).status_code == 200
    # admins never; other departments without a grant: hidden
    assert client.get(f"/api/documents/{doc_id}/download", headers=login("risk.admin")).status_code == 403
    assert client.get(f"/api/documents/{doc_id}/download", headers=login("comp.officer")).status_code == 404


def test_seeded_documents_have_files(client, login):
    docs = client.get("/api/knowledge-bases/hr-policies/documents", headers=login("analyst")).json()
    r = client.get(f"/api/documents/{docs[0]['id']}/download", headers=login("analyst"))
    assert r.status_code == 200 and r.content.startswith(b"%PDF")


def test_kb_detail_reports_capabilities(client, login):
    caps = lambda who, kb="credit-risk": client.get(f"/api/knowledge-bases/{kb}", headers=login(who)).json()["capabilities"]  # noqa: E731
    assert caps("risk.maker") == {"view_documents": True, "view_unapproved": True, "upload": True, "review": False, "edit": False}
    assert caps("risk.checker") == {"view_documents": True, "view_unapproved": True, "upload": False, "review": True, "edit": False}
    assert caps("analyst") == {"view_documents": True, "view_unapproved": False, "upload": False, "review": False, "edit": False}
    assert caps("analyst", "hr-policies")["view_unapproved"] is False  # granted access: approved only
    assert caps("risk.admin") == {"view_documents": False, "view_unapproved": False, "upload": False, "review": False, "edit": True}


def test_only_makers_upload(client, login):
    for who in ("risk.checker", "analyst", "risk.admin", "admin", "hr.maker"):
        assert _upload(client, login(who)).status_code in (403, 404), who


def test_only_same_department_checker_approves(client, login):
    doc_id = _upload(client, login("risk.maker")).json()[0]["id"]
    for who in ("hr.checker", "risk.maker", "risk.admin", "admin", "analyst"):
        r = client.post(f"/api/documents/{doc_id}/approve", json={}, headers=login(who))
        assert r.status_code in (403, 404), who


def test_reject_needs_a_reason(client, login):
    doc_id = _upload(client, login("risk.maker")).json()[0]["id"]
    h = login("risk.checker")
    assert client.post(f"/api/documents/{doc_id}/reject", json={}, headers=h).status_code == 422
    r = client.post(f"/api/documents/{doc_id}/reject", json={"reason": "Wrong template"}, headers=h)
    assert r.json()["status"] == "rejected" and r.json()["rejection_reason"] == "Wrong template"
    assert client.post(f"/api/documents/{doc_id}/approve", json={}, headers=h).status_code == 409


def test_maker_who_moved_department_cannot_be_approved_by_old_checker(client, login):
    """The checker must share the maker's department, not just the KB's."""
    from app.db.models import Department, User
    from app.db.session import new_session

    doc_id = _upload(client, login("risk.maker")).json()[0]["id"]
    with new_session() as db:
        maker = db.query(User).filter_by(lan_id="risk.maker").one()
        maker.department_id = db.query(Department).filter_by(code="HR").one().id
        db.commit()
    r = client.post(f"/api/documents/{doc_id}/approve", json={}, headers=login("risk.checker"))
    assert r.status_code == 403


# --------------------------------------------------------------------------- activity


def _activity(client, h, kb="credit-risk"):
    r = client.get(f"/api/knowledge-bases/{kb}/activity", headers=h)
    return r.status_code, r.json()


def test_activity_shows_uploads_and_decisions_newest_first(client, login):
    doc_id = _upload(client, login("risk.maker"), files=(("q4-plan.pdf", PDF),)).json()[0]["id"]
    code, events = _activity(client, login("risk.checker"))
    assert code == 200
    newest = events[0]
    assert (newest["type"], newest["document"]["filename"], newest["document"]["status"]) == (
        "uploaded", "q4-plan.pdf", "pending_approval")
    assert newest["actor"]["username"] == "risk.maker"

    client.post(f"/api/documents/{doc_id}/reject", json={"reason": "Use the Q4 template"}, headers=login("risk.checker"))
    events = _activity(client, login("risk.checker"))[1]
    assert [(e["type"], e["document"]["filename"]) for e in events[:2]] == [
        ("rejected", "q4-plan.pdf"), ("uploaded", "q4-plan.pdf")]
    assert events[0]["actor"]["username"] == "risk.checker" and events[0]["reason"] == "Use the Q4 template"
    assert events[1]["document"]["status"] == "rejected"  # current status shown on older events too
    times = [e["at"] for e in events]
    assert times == sorted(times, reverse=True)


def test_seeded_activity(client, login):
    events = _activity(client, login("risk.checker"))[1]
    kinds = sorted((e["type"], e["document"]["filename"]) for e in events)
    assert kinds == [
        ("approved", "credit-policy-2026.pdf"), ("rejected", "model-validation.pdf"),
        ("uploaded", "credit-policy-2026.pdf"), ("uploaded", "model-validation.pdf"),
        ("uploaded", "risk-appetite-q3.pdf"),
    ]


def test_activity_follows_document_visibility(client, login):
    viewer = {e["document"]["filename"] for e in _activity(client, login("analyst"))[1]}
    assert viewer == {"credit-policy-2026.pdf"}  # approved only
    assert {e["document"]["filename"] for e in _activity(client, login("analyst"), "hr-policies")[1]} == {
        "employee-handbook.pdf"}  # granted access: approved only
    assert _activity(client, login("risk.admin"))[0] == 403
    assert _activity(client, login("comp.officer"))[0] == 404
