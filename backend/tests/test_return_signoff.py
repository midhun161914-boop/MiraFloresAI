"""Return-level sign-off: the reviewer and partner sign the return as a whole. The
pre-file gate requires both; the usual rules apply (reviewer before partner, no
self-review), and a later correction or adjustment reopens them."""

from tests.test_changes import DANIEL, HELEN, PRIYA
from tests.test_lifecycle import complete_dd, gate


def kinds(c):
    return [b["kind"] for b in gate(c)["blockers"]]


def sign(c, level, who):
    return c.post("/api/review/signoffs", json={"node": "return", "level": level}, headers=who)


def clear_findings(c):
    errs = [f["id"] for f in c.get("/api/checks", headers=PRIYA).json()["findings"]
            if f["severity"] == "error" and f["status"] == "open"]
    assert c.post("/api/bulk/disposition", json={"finding_ids": errs, "disposition": "accepted",
                                                 "note": "Accepted with partner."}, headers=PRIYA).status_code == 200


def finding_id(c, code):
    return next(f["id"] for f in c.get("/api/checks", headers=PRIYA).json()["findings"] if f["code"] == code)


def test_return_signoff_is_actionable_and_clears_both_gate_blockers(fresh):
    clear_findings(fresh)
    complete_dd(fresh)
    g = gate(fresh)
    sig = [b for b in g["blockers"] if b["kind"] == "missing_signoff"]
    assert [b["title"] for b in sig] == ["Reviewer sign-off on the return", "Partner sign-off on the return"]
    assert all(b["link"] == "/review#return-signoff" for b in sig)          # the gate sends you to a real control
    before = len(g["blockers"])

    r = fresh.get("/api/review/node", params={"node": "return"}, headers=DANIEL).json()
    assert r["permissions"]["signoff_reviewer"]["allowed"] and not r["permissions"]["signoff_partner"]["allowed"]

    assert sign(fresh, "partner", HELEN).json()["detail"]["code"] == "ORDER"     # reviewer first
    assert sign(fresh, "reviewer", PRIYA).json()["detail"]["code"] == "ROLE"
    assert sign(fresh, "reviewer", DANIEL).status_code == 200
    assert len(gate(fresh)["blockers"]) == before - 1
    assert sign(fresh, "partner", HELEN).status_code == 200
    g = gate(fresh)
    assert "missing_signoff" not in kinds(fresh) and len(g["blockers"]) == before - 2 and g["clear"]
    steps = {s["step"]: s["status"] for s in g["steps"]}
    assert steps["Reviewer sign-off"] == steps["Partner sign-off"] == "done"


def test_adjusting_the_return_is_preparer_work_on_it(fresh):
    fx = finding_id(fresh, "FX_RATE_WRONG_YEAR")
    assert fresh.post(f"/api/adjustments/from-finding/{fx}", json={"reason": "2025 rate"}, headers=DANIEL).json()["status"] == "active"
    r = sign(fresh, "reviewer", DANIEL)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "NO_SELF_REVIEW"
    assert sign(fresh, "reviewer", HELEN).status_code == 200                   # someone who didn't adjust it


def test_adjustment_after_signoff_reopens_the_return_signoffs(fresh):
    clear_findings(fresh)
    complete_dd(fresh)
    sign(fresh, "reviewer", DANIEL)
    sign(fresh, "partner", HELEN)
    assert gate(fresh)["clear"]
    fx = finding_id(fresh, "FX_RATE_WRONG_YEAR")
    assert fresh.post(f"/api/adjustments/from-finding/{fx}", json={"reason": "2025 rate"}, headers=PRIYA).json()["status"] == "active"
    r = fresh.get("/api/review/node", params={"node": "return"}, headers=DANIEL).json()
    assert {s["level"]: s["status"] for s in r["signoffs"]} == {"reviewer": "reopened", "partner": "reopened"}
    reopened = next(s for s in r["signoffs"] if s["level"] == "reviewer")
    assert reopened["changed"] and reopened["changed"][0]["ev"] == "SchB.1.6" and "ADJ-" in reopened["reopened_reason"]
    ks = kinds(fresh)
    assert ks.count("reopened_signoff") == 2 and ks.count("missing_signoff") == 2
    assert sign(fresh, "reviewer", DANIEL).status_code == 200 and sign(fresh, "partner", HELEN).status_code == 200
    assert gate(fresh)["clear"]                     # signing again answers the reopened sign-offs


def test_correction_after_signoff_reopens_the_return_signoff(fresh):
    sign(fresh, "reviewer", DANIEL)
    ev = next(s["ref"] for s in fresh.get("/api/lines/F1040.1a", headers=PRIYA).json()["sources"] if s["ref"].startswith("ev-"))
    val = fresh.get(f"/api/values/{ev}", headers=PRIYA).json()["value"]
    fresh.post("/api/review/corrections", json={"ev": ev, "to": val + 1, "reason": "test"}, headers=PRIYA)
    r = fresh.get("/api/review/node", params={"node": "return"}, headers=DANIEL).json()
    assert [s["status"] for s in r["signoffs"] if s["level"] == "reviewer"] == ["reopened"]
