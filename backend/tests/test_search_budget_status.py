"""Workpaper-wide search, time vs budget, status surface, typed lifecycle schema."""

from tests.test_changes import DANIEL, HELEN, PRIYA
from tests.test_lifecycle import ERIK, MARCUS, NGOZI, authorize, clear_gate


def groups(c, q, who=PRIYA):
    r = c.get("/api/search", params={"q": q}, headers=who)
    assert r.status_code == 200
    return {g["kind"]: g for g in r.json()["groups"]}


def test_search_covers_findings_people_screens_and_events(fresh):
    g = groups(fresh, "zero basis")
    assert "finding" in g and g["finding"]["items"][0]["link"].startswith("/findings")
    g = groups(fresh, "theo")
    assert "person" in g and g["person"]["items"][0]["label"] == "Theo Lindqvist-Okafor"
    assert "666" not in str(g["person"])                      # people never expose identifiers
    assert "screen" in groups(fresh, "8879")                   # screens by keyword
    fresh.post("/api/review/notes", json={"node": "F1040.1a", "text": "Tie the Corvane W-2", "blocking": False}, headers=DANIEL)
    ev = groups(fresh, "corvane w-2")["event"]["items"][0]
    assert ev["label"].startswith("#") and ev["link"] == "/lines/F1040.1a"
    assert "notice" in groups(fresh, "letter 566")
    assert fresh.get("/api/search", params={"q": "theo"}, headers=NGOZI).status_code == 403   # clients: no firm search


def test_search_does_not_find_identity_numbers_in_events(fresh):
    clear_gate(fresh)
    authorize(fresh)
    fresh.post("/api/filing/transmit", headers=DANIEL)
    fresh.post("/api/filing/identity", json={"person": "theo", "evidence": "ev-1080", "reason": "per D71"}, headers=PRIYA)
    assert "event" not in groups(fresh, "666-74-3390", MARCUS)


def test_time_logging_and_budget_indicators(fresh):
    r = fresh.post("/api/time", json={"bucket": "business", "hours": 3.0, "note": "Schedule C tie-out"}, headers=PRIYA)
    assert r.status_code == 200
    eid = r.json()["id"]
    b = {x["bucket"]: x for x in fresh.get("/api/budget", headers=PRIYA).json()["buckets"]}
    assert b["business"]["budget"] == 3.5 and b["business"]["status"] == "near" and b["business"]["remaining"] == 0.5
    fresh.post("/api/time", json={"bucket": "business", "hours": 1.0, "note": "1099 follow-up"}, headers=DANIEL)
    b = {x["bucket"]: x for x in fresh.get("/api/budget", headers=PRIYA).json()["buckets"]}
    assert b["business"]["status"] == "over" and b["business"]["by_person"] == {"Priya Raman": 3.0, "Daniel Ortiz": 1.0}
    assert b["california"]["status"] == "not_started"
    # rules
    bad = [({"bucket": "nope", "hours": 1, "note": "x"}, "BUCKET"), ({"bucket": "business", "hours": 0.3, "note": "x"}, "HOURS"),
           ({"bucket": "business", "hours": 1, "note": " "}, "NOTE")]
    for body, code in bad:
        assert fresh.post("/api/time", json=body, headers=PRIYA).json()["detail"]["code"] == code
    assert fresh.post(f"/api/time/{eid}/void", headers=DANIEL).json()["detail"]["code"] == "NOT_YOURS"
    assert fresh.post(f"/api/time/{eid}/void", headers=PRIYA).json()["voided"]
    b = {x["bucket"]: x for x in fresh.get("/api/budget", headers=PRIYA).json()["buckets"]}
    assert b["business"]["logged"] == 1.0


def test_status_follows_the_lifecycle(fresh):
    s = fresh.get("/api/status", headers=PRIYA).json()
    assert s["stage"] == "preparing" and s["blockers"] > 0 and s["next_step"]["label"].startswith("Clear:")
    assert any(o["kind"] == "errors" for o in s["outstanding"])
    assert any(o["role"] == "preparer" and o["name"] == "Priya Raman" for o in s["owners"])
    clear_gate(fresh)
    assert fresh.get("/api/status", headers=PRIYA).json()["next_step"]["label"] == "Present the return to the client"
    fresh.post("/api/filing/present", json={"note": "x"}, headers=DANIEL)
    s = fresh.get("/api/status", headers=PRIYA).json()
    assert s["stage"] == "presented" and "Ngozi" in s["next_step"]["label"]
    for who in (NGOZI, ERIK):
        fresh.post("/api/client/filing/approve", json={"pin": "24680", "agree": True}, headers=who)
    fresh.post("/api/filing/ero-sign", json={}, headers=HELEN)
    fresh.post("/api/filing/transmit", headers=DANIEL)
    assert fresh.get("/api/status", headers=PRIYA).json()["stage"] == "transmitted"
    fresh.post("/api/filing/identity", json={"person": "theo", "evidence": "ev-1080", "reason": "per D71"}, headers=PRIYA)
    fresh.post("/api/filing/transmit", headers=DANIEL)
    s = fresh.get("/api/status", headers=PRIYA).json()
    assert s["stage"] == "notice" and s["filed_snapshot"]          # Letter 566 is open in the packet
    assert any(m["label"].startswith("Accepted") and m["done"] for m in s["milestones"])


def test_lifecycle_schemas_are_in_openapi(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    for name in ("Filing", "Gate", "ExtensionView", "Amendment", "NoticeResponse", "CarryForward", "ClientFiling",
                 "FiledReturn", "Status", "Budget"):
        assert name in schemas, name
    assert schemas["Filing"].get("additionalProperties") is False   # strict: undeclared fields fail validation
