def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_overview(client):
    body = client.get("/api/overview").json()
    assert body["counts"]["documents"] == 74
    assert body["counts"]["extracted_values"] == 3012
    assert body["current_version"] == "v3"
    assert [v["version"] for v in body["versions"]] == ["v1", "v2", "v3"]


def test_documents_index_flags_supersession(client):
    docs = {d["id"]: d for d in client.get("/api/documents").json()}
    assert len(docs) == 74
    assert docs["D30"]["current_use"] == "superseded"
    assert docs["D31"]["marked_corrected"] is True
    assert docs["D31"]["current_use"] == "used"


def test_document_detail_has_pages_and_located_values(client):
    d = client.get("/api/documents/D09").json()
    assert d["page_count"] == len(d["pages"]) == 1
    box1 = next(v for v in d["values"] if v["id"] == "ev-0035")
    page = d["pages"][0]["printed_content"]
    assert page[box1["match"]["start"]:box1["match"]["end"]] == "107,800.00"
    assert client.get("/api/documents/D99").status_code == 404


def test_values_filters(client):
    low = client.get("/api/values", params={"max_confidence": 0.5}).json()
    assert [v["id"] for v in low["items"]] == ["ev-1049"]
    by_doc = client.get("/api/values", params={"document_id": "D09"}).json()
    assert by_doc["total"] == 17
    page = client.get("/api/values", params={"limit": 100, "offset": 3000}).json()
    assert page["total"] == 3012 and len(page["items"]) == 12
    q = client.get("/api/values", params={"q": "box 1 wages", "document_id": "D09"}).json()
    assert q["items"][0]["id"] == "ev-0035"


def test_resolve_endpoints(client):
    r = client.get("/api/resolve", params={"ref": "ev-0035"})
    assert r.status_code == 200 and r.json()["document_id"] == "D09"
    assert client.get("/api/resolve", params={"ref": "nope"}).status_code == 404
    batch = client.post("/api/resolve/batch", json={"refs": ["D01", "nope", "F1040.11"]}).json()
    assert [b["found"] for b in batch] == [True, False, True]


def test_version_lines(client):
    body = client.get("/api/versions/v3/lines", params={"form": "F1040"}).json()
    assert body["total"] == 31
    one_a = next(x for x in body["items"] if x["key"] == "F1040.1a")
    assert one_a["value"] == 212400 and one_a["sources"] == ["ev-0016", "ev-0035"]
