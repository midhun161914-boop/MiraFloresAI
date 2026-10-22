"""Adjustments with the partner rule, version compare, digest, what-ifs, bulk + undo."""

PRIYA = {"X-Actor-Id": "st-01"}
DANIEL = {"X-Actor-Id": "st-02"}
HELEN = {"X-Actor-Id": "st-03"}
JO = {"X-Actor-Id": "st-05"}


def finding(c, code):
    return next(f for f in c.get("/api/checks", headers=PRIYA).json()["findings"] if f["code"] == code)


# ------------------------------------------------------------------ adjustments
def test_rsu_fix_requires_partner_signoff_enforced_server_side(fresh):
    f = finding(fresh, "ZERO_BASIS_WITH_KNOWN_BASIS")
    assert f["fix"] and len(f["fix"]["changes"]) == 3
    r = fresh.post(f"/api/adjustments/from-finding/{f['id']}", json={"reason": "Use D11 adjusted basis per lot."}, headers=PRIYA)
    assert r.status_code == 200
    adj = r.json()
    assert adj["status"] == "pending_partner" and adj["requires_partner"] and adj["threshold"] == 1000
    assert adj["tax_effect"]["federal_balance_due"] == f["tax_effect"]["federal_balance_due"]   # carried from the finding
    assert set(f["refs"]) <= set(adj["refs"])                                                     # evidence carried through
    blockers = fresh.get("/api/review/readiness", headers=PRIYA).json()["blockers"]
    assert any(b["kind"] == "pending_adjustment" for b in blockers)
    # not applied while pending
    rows = {x["key"]: x for x in fresh.get("/api/versions/v3/lines", params={"form": "F8949"}, headers=PRIYA).json()["items"]}
    assert rows["F8949.B.N1"]["adjusted_value"] is None

    r = fresh.post(f"/api/adjustments/{adj['id']}/approve", json={"note": "ok"}, headers=DANIEL)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "PARTNER_REQUIRED"
    r = fresh.post(f"/api/adjustments/{adj['id']}/approve", json={"note": ""}, headers=HELEN)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "NOTE"
    r = fresh.post(f"/api/adjustments/{adj['id']}/approve", json={"note": "Agreed to D11 lot detail."}, headers=HELEN)
    assert r.status_code == 200 and r.json()["status"] == "active"

    rows = {x["key"]: x for x in fresh.get("/api/versions/v3/lines", params={"form": "F8949"}, headers=PRIYA).json()["items"]}
    assert rows["F8949.B.N1"]["value"] == 19240 and rows["F8949.B.N1"]["adjusted_value"] == 140  # original preserved
    assert finding(fresh, "ZERO_BASIS_WITH_KNOWN_BASIS")["status"] == "adjusted"

    # undo follows the same rule: reversing a partner-approved adjustment needs a partner
    r = fresh.post(f"/api/adjustments/{adj['id']}/reverse", json={"note": "mistake"}, headers=PRIYA)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "PARTNER_REQUIRED"
    r = fresh.post(f"/api/adjustments/{adj['id']}/reverse", json={"note": "Re-examining lot N4."}, headers=HELEN)
    assert r.json()["status"] == "reversed"


def test_small_adjustment_applies_without_partner(fresh):
    f = finding(fresh, "FX_RATE_WRONG_YEAR")
    adj = fresh.post(f"/api/adjustments/from-finding/{f['id']}", json={"reason": "2025 average rate."}, headers=PRIYA).json()
    assert adj["status"] == "active" and not adj["requires_partner"]


def test_partner_cannot_approve_own_adjustment(fresh):
    f = finding(fresh, "ESTIMATED_PAYMENTS_MISMATCH")
    adj = fresh.post(f"/api/adjustments/from-finding/{f['id']}", json={"reason": "Per transcript."}, headers=HELEN).json()
    assert adj["status"] == "active"  # +1,000 is not *over* 1,000
    f2 = finding(fresh, "CA_ESTIMATED_PAYMENTS_MISMATCH")
    adj2 = fresh.post(f"/api/adjustments/from-finding/{f2['id']}", json={"reason": "Per FTB."}, headers=HELEN).json()
    assert adj2["status"] == "pending_partner"
    r = fresh.post(f"/api/adjustments/{adj2['id']}/approve", json={"note": "fine"}, headers=HELEN)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "NO_SELF_REVIEW"


def test_new_line_adjustment_adds_missing_lot(fresh):
    f = finding(fresh, "BROKER_SUMMARY_DETAIL_MISMATCH")
    adj = fresh.post(f"/api/adjustments/from-finding/{f['id']}", json={"reason": "Lot M18 on unread page 32."}, headers=PRIYA).json()
    assert adj["changes"][0]["new_line"] and adj["changes"][0]["to_value"] == -60
    rows = {x["key"]: x for x in fresh.get("/api/versions/v3/lines", params={"form": "F8949"}, headers=PRIYA).json()["items"]}
    assert rows["F8949.B.M18"]["adjusted_value"] == -60 and rows["F8949.B.M18"]["rule"] == "ADJUSTMENT"


def test_adjustment_rules(fresh):
    r = fresh.post("/api/adjustments", json={"reason": "", "changes": [{"key": "SchB.1.2", "to_value": 0}]}, headers=PRIYA)
    assert r.status_code == 403
    r = fresh.post("/api/adjustments", json={"reason": "x", "changes": [{"key": "SchB.1.2", "to_value": 0}]}, headers=JO)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "ROLE"
    r = fresh.post("/api/adjustments", json={"reason": "x", "changes": [{"key": "SchB.1.2", "to_value": 0}]}, headers=PRIYA)
    assert r.json()["tax_effect"]["source"] == "tax_effect_rates estimate" and r.json()["tax_effect"]["federal_tax"] == round(-1840 * 0.348)


# ------------------------------------------------------------------ compare
def test_compare_v2_v3_explains_changes(client):
    c = client.get("/api/compare", params={"a": "v2", "b": "v3"}, headers=PRIYA).json()
    assert c["summary"]["lines_added"] >= 1 and c["summary"]["engine_change_log_entries"] == 89
    lines = {d["key"]: d for g in c["groups"] for d in g["lines"]}
    assert lines["SchB.1.8"]["change"] == "added"
    assert any("trigger" in w for w in lines["SchB.2"]["why"])
    assert {h["key"] for h in c["headline"]} >= {"F1040.24", "F540NR.64"}


def test_compare_v1_v2_names_the_corrected_document(client):
    c = client.get("/api/compare", params={"a": "v1", "b": "v2"}, headers=PRIYA).json()
    whys = [w for g in c["groups"] for d in g["lines"] for w in d["why"]]
    assert any("D30" in w and "D31" in w for w in whys)


def test_saved_state_compare_shows_adjustments(fresh):
    fresh.post("/api/states", json={"name": "Before adjustments"}, headers=PRIYA)
    state = next(s for s in fresh.get("/api/states", headers=PRIYA).json() if s["kind"] == "saved")
    f = finding(fresh, "FX_RATE_WRONG_YEAR")
    fresh.post(f"/api/adjustments/from-finding/{f['id']}", json={"reason": "2025 rate."}, headers=PRIYA)
    c = fresh.get("/api/compare", params={"a": state["id"], "b": "v3@now"}, headers=PRIYA).json()
    d = next(d for g in c["groups"] for d in g["lines"] if d["key"] == "SchB.1.6")
    assert d["old"] == 1747 and d["new"] == 1871 and d["why"][0].startswith("Adjustment ")


# ------------------------------------------------------------------ digest
def test_since_last_looked_is_per_user(fresh):
    fresh.post("/api/digest/seen", json={}, headers=DANIEL)
    fresh.post("/api/review/notes", json={"node": "F1040.1a", "text": "Check RSU income in box 1"}, headers=PRIYA)
    d = fresh.get("/api/digest", headers=DANIEL).json()
    assert d["count"] == 1 and "RSU" in d["items"][0]["text"]
    assert fresh.get("/api/digest", headers=PRIYA).json()["count"] == 0 or \
        all(i["actor"] != "st-01" for i in fresh.get("/api/digest", headers=PRIYA).json()["items"])
    fresh.post("/api/digest/seen", json={}, headers=DANIEL)
    assert fresh.get("/api/digest", headers=DANIEL).json()["count"] == 0


# ------------------------------------------------------------------ what-ifs
def test_scripted_whatifs_are_engine_results(client):
    w = client.get("/api/whatif", headers=PRIYA).json()
    assert len(w["alternatives"]) == 5 and all(a["kind"] == "ENGINE" for a in w["alternatives"])


def test_adhoc_estimate_is_labelled(client):
    e = client.post("/api/whatif/estimate", json={"items": [{"category": "itemized", "change": 6000, "label": "receipt is 7,500"}]},
                    headers=PRIYA).json()
    assert e["kind"] == "ESTIMATE" and "not an engine recompute" in e["disclaimer"]
    assert e["federal_tax"] == round(6000 * -0.26)


# ------------------------------------------------------------------ bulk + undo
def test_bulk_verify_and_undo_respect_rules(fresh):
    lots = [x["key"] for x in fresh.get("/api/versions/v3/lines", params={"form": "F8949"}, headers=PRIYA).json()["items"]
            if not x["key"].endswith(".total")][:50]
    r = fresh.post("/api/bulk/verify", json={"nodes": lots, "method": "agreed_to_source_document",
                                             "note": "Agreed to 1099-B detail"}, headers=PRIYA).json()
    assert r["applied"] == 50 and r["refused"] == []
    summary = fresh.get("/api/review/summary", headers=PRIYA).json()
    assert all(summary[k]["verified"] for k in lots)
    bulk = fresh.get("/api/bulk", headers=PRIYA).json()[0]
    assert bulk["count"] == 50 and not bulk["undone"]
    # Daniel didn't record those verifications, so he can't undo them
    r = fresh.post(f"/api/bulk/{r['bulk_id']}/undo", headers=DANIEL)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "UNDO_NOT_ALLOWED"
    u = fresh.post(f"/api/bulk/{bulk['id']}/undo", headers=PRIYA).json()
    assert u["applied"] == 50
    summary = fresh.get("/api/review/summary", headers=PRIYA).json()
    assert not any(summary.get(k, {}).get("verified") for k in lots)
    assert fresh.post(f"/api/bulk/{bulk['id']}/undo", headers=PRIYA).status_code == 409


def test_bulk_disposition_reports_refusals(fresh):
    run = fresh.get("/api/checks", headers=PRIYA).json()
    errors = [f["id"] for f in run["findings"] if f["severity"] == "error" and f["status"] == "open"]
    warns = [f["id"] for f in run["findings"] if f["severity"] == "warning" and f["status"] == "open"]
    r = fresh.post("/api/bulk/disposition", json={"finding_ids": errors + warns[:2], "disposition": "not_an_issue",
                                                  "note": "batch"}, headers=PRIYA).json()
    assert r["applied"] == 2 and len(r["refused"]) == len(errors)  # preparers can't wave off errors
