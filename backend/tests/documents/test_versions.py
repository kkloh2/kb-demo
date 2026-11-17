"""Document versions: uploading the same name to the same folder again."""

from tests.approvals.test_approvals import decide, inbox

V1, V2, V3 = b"%PDF-1.4 version one", b"%PDF-1.4 version two", b"%PDF-1.4 version three"


def upload(client, hub, data, name="policy.pdf", who="marcus", path=None, more=()):
    files = [("files", (name, data, "application/pdf"))] + [("files", (n, b, "application/pdf")) for n, b in more]
    body = {"paths": [path or name] + [n for n, _ in more]} if path or more else None
    return client.post(f"/api/doc-repos/{hub['repo']}/documents", headers=hub[who], files=files, data=body)


def url(hub, doc_id, rest=""):
    return f"/api/doc-repos/{hub['repo']}/documents/{doc_id}{rest}"


def get(client, hub, doc_id, who="marcus"):
    return client.get(url(hub, doc_id), headers=hub[who])


def download(client, hub, doc_id, who="marcus"):
    return client.get(url(hub, doc_id, "/download"), headers=hub[who]).content


def listed(client, hub, who):
    return client.get(f"/api/doc-repos/{hub['repo']}/documents", headers=hub[who]).json()


def submit(client, hub, doc_id, who="marcus"):
    r = client.post(f"/api/doc-repos/{hub['repo']}/documents/submit", json={"ids": [doc_id]}, headers=hub[who])
    assert r.status_code == 200, r.text


def decide_latest(client, hub, decision, comment=""):
    [task] = inbox(client, hub, "cara")
    assert decide(client, hub, "cara", task["id"], decision, comment).status_code == 204


def approved_v1(client, hub):
    [d] = upload(client, hub, V1).json()
    submit(client, hub, d["id"])
    decide_latest(client, hub, "approve")
    return d["id"]


def versions(client, hub, doc_id, who="marcus"):
    return client.get(url(hub, doc_id, "/versions"), headers=hub[who])


def meta(d):
    return {m["label"]: m["value"] for m in d["metadata"]}


# --------------------------------------------------------------------------- uploading again


def test_uploading_over_an_approved_document_adds_a_version(client, hub):
    doc_id = approved_v1(client, hub)
    [d] = upload(client, hub, V2).json()
    assert d["id"] == doc_id and d["version"] == 2 and d["status"] == "draft" and d["outcome"] == "version"
    assert d["approved_version"] == 1 and d["last_decision"] is None
    assert [x["filename"] for x in listed(client, hub, "marcus")] == ["policy.pdf"]  # still one document
    assert download(client, hub, doc_id) == V2


def test_viewers_and_checkers_keep_seeing_the_approved_version(client, hub):
    doc_id = approved_v1(client, hub)
    upload(client, hub, V2)
    for who in ("eve", "cara"):
        d = get(client, hub, doc_id, who).json()
        assert (d["version"], d["status"], d["latest"]) == (1, "approved", False)
        assert d["last_decision"]["decision"] == "APPROVED"
        assert download(client, hub, doc_id, who) == V1
    assert [d["version"] for d in listed(client, hub, "eve")] == [1]
    repos = client.get("/api/doc-repos", headers=hub["eve"]).json()
    assert next(r for r in repos if r["id"] == hub["repo"])["document_count"] == 1


def test_once_the_new_version_is_approved_everyone_sees_it(client, hub):
    doc_id = approved_v1(client, hub)
    upload(client, hub, V2)
    submit(client, hub, doc_id)
    assert inbox(client, hub, "cara")[0]["metadata"]["document"]["version"] == 2
    assert get(client, hub, doc_id, "cara").json()["version"] == 2  # checkers see what's waiting
    decide_latest(client, hub, "approve")
    d = get(client, hub, doc_id, "eve").json()
    assert (d["version"], d["latest"], d["approved_version"]) == (2, True, 2) and download(client, hub, doc_id, "eve") == V2


def test_uploading_over_a_draft_replaces_its_file(client, hub):
    [d] = upload(client, hub, V1).json()
    [again] = upload(client, hub, V2).json()
    assert again["id"] == d["id"] and again["version"] == 1 and again["outcome"] == "replaced"
    assert download(client, hub, d["id"]) == V2
    assert [v["number"] for v in versions(client, hub, d["id"]).json()] == [1]


def test_uploading_over_changes_requested_continues_the_same_request(client, hub):
    [d] = upload(client, hub, V1).json()
    submit(client, hub, d["id"])
    decide_latest(client, hub, "request_changes", "Add the date")
    [again] = upload(client, hub, V2).json()
    assert (again["version"], again["status"], again["outcome"]) == (1, "changes_requested", "replaced")
    submit(client, hub, d["id"])
    [task] = inbox(client, hub, "cara")
    assert task["round"] == 2 and download(client, hub, d["id"], "cara") == V2


def test_uploading_over_a_rejected_document_adds_a_version(client, hub):
    [d] = upload(client, hub, V1).json()
    submit(client, hub, d["id"])
    decide_latest(client, hub, "reject", "Wrong file")
    [again] = upload(client, hub, V2).json()
    assert (again["version"], again["status"], again["approved_version"]) == (2, "draft", None)


def test_identical_content_still_adds_a_version(client, hub):
    doc_id = approved_v1(client, hub)
    [d] = upload(client, hub, V1).json()
    assert d["id"] == doc_id and d["version"] == 2


def test_a_document_waiting_for_approval_refuses_the_whole_upload(client, hub):
    [d] = upload(client, hub, V1).json()
    submit(client, hub, d["id"])
    r = upload(client, hub, V2, more=[("other.pdf", V3)])
    assert r.status_code == 409 and "policy.pdf" in r.json()["detail"] and "waiting for approval" in r.json()["detail"]
    assert [x["filename"] for x in listed(client, hub, "marcus")] == ["policy.pdf"]  # other.pdf wasn't added
    assert download(client, hub, d["id"]) == V1


def test_the_same_name_in_another_folder_is_another_document(client, hub):
    doc_id = approved_v1(client, hub)
    [d] = upload(client, hub, V2, path="Archive/policy.pdf").json()
    assert d["id"] != doc_id and d["version"] == 1


def test_a_new_version_can_come_from_another_maker(client, hub):
    doc_id = approved_v1(client, hub)
    [d] = upload(client, hub, V2, who="mia").json()
    assert d["maker"]["lan_id"] == "mia"
    submit(client, hub, doc_id, who="mia")
    assert len(inbox(client, hub, "cara")) == 1


# --------------------------------------------------------------------------- metadata


def test_metadata_carries_forward_and_the_approved_version_keeps_its_own(client, hub):
    [d] = upload(client, hub, V1).json()
    country = next(m["field_id"] for m in d["metadata"] if m["label"] == "Country")
    client.put(url(hub, d["id"], "/metadata"), headers=hub["marcus"],
               json={"inherited": [{"field_id": country, "state": "override", "value": "Japan"}],
                     "own": [{"label": "Owner", "value": "Credit"}]})
    submit(client, hub, d["id"])
    decide_latest(client, hub, "approve")
    [v2] = upload(client, hub, V2).json()
    assert meta(v2) == {"Department": "Risk Management", "Country": "Japan", "Owner": "Credit"}
    r = client.put(url(hub, d["id"], "/metadata"), headers=hub["marcus"], json={"own": [{"label": "Owner", "value": "Treasury"}]})
    assert r.status_code == 200 and meta(r.json())["Owner"] == "Treasury"  # the new version is editable
    assert meta(get(client, hub, d["id"], "eve").json())["Owner"] == "Credit"  # viewers: the approved version's


def test_repository_values_follow_the_repository_again_in_a_new_version(client, hub):
    doc_id = approved_v1(client, hub)
    client.put(f"/api/doc-repos/{hub['repo']}/metadata", headers=hub["ben"],
               json=[{"label": "Department", "value": "Risk"}, {"label": "Country", "value": "Singapore"}])
    assert meta(get(client, hub, doc_id).json())["Department"] == "Risk Management"  # approved: frozen
    [v2] = upload(client, hub, V2).json()
    assert meta(v2)["Department"] == "Risk"
    assert meta(get(client, hub, doc_id, "eve").json())["Department"] == "Risk Management"


# --------------------------------------------------------------------------- history


def test_makers_and_checkers_see_every_version(client, hub):
    doc_id = approved_v1(client, hub)
    upload(client, hub, V2)
    for who in ("marcus", "cara"):
        r = versions(client, hub, doc_id, who)
        assert r.status_code == 200
        items = r.json()
        assert [(v["number"], v["status"], v["latest"], v["approved"]) for v in items] == [
            (2, "draft", True, False), (1, "approved", False, True)]
        assert items[1]["last_decision"]["decision"] == "APPROVED"
    assert versions(client, hub, doc_id, "eve").status_code == 404
    assert get(client, hub, doc_id, "eve").json()["actions"]["versions"] is False


def test_any_version_can_be_downloaded_from_the_history(client, hub):
    doc_id = approved_v1(client, hub)
    upload(client, hub, V2)
    assert client.get(url(hub, doc_id, "/versions/1/download"), headers=hub["marcus"]).content == V1
    assert client.get(url(hub, doc_id, "/versions/2/download"), headers=hub["marcus"]).content == V2
    assert client.get(url(hub, doc_id, "/versions/3/download"), headers=hub["marcus"]).status_code == 404
    assert client.get(url(hub, doc_id, "/versions/1/download"), headers=hub["eve"]).status_code == 404


# --------------------------------------------------------------------------- discard


def test_discarding_the_new_version_goes_back_to_the_approved_one(client, hub):
    doc_id = approved_v1(client, hub)
    [v2] = upload(client, hub, V2).json()
    assert v2["actions"]["discard"] is True
    client.put(url(hub, doc_id, "/metadata"), headers=hub["marcus"], json={"own": [{"label": "Owner", "value": "X"}]})
    r = client.post(url(hub, doc_id, "/discard-version"), headers=hub["marcus"])
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["version"], d["status"], d["latest"]) == (1, "approved", True) and "Owner" not in meta(d)
    assert download(client, hub, doc_id) == V1
    assert d["actions"]["edit"] is False  # approved again: locked
    items = versions(client, hub, doc_id).json()
    assert [(v["number"], v["discarded_at"] is not None) for v in items] == [(2, True), (1, False)]
    [v3] = upload(client, hub, V3).json()
    assert v3["version"] == 3  # numbers aren't reused


def test_discarding_changes_requested_withdraws_its_request(client, hub):
    doc_id = approved_v1(client, hub)
    upload(client, hub, V2)
    submit(client, hub, doc_id)
    decide_latest(client, hub, "request_changes", "Not yet")
    assert client.post(url(hub, doc_id, "/discard-version"), headers=hub["marcus"]).status_code == 200
    assert get(client, hub, doc_id).json()["version"] == 1 and inbox(client, hub, "cara") == []
    upload(client, hub, V3)
    submit(client, hub, doc_id)  # a fresh request for the next version
    assert inbox(client, hub, "cara")[0]["round"] == 1


def test_a_first_version_cannot_be_discarded(client, hub):
    [d] = upload(client, hub, V1).json()
    assert d["actions"]["discard"] is False
    r = client.post(url(hub, d["id"], "/discard-version"), headers=hub["marcus"])
    assert r.status_code == 409 and "delete the document" in r.json()["detail"]


def test_a_version_waiting_for_approval_cannot_be_discarded(client, hub):
    doc_id = approved_v1(client, hub)
    upload(client, hub, V2)
    submit(client, hub, doc_id)
    assert client.post(url(hub, doc_id, "/discard-version"), headers=hub["marcus"]).status_code == 409
    assert client.post(url(hub, doc_id, "/discard-version"), headers=hub["eve"]).status_code == 403


# --------------------------------------------------------------------------- restore


def test_restoring_an_earlier_version_makes_it_a_new_draft(client, hub):
    [d] = upload(client, hub, V1).json()
    client.put(url(hub, d["id"], "/metadata"), headers=hub["marcus"], json={"own": [{"label": "Owner", "value": "One"}]})
    submit(client, hub, d["id"])
    decide_latest(client, hub, "approve")
    upload(client, hub, V2)
    client.put(url(hub, d["id"], "/metadata"), headers=hub["marcus"], json={"own": [{"label": "Owner", "value": "Two"}]})
    submit(client, hub, d["id"])
    decide_latest(client, hub, "approve")
    assert [v["can_restore"] for v in versions(client, hub, d["id"]).json()] == [False, True]
    r = client.post(url(hub, d["id"], "/versions/1/restore"), headers=hub["marcus"])
    assert r.status_code == 200, r.text
    v3 = r.json()
    assert (v3["version"], v3["status"], meta(v3)["Owner"]) == (3, "draft", "One")
    assert download(client, hub, d["id"]) == V1
    assert versions(client, hub, d["id"]).json()[0]["restored_from"] == 1
    assert get(client, hub, d["id"], "eve").json()["version"] == 2  # until v3 is approved


def test_restoring_over_a_draft_replaces_it_in_place(client, hub):
    doc_id = approved_v1(client, hub)
    upload(client, hub, V2)
    d = client.post(url(hub, doc_id, "/versions/1/restore"), headers=hub["marcus"]).json()
    assert (d["version"], d["status"]) == (2, "draft") and download(client, hub, doc_id) == V1


def test_restoring_is_refused_while_waiting_for_approval(client, hub):
    doc_id = approved_v1(client, hub)
    upload(client, hub, V2)
    submit(client, hub, doc_id)
    r = client.post(url(hub, doc_id, "/versions/1/restore"), headers=hub["marcus"])
    assert r.status_code == 409 and "waiting for approval" in r.json()["detail"]
    assert client.post(url(hub, doc_id, "/versions/2/restore"), headers=hub["marcus"]).status_code == 409


def test_version_changes_are_audited(client, hub):
    doc_id = approved_v1(client, hub)
    upload(client, hub, V2)
    client.post(url(hub, doc_id, "/discard-version"), headers=hub["marcus"])
    upload(client, hub, V3)
    client.post(url(hub, doc_id, "/versions/1/restore"), headers=hub["marcus"])
    from tests.audit.test_audit import events
    [discarded] = events(client, hub["admin"], action="DOCUMENT_VERSION_DISCARDED")
    [restored] = events(client, hub["admin"], action="DOCUMENT_VERSION_RESTORED")
    assert (discarded["details"]["discarded"], discarded["details"]["now_latest"]) == (2, 1)
    assert (restored["details"]["restored"], restored["details"]["as_version"]) == (1, 3)


def test_viewers_see_only_the_approved_versions_approval_history(client, hub):
    doc_id = approved_v1(client, hub)
    upload(client, hub, V2)
    submit(client, hub, doc_id)
    history = lambda who: client.get(url(hub, doc_id, "/history"), headers=hub[who]).json()
    assert [h["status"] for h in history("marcus")] == ["PENDING", "APPROVED"]
    assert [h["status"] for h in history("eve")] == ["APPROVED"]


# --------------------------------------------------------------------------- Published / In progress


def view(client, hub, which, who="marcus"):
    r = client.get(f"/api/doc-repos/{hub['repo']}/documents", params={"view": which}, headers=hub[who])
    assert r.status_code == 200, r.text
    return {d["filename"]: (d["version"], d["status"]) for d in r.json()}


def test_published_lists_approved_versions_and_in_progress_the_rest(client, hub):
    doc_id = approved_v1(client, hub)
    upload(client, hub, V2)  # policy.pdf v2: a draft
    upload(client, hub, V3, name="new.pdf")  # never approved
    assert view(client, hub, "published") == {"policy.pdf": (1, "approved")}
    assert view(client, hub, "in_progress") == {"policy.pdf": (2, "draft"), "new.pdf": (1, "draft")}
    assert view(client, hub, "published", "eve") == {"policy.pdf": (1, "approved")}
    assert view(client, hub, "in_progress", "eve") == {}
    submit(client, hub, doc_id)
    assert view(client, hub, "in_progress", "cara") == {"policy.pdf": (2, "pending_approval")}  # no drafts


def test_the_published_version_opens_and_downloads_on_request(client, hub):
    doc_id = approved_v1(client, hub)
    upload(client, hub, V2)
    d = client.get(url(hub, doc_id), params={"published": True}, headers=hub["marcus"]).json()
    assert (d["version"], d["latest"], d["actions"]["edit"]) == (1, False, False)
    assert client.get(url(hub, doc_id, "/download"), params={"published": True}, headers=hub["marcus"]).content == V1
    [draft] = upload(client, hub, V3, name="new.pdf").json()
    r = client.get(url(hub, draft["id"]), params={"published": True}, headers=hub["marcus"])
    assert r.status_code == 404 and "no approved version" in r.json()["detail"]


def test_an_unknown_view_is_refused(client, hub):
    r = client.get(f"/api/doc-repos/{hub['repo']}/documents", params={"view": "mine"}, headers=hub["marcus"])
    assert r.status_code == 422
