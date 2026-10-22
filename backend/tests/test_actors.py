import re

from app.services.redact import mask_keep_last4

FULL_SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
CLEARED = {"X-Actor-Id": "st-01"}      # Priya Raman, preparer, cleared
UNCLEARED = {"X-Actor-Id": "st-04"}    # Marcus Bell, preparer, no clearance


def test_actor_roster(client):
    actors = {a["id"]: a for a in client.get("/api/actors").json()}
    assert set(actors) >= {"st-01", "st-02", "st-03", "st-04", "st-05", "st-06", "cu-01", "cu-02"}
    assert actors["st-04"]["sensitive_data_clearance"] is False
    assert actors["st-01"]["assignments"] == ["preparer"]
    assert actors["cu-01"]["kind"] == "client"


def test_default_actor_is_the_assigned_preparer(client):
    assert client.get("/api/me").json()["id"] == "st-01"
    assert client.get("/api/me", headers=UNCLEARED).json()["name"] == "Marcus Bell"
    assert client.get("/api/me", headers={"X-Actor-Id": "nobody"}).status_code == 400


def test_mask_keeps_length_and_last_four():
    assert mask_keep_last4("666-41-2287") == "•••-••-2287"
    assert len(mask_keep_last4("4483019276")) == 10


def test_uncleared_actor_never_receives_a_full_ssn(client):
    cleared = client.get("/api/documents/D09", headers=CLEARED).json()
    masked = client.get("/api/documents/D09", headers=UNCLEARED).json()
    assert FULL_SSN.search(cleared["pages"][0]["printed_content"])
    assert not FULL_SSN.search(masked["pages"][0]["printed_content"])
    assert masked["redacted"] is True
    ssn = next(v for v in masked["values"] if v["value_type"] == "ssn")
    assert ssn["redacted"] and ssn["text_as_read"].endswith("2287") and "666" not in ssn["text_as_read"]

    for path in ["/api/values?value_type=ssn", "/api/resolve?ref=household:ngozi", "/api/search?q=666"]:
        body = client.get(path, headers=UNCLEARED).text
        assert not FULL_SSN.search(body), path


def test_highlight_spans_survive_masking(client):
    masked = client.get("/api/documents/D09", headers=UNCLEARED).json()
    page = masked["pages"][0]["printed_content"]
    box1 = next(v for v in masked["values"] if v["id"] == "ev-0035")
    assert page[box1["match"]["start"]:box1["match"]["end"]] == "107,800.00"


def test_ip_pin_fully_masked(client):
    target = client.get("/api/resolve?ref=household:ngozi", headers=UNCLEARED).json()["target"]
    assert set(target["ip_pin"]) == {"•"}


def test_search_groups(client):
    res = client.get("/api/search", params={"q": "meridian"}).json()
    kinds = [g["kind"] for g in res["groups"]]
    assert "document" in kinds
    exact = client.get("/api/search", params={"q": "ev-0035"}).json()
    assert exact["exact"]["document_id"] == "D09"
    by_id = client.get("/api/search", params={"q": "D3"}).json()
    docs = next(g for g in by_id["groups"] if g["kind"] == "document")
    assert docs["items"][0]["id"].startswith("D3")
