"""Filing lifecycle: extension, pre-file gate, 8879, e-file reject → fix → accept, freeze, amend,
Letter 566 response, carry-forward. All rules are server-side."""

from tests.test_changes import DANIEL, HELEN, PRIYA

NGOZI = {"X-Actor-Id": "cu-01"}
ERIK = {"X-Actor-Id": "cu-02"}
MARCUS = {"X-Actor-Id": "st-04"}


def gate(c):
    return c.get("/api/filing/gate", headers=PRIYA).json()


def complete_dd(c):
    qs = c.get("/api/filing", headers=PRIYA).json()["diligence_questions"]
    for item in ("ctc", "odc"):
        r = c.post(f"/api/filing/diligence/{item}", json={"answers": {q: True for q in qs},
                   "note": "Interviewed Ngozi 2026-07-01; Theo 8, Ada 19 student; SSA cards in file."}, headers=PRIYA)
        assert r.status_code == 200, r.text


def clear_gate(c):
    errs = [f["id"] for f in c.get("/api/checks", headers=PRIYA).json()["findings"]
            if f["severity"] == "error" and f["status"] == "open"]
    r = c.post("/api/bulk/disposition", json={"finding_ids": errs, "disposition": "accepted",
                                              "note": "Accepted; reviewed with partner."}, headers=PRIYA)
    assert r.status_code == 200, r.text
    complete_dd(c)
    assert c.post("/api/review/signoffs", json={"node": "return", "level": "reviewer"}, headers=DANIEL).status_code == 200
    assert c.post("/api/review/signoffs", json={"node": "return", "level": "partner"}, headers=HELEN).status_code == 200
    g = gate(c)
    assert g["clear"], g["blockers"]


def authorize(c):
    assert c.post("/api/filing/present", json={"note": "Final"}, headers=DANIEL).status_code == 200
    for who in (NGOZI, ERIK):
        r = c.post("/api/client/filing/approve", json={"pin": "24680", "agree": True}, headers=who)
        assert r.status_code == 200, r.text
    assert c.post("/api/filing/ero-sign", json={"note": ""}, headers=HELEN).status_code == 200


def test_extension_uses_packet_estimate(fresh):
    v = fresh.get("/api/filing/extension", headers=PRIYA).json()
    assert v["federal"]["paid_with_form_4868"] == 36000 and v["federal"]["recomputed_payment"] == 36000
    assert v["california"]["recomputed_payment"] == 0
    assert fresh.post("/api/filing/extension", json={"note": "x"}, headers=PRIYA).status_code == 403   # reviewer files
    r = fresh.post("/api/filing/extension", json={"note": "Form 4868 with 36,000"}, headers=DANIEL)
    assert r.status_code == 200 and r.json()["filed"]["federal_payment"] == 36000
    assert fresh.post("/api/filing/extension", json={"note": "again"}, headers=DANIEL).status_code == 409


def test_gate_blocks_until_everything_is_clear(fresh):
    g = gate(fresh)
    kinds = {b["kind"] for b in g["blockers"]}
    assert {"error_finding", "missing_signoff", "due_diligence"} <= kinds
    assert fresh.post("/api/filing/present", json={}, headers=DANIEL).json()["detail"]["code"] == "GATE_BLOCKED"
    # a blocking note blocks too
    fresh.post("/api/review/notes", json={"node": "F1040.1a", "text": "Tie W-2s", "blocking": True}, headers=DANIEL)
    assert any(b["kind"] == "blocking_note" for b in gate(fresh)["blockers"])


def test_due_diligence_needs_every_answer(fresh):
    r = fresh.post("/api/filing/diligence/ctc", json={"answers": {}, "note": "n"}, headers=PRIYA)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "INCOMPLETE"
    r = fresh.post("/api/filing/diligence/eic", json={"answers": {}, "note": "n"}, headers=PRIYA)
    assert r.status_code == 409   # not claimed


def test_full_lifecycle_reject_fix_accept_freeze_amend_notice(fresh):
    clear_gate(fresh)
    # clients can't approve before presentation; staff can't approve for them
    assert fresh.post("/api/client/filing/approve", json={"pin": "24680", "agree": True}, headers=NGOZI).status_code == 409
    authorize(fresh)
    assert fresh.post("/api/filing/ero-sign", json={}, headers=HELEN).status_code == 409
    f = fresh.get("/api/filing", headers=PRIYA).json()
    assert f["stage"] == "authorized"
    assert any(not c["match"] for c in f["tin_checks"])      # Theo: return 3309 vs card 3390

    # transmit → the packet's reject
    assert fresh.post("/api/filing/transmit", headers=PRIYA).status_code == 403   # preparer can't transmit
    f = fresh.post("/api/filing/transmit", headers=DANIEL).json()
    fed = [s for s in f["submissions"] if s["jurisdiction"] == "federal"][0]
    assert fed["status"] == "rejected" and fed["response"]["errors"][0]["code"] == "R0000-504-02"
    assert [s for s in f["submissions"] if s["jurisdiction"] == "california"][0]["status"] == "not_transmitted"

    # fix from the SSA card; uncleared staff can't
    body = {"person": "theo", "evidence": "ev-1080", "reason": "R0000-504-02; SSN per Social Security card D71."}
    assert fresh.post("/api/filing/identity", json=body, headers=MARCUS).json()["detail"]["code"] == "CLEARANCE"
    r = fresh.post("/api/filing/identity", json=body, headers=PRIYA)
    assert r.status_code == 200 and all(c["match"] for c in r.json()["tin_checks"])

    # resubmit → accepted → frozen
    f = fresh.post("/api/filing/transmit", headers=DANIEL).json()
    assert f["stage"] == "filed"
    acc = {s["jurisdiction"]: s["id"] for s in f["submissions"] if s["status"] == "accepted"}
    assert acc == {"federal": "71530420261950019871", "california": "71530420261950019872"}
    filed = fresh.get("/api/filing/filed", headers=PRIYA).json()
    assert filed["intact"] and filed["figures"]["federal"]["total_tax"] == 81962

    # frozen: no adjustments, corrections or verifications on the filed return
    fx = next(x for x in fresh.get("/api/checks", headers=PRIYA).json()["findings"] if x["code"] == "FX_RATE_WRONG_YEAR")
    r = fresh.post(f"/api/adjustments/from-finding/{fx['id']}", json={"reason": "late"}, headers=PRIYA)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "FROZEN"
    r = fresh.post("/api/review/verify", json={"node": "F1040.1a", "method": "recalculated"}, headers=PRIYA)
    assert r.json()["detail"]["code"] == "FROZEN"

    # amendment on top
    amd = fresh.post("/api/amendments", json={"reason": "Duplicate interest line found after filing."}, headers=PRIYA).json()
    dup = next(x for x in fresh.get("/api/checks", headers=PRIYA).json()["findings"] if x["code"] == "DUPLICATE_INCOME_LINE")
    a = fresh.post(f"/api/amendments/{amd['id']}/from-finding/{dup['id']}", json={"reason": "Remove duplicate SchB line."},
                   headers=PRIYA).json()
    row = a["rows"][0]
    assert row["key"] == "SchB.1.2" and row["corrected"] == 0 and row["as_filed"] > 0 and row["net_change"] < 0
    assert a["intact_base"]
    assert fresh.post(f"/api/amendments/{amd['id']}/approve", json={"note": "ok"}, headers=PRIYA).status_code == 403
    assert fresh.post(f"/api/amendments/{amd['id']}/approve", json={"note": "Agreed."}, headers=HELEN).json()["status"] == "approved"
    # the filed record is untouched
    again = fresh.get("/api/filing/filed", headers=PRIYA).json()
    assert again["snapshot_hash"] == filed["snapshot_hash"] and again["intact"]

    # Letter 566
    resp = fresh.post("/api/notices/N-2025-L566/assemble", headers=PRIYA).json()
    items = resp["record"]["items"]
    assert len(items) == 2
    assert any(line["key"] == "SchA.12" for line in items[0]["lines"])
    rec = items[1]["reconciliation"]
    assert rec["reported"] == 163700 and rec["irs_1099_nec"] == 142000 and rec["irs_1099_k"] == 12400
    assert rec["bridge_total"] == 163700 and rec["file_agrees_with_irs"] and rec["books_revenue"] == 151300
    assert items[1]["lines"][0]["evidence"] and "page" in items[1]["lines"][0]["evidence"][0]
    assert fresh.post("/api/notices/N-2025-L566/sent", json={"note": "Faxed"}, headers=PRIYA).status_code == 403

    # carry forward
    cf = fresh.get("/api/carryforward", headers=PRIYA).json()
    mtc = next(r for r in cf["federal"] if r["key"] == "minimum_tax_credit_from_2025_amt")
    assert mtc["out_2026"] == 3871 and mtc["changes"]
    assert cf["planning"]["estimates"]["federal"]["installments"][0]["due"] == "2026-04-15"
    assert fresh.post("/api/carryforward/roll", json={"note": "2026 file"}, headers=PRIYA).json()["rolled"]


def test_client_approval_goes_stale_when_return_changes(fresh):
    clear_gate(fresh)
    assert fresh.post("/api/filing/present", json={"note": "Final"}, headers=DANIEL).status_code == 200
    fx = next(x for x in fresh.get("/api/checks", headers=PRIYA).json()["findings"] if x["code"] == "FX_RATE_WRONG_YEAR")
    fresh.post(f"/api/adjustments/from-finding/{fx['id']}", json={"reason": "2025 rate."}, headers=PRIYA)
    r = fresh.post("/api/client/filing/approve", json={"pin": "24680", "agree": True}, headers=NGOZI)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "CHANGED"


def test_staff_cannot_use_client_approval(fresh):
    assert fresh.post("/api/client/filing/approve", json={"pin": "24680", "agree": True}, headers=DANIEL).status_code == 403
    assert fresh.get("/api/filing", headers=NGOZI).status_code == 403
