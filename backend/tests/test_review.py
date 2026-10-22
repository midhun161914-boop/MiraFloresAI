"""Review layer: event store, verifications, review notes, sign-offs, enforced rules, view log."""

import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

PRIYA = {"X-Actor-Id": "st-01"}   # preparer
DANIEL = {"X-Actor-Id": "st-02"}  # reviewer
HELEN = {"X-Actor-Id": "st-03"}   # partner
MARCUS = {"X-Actor-Id": "st-04"}  # preparer, no sensitive-data clearance
JO = {"X-Actor-Id": "st-05"}      # firm administrator
NGOZI = {"X-Actor-Id": "cu-01"}   # client
LINE = "F2441.1b"                 # dependent-care provider line; cites ev-1045 (EIN misread)
FULL_SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")


def node(c, key, who=PRIYA):
    return c.get("/api/review/node", params={"node": key}, headers=who).json()


# ------------------------------------------------------------------ event store
def test_store_is_append_only_at_the_database_level(fresh):
    fresh.post("/api/review/verify", json={"node": LINE, "method": "recalculated"}, headers=PRIYA)
    con = sqlite3.connect(fresh.db_path)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        con.execute("UPDATE events SET actor = 'x'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        con.execute("DELETE FROM events")
    con.close()


def test_assignments_seeded_once_and_state_survives_restart(idx, tmp_path):
    db = tmp_path / "e.sqlite"
    with TestClient(create_app(idx, frontend_dist=tmp_path, events_db=db)) as c:
        q = c.get("/api/review/queue", headers=PRIYA).json()
        assert {a["role"]: a["actor"] for a in q["assignments"]} == {"preparer": "st-01", "reviewer": "st-02", "partner": "st-03"}
        c.post("/api/review/notes", json={"node": LINE, "text": "persist me", "blocking": True}, headers=PRIYA)
    with TestClient(create_app(idx, frontend_dist=tmp_path, events_db=db)) as c:  # "refresh" / restart
        notes = node(c, LINE)["notes"]
        assert [n["text"] for n in notes] == ["persist me"]
        seeded = [e for e in c.get("/api/events", params={"type": "assignment."}, headers=PRIYA).json()["items"]]
        assert len(seeded) == 3  # not re-seeded on restart


# ------------------------------------------------------------------ the demo flow, end to end
def test_demo_flow_verify_note_resolve_signoff_reopen(fresh):
    c = fresh
    # Priya verifies the number and leaves a blocking note
    v = c.post("/api/review/verify", json={"node": LINE, "method": "agreed_to_source_document",
                                           "note": "4,200 agreed to D62 statement total."}, headers=PRIYA)
    assert v.status_code == 200 and v.json()["status"] == "current"
    n = c.post("/api/review/notes", json={"node": LINE, "blocking": True,
                                          "text": "Confirm Little Sprouts is Theo's only 2025 provider."}, headers=PRIYA).json()
    assert c.get("/api/review/readiness", headers=PRIYA).json()["ready"] is False

    # Priya cannot clear her own blocking note, nor sign as reviewer
    r = c.post(f"/api/review/notes/{n['id']}/resolve", json={"text": "done"}, headers=PRIYA)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "REVIEW_REQUIRED"
    r = c.post("/api/review/signoffs", json={"node": LINE, "level": "reviewer"}, headers=PRIYA)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "ROLE"

    # Daniel cannot sign while the blocking note is open; resolves it, then signs
    r = c.post("/api/review/signoffs", json={"node": LINE, "level": "reviewer"}, headers=DANIEL)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "BLOCKING_NOTE"
    r = c.post(f"/api/review/notes/{n['id']}/resolve", json={"text": "Confirmed via call notes.",
                                                              "expected_seq": n["last_seq"]}, headers=DANIEL)
    assert r.status_code == 200 and r.json()["status"] == "resolved"
    fp = node(c, LINE, DANIEL)["fingerprint"]
    s = c.post("/api/review/signoffs", json={"node": LINE, "level": "reviewer", "expected_fingerprint": fp}, headers=DANIEL)
    assert s.status_code == 200 and s.json()["status"] == "active"
    assert c.get("/api/review/readiness", headers=PRIYA).json()["blockers"] == []

    # The underlying value changes: Priya corrects the transposed provider EIN to what D62 prints
    corr = c.post("/api/review/corrections", json={"ev": "ev-1045", "to": "74-3829156",
                                                   "reason": "D62 prints 74-3829156; pipeline transposed digits."}, headers=PRIYA)
    assert corr.status_code == 200
    review = node(c, LINE, DANIEL)
    signoff = review["signoffs"][0]
    assert signoff["status"] == "reopened"
    assert signoff["changed"] == [{"ev": "ev-1045", "was": "74-3829516", "now": "74-3829156"}]
    assert review["verifications"][0]["status"] == "stale"
    blockers = c.get("/api/review/readiness", headers=PRIYA).json()["blockers"]
    assert [b["kind"] for b in blockers] == ["reopened_signoff"]
    # the reopen is itself an event, by the system, caused by the correction
    reopened = c.get("/api/events", params={"type": "signoff.reopened"}, headers=JO).json()["items"]
    assert reopened[0]["actor"] == "system" and reopened[0]["payload"]["caused_by"] == corr.json()["id"]
    # the value now carries its correction everywhere it is served
    assert c.get("/api/values/ev-1045", headers=PRIYA).json()["correction"]["to"] == "74-3829156"


# ------------------------------------------------------------------ rules
def test_no_self_review(fresh):
    fresh.post("/api/review/verify", json={"node": LINE, "method": "recalculated"}, headers=DANIEL)
    r = fresh.post("/api/review/signoffs", json={"node": LINE, "level": "reviewer"}, headers=DANIEL)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "NO_SELF_REVIEW"
    # preparer work beneath a total also counts: verifying wages bars reviewing AGI
    fresh.post("/api/review/verify", json={"node": "F1040.1a", "method": "agreed_to_source_document"}, headers=HELEN)
    perm = node(fresh, "F1040.11", HELEN)["permissions"]["signoff_partner"]
    assert perm["allowed"] is False


def test_partner_follows_reviewer_and_unknown_method_refused(fresh):
    r = fresh.post("/api/review/verify", json={"node": LINE, "method": "eyeballed"}, headers=PRIYA)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "METHOD"
    fresh.post("/api/review/verify", json={"node": LINE, "method": "recalculated"}, headers=PRIYA)
    r = fresh.post("/api/review/signoffs", json={"node": LINE, "level": "partner"}, headers=HELEN)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "ORDER"


def test_lost_writes_are_refused_not_overwritten(fresh):
    n = fresh.post("/api/review/notes", json={"node": LINE, "text": "q"}, headers=PRIYA).json()
    fresh.post(f"/api/review/notes/{n['id']}/reply", json={"text": "first", "expected_seq": n["last_seq"]}, headers=DANIEL)
    stale = fresh.post(f"/api/review/notes/{n['id']}/reply", json={"text": "second", "expected_seq": n["last_seq"]},
                       headers=PRIYA)
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "STALE"
    fresh.post("/api/review/verify", json={"node": LINE, "method": "recalculated"}, headers=PRIYA)
    fp = node(fresh, LINE, DANIEL)["fingerprint"]
    fresh.post("/api/review/corrections", json={"ev": "ev-1046", "to": 4300, "reason": "test"}, headers=PRIYA)
    r = fresh.post("/api/review/signoffs", json={"node": LINE, "level": "reviewer", "expected_fingerprint": fp},
                   headers=DANIEL)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "CONTENT_CHANGED"


def test_administrator_and_client_cannot_do_review_work(fresh):
    assert fresh.post("/api/review/verify", json={"node": LINE, "method": "recalculated"}, headers=JO).status_code == 403
    r = fresh.post("/api/review/verify", json={"node": LINE, "method": "recalculated"}, headers=NGOZI)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "CLIENT_SURFACE_ONLY"


# ------------------------------------------------------------------ client surface
@pytest.mark.parametrize("path", ["/api/documents", "/api/documents/D09", "/api/lines/F1040.1a",
                                  "/api/values", "/api/overview", "/api/review/queue", "/api/events"])
def test_client_users_only_reach_the_client_surface(fresh, path):
    r = fresh.get(path, headers=NGOZI)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "CLIENT_SURFACE_ONLY"


def test_client_home(fresh):
    home = fresh.get("/api/client/home", headers=NGOZI).json()
    assert home["you"] == "Ngozi Okafor" and all(d["uploaded_by"] == "client" for d in home["documents"])
    assert fresh.get("/api/client/home", headers=PRIYA).status_code == 403


# ------------------------------------------------------------------ sensitive data + view log
def test_marcus_sees_masked_data_and_every_access_is_logged(fresh):
    body = fresh.get("/api/documents/D09", headers=MARCUS).text
    assert not FULL_SSN.search(body)
    fresh.get("/api/documents/D09", headers=PRIYA)  # an unmasked view is logged too (firm rule)
    log = fresh.get("/api/viewlog", headers=JO).json()["items"]
    entries = {(e["actor"], e["node"], e["payload"]["masked"]) for e in log}
    assert ("st-04", "D09", True) in entries and ("st-01", "D09", False) in entries
    # repeat views inside 30 s coalesce
    fresh.get("/api/documents/D09", headers=MARCUS)
    assert len([e for e in fresh.get("/api/viewlog", headers=JO).json()["items"] if e["actor"] == "st-04"]) == 1


def test_view_log_visibility(fresh):
    fresh.get("/api/documents/D09", headers=MARCUS)
    fresh.get("/api/documents/D09", headers=PRIYA)
    mine = fresh.get("/api/viewlog", headers=MARCUS).json()["items"]
    assert {e["actor"] for e in mine} == {"st-04"}  # Marcus sees only his own entries
    assert {e["actor"] for e in fresh.get("/api/viewlog", headers=HELEN).json()["items"]} >= {"st-01", "st-04"}


def test_uncleared_staff_cannot_correct_sensitive_values(fresh, idx):
    ssn_ev = next(e.id for e in idx.packet.extracted_values if e.value_type == "ssn")
    r = fresh.post("/api/review/corrections", json={"ev": ssn_ev, "to": "x", "reason": "r"}, headers=MARCUS)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "CLEARANCE"
