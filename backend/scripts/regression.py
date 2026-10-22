"""End-to-end regression over HTTP, covering every area, against a running app with a FRESH event store.

    python backend/scripts/regression.py http://localhost:8000
    python backend/scripts/regression.py http://localhost:8080      # the Docker container

Standard library only, so it runs from any Python. Prints one line per check and exits
non-zero on the first failure. It writes events, so point it at a throwaway store.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]  # consoles without UTF-8
BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
PRIYA, DANIEL, HELEN, MARCUS, NGOZI, ERIK = "st-01", "st-02", "st-03", "st-04", "cu-01", "cu-02"
passed = 0


def call(method: str, path: str, who: str | None = PRIYA, body: object | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else (b"{}" if method == "POST" else None)
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", **({"X-Actor-Id": who} if who else {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            ctype = r.headers.get("content-type", "")
            return r.status, json.loads(raw) if "json" in ctype else raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw.decode("utf-8", "replace")


def get(path: str, who: str | None = PRIYA) -> object:
    code, body = call("GET", path, who)
    assert code == 200, f"GET {path} → {code} {str(body)[:200]}"
    return body


def post(path: str, body: object | None = None, who: str = PRIYA, expect: int = 200) -> object:
    code, out = call("POST", path, who, body)
    assert code == expect, f"POST {path} as {who} → {code}, expected {expect}: {str(out)[:300]}"
    return out


def refused(path: str, body: object | None, who: str, code_: str) -> None:
    code, out = call("POST", path, who, body)
    assert code in (403, 409) and out["detail"]["code"] == code_, f"{path} as {who}: expected {code_}, got {code} {out}"


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  ✓ {label}")


def section(t: str) -> None:
    print(f"\n{t}")


def main() -> None:
    q = urllib.parse.quote
    section("Packet, resolver, serving")
    assert get("/api/health", None)["status"] == "ok"
    ov = get("/api/overview")
    assert ov["counts"]["documents"] == 74 and ov["counts"]["extracted_values"] == 3012 and len(ov["versions"]) == 3
    ok("packet loads: 74 documents, 3,012 values, 3 versions")
    r = get("/api/resolve?ref=ev-1080")
    assert r["found"] and r["document_id"] == "D71" and r["page"] == 1 and r["position"]
    ok("resolve_ref → {document_id, page, position}")
    code, html = call("GET", "/filing", None)
    assert code == 200 and "<div id=\"root\">" in str(html)
    ok("UI served, SPA deep link /filing → index.html")

    section("Trace both ways")
    t = get("/api/lines/F1040.1a")
    assert t["sources"], "F1040.1a has sources"
    ok(f"F1040.1a traces to {len(t['sources'])} source(s)")
    land = get("/api/documents/D31/landing")
    assert land["status"] in ("lands", "lands_indirectly", "superseded", "duplicate", "partial", "not_extracted", "support_only", "not_used")
    ok(f"D31 landing: {land['status']}")

    section("Review layer, roles, persistence")
    v = post("/api/review/verify", {"node": "F1040.1a", "method": "agreed_to_source_document", "note": "W-2s tie"})
    refused("/api/review/signoffs", {"node": "F1040.1a", "level": "reviewer"}, PRIYA, "ROLE")
    s = post("/api/review/signoffs", {"node": "F1040.1a", "level": "reviewer"}, DANIEL)
    ok("preparer verifies, reviewer signs; preparer can't sign as reviewer")
    ev_id = next(x["ref"] for x in t["sources"] if x["ref"].startswith("ev-"))
    val = get(f"/api/values/{ev_id}")
    post("/api/review/corrections", {"ev": ev_id, "to": (val["value"] or 0) + 1, "reason": "regression: reopen test"})
    so = next(x for x in get("/api/review/queue")["reopened_signoffs"] if x["id"] == s["id"])
    ok(f"correcting {ev_id} reopened the reviewer sign-off ({so['status']})")
    post(f"/api/review/corrections/{ev_id}/revert", {"reason": "regression: undo"})
    post(f"/api/review/signoffs/{s['id']}/withdraw", {}, DANIEL)
    masked = get("/api/values/ev-1080", MARCUS)
    assert "•" in str(masked["value"]) or "•" in str(masked["text_as_read"])
    ok("uncleared staff see the SSN masked")
    code, _ = call("GET", "/api/return-health", NGOZI)
    assert code == 403
    ok("client users are refused firm endpoints")

    section("Health, variance, checks")
    h = get("/api/return-health")
    assert len(h["areas"]) == 8
    chk = get("/api/checks")
    m18 = [f for f in chk["findings"] if f["code"] == "BROKER_SUMMARY_DETAIL_MISMATCH"]
    assert m18 and m18[0]["tax_effect"]
    ok(f"8 areas; {len(chk['checks'])} checks, {len(chk['findings'])} findings incl. the M18 lot")
    assert get("/api/variance")["flags"]
    ok("variance flags present")

    section("Change & versions")
    find = {f["code"]: f for f in chk["findings"]}
    adj = post(f"/api/adjustments/from-finding/{q(find['ZERO_BASIS_WITH_KNOWN_BASIS']['id'])}", {"reason": "RSU basis per supplemental"})
    assert adj["status"] == "pending_partner"
    refused(f"/api/adjustments/{adj['id']}/approve", {"note": "ok"}, DANIEL, "PARTNER_REQUIRED")
    assert post(f"/api/adjustments/{adj['id']}/approve", {"note": "Agreed"}, HELEN)["status"] == "active"
    ok("RSU adjustment needs partner; reviewer refused; partner approves")
    assert post(f"/api/adjustments/from-finding/{q(find['FX_RATE_WRONG_YEAR']['id'])}", {"reason": "2025 rate"})["status"] == "active"
    cmp_ = get("/api/compare?a=v2&b=v3")
    assert cmp_["summary"]["lines_changed"] > 50
    ok(f"compare v2→v3: {cmp_['summary']['lines_changed']} changed lines with reasons")
    est = post("/api/whatif/estimate", {"items": [{"category": "ltcg", "change": -10000}]})
    assert est["kind"] == "ESTIMATE" and est["disclaimer"].startswith("ESTIMATE")
    assert all(a["kind"] == "ENGINE" for a in get("/api/whatif")["alternatives"])
    ok("scripted what-ifs are ENGINE; ad-hoc is labelled ESTIMATE")
    lots = [l["key"] for l in get("/api/versions/v3/lines?form=F8949")["items"] if l["rule"] != "ADJUSTMENT"][:8]
    b = post("/api/bulk/verify", {"nodes": lots, "method": "agreed_to_source_document", "note": "regression"})
    refused(f"/api/bulk/{b['bulk_id']}/undo", None, DANIEL, "UNDO_NOT_ALLOWED")
    assert post(f"/api/bulk/{b['bulk_id']}/undo")["applied"] == b["applied"]
    ok(f"bulk-verified {b['applied']} lots; only the verifier can undo; undone")

    section("Filing & after")
    assert post("/api/filing/extension", {"note": "4868"}, DANIEL)["filed"]["federal_payment"] == 36000
    refused("/api/filing/present", {"note": "x"}, DANIEL, "GATE_BLOCKED")
    ok("extension recorded; pre-file gate blocks presentation")
    open_err = [f["id"] for f in get("/api/checks")["findings"] if f["severity"] == "error" and f["status"] == "open"]
    post("/api/bulk/disposition", {"finding_ids": open_err, "disposition": "accepted", "note": "regression: accepted with partner"}, DANIEL)
    qs = get("/api/filing")["diligence_questions"]
    for item in ("ctc", "odc"):
        post(f"/api/filing/diligence/{item}", {"answers": {x: True for x in qs}, "note": "Interviewed; SSA cards on file"})
    post("/api/review/signoffs", {"node": "return", "level": "reviewer"}, DANIEL)
    post("/api/review/signoffs", {"node": "return", "level": "partner"}, HELEN)
    g = get("/api/filing/gate")
    assert g["clear"], g["blockers"]
    ok("gate cleared: errors dispositioned, 8867 done, reviewer + partner sign-off")
    post("/api/filing/present", {"note": "final"}, DANIEL)
    refused("/api/filing/ero-sign", {"note": ""}, HELEN, "CLIENT_FIRST")
    post("/api/client/filing/approve", {"pin": "24680", "agree": True}, NGOZI)
    post("/api/client/filing/approve", {"pin": "13579", "agree": True}, ERIK)
    post("/api/filing/ero-sign", {"note": ""}, HELEN)
    ok("presented → both taxpayers sign 8879 → ERO signs (order enforced)")
    f = post("/api/filing/transmit", None, DANIEL)
    fed = next(x for x in f["submissions"] if x["jurisdiction"] == "federal")
    assert fed["status"] == "rejected" and fed["response"]["errors"][0]["code"] == "R0000-504-02"
    refused("/api/filing/identity", {"person": "theo", "evidence": "ev-1080", "reason": "x"}, MARCUS, "CLEARANCE")
    post("/api/filing/identity", {"person": "theo", "evidence": "ev-1080", "reason": "R0000-504-02 per D71"})
    f = post("/api/filing/transmit", None, DANIEL)
    assert f["stage"] == "filed"
    ok("R0000-504-02 reject → TIN fixed from D71 → resubmitted → accepted")
    refused(f"/api/adjustments/from-finding/{q(find['DUPLICATE_INCOME_LINE']['id'])}", {"reason": "late"}, PRIYA, "FROZEN")
    filed = get("/api/filing/filed")
    assert filed["intact"]
    ok("frozen: adjustments refused; filed snapshot intact")
    amd = post("/api/amendments", {"reason": "duplicate interest found after filing"})
    a = post(f"/api/amendments/{amd['id']}/from-finding/{q(find['DUPLICATE_INCOME_LINE']['id'])}", {"reason": "remove duplicate"})
    assert a["rows"][0]["corrected"] == 0
    post(f"/api/amendments/{amd['id']}/approve", {"note": "Agreed"}, HELEN)
    assert get("/api/filing/filed")["snapshot_hash"] == filed["snapshot_hash"]
    ok("amendment on top of the frozen return; filed record unchanged")
    resp = post("/api/notices/N-2025-L566/assemble")
    rec = resp["record"]["items"][1]["reconciliation"]
    assert rec["bridge_total"] == rec["reported"] == 163700
    ok("Letter 566 response assembled; Schedule C bridge ties to 163,700")
    assert get("/api/carryforward")["planning"]["estimates"]["federal"]["installments"]
    ok("carry-forward with history and 2026 planning")

    section("Search, budget, status")
    kinds = {x["kind"] for x in get("/api/search?q=" + q("theo"))["groups"]}
    assert "person" in kinds
    kinds = {x["kind"] for x in get("/api/search?q=" + q("zero basis"))["groups"]}
    assert "finding" in kinds
    ok("global search finds people and findings")
    post("/api/time", {"bucket": "business", "hours": 4, "note": "Schedule C tie-out"})
    bud = {x["bucket"]: x for x in get("/api/budget")["buckets"]}
    assert bud["business"]["status"] == "over"
    ok("time vs budget: Business 4h of 3.5h → over")
    st = get("/api/status")
    assert st["stage"] in ("amending", "amend_ready", "notice") and st["filed_snapshot"] == filed["snapshot_hash"]
    ok(f"status: {st['stage_label']} — next: {st['next_step']['label'] if st['next_step'] else '—'}")

    print(f"\nAll {passed} checks passed against {BASE}")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\n  ✗ FAILED: {e}")
        sys.exit(1)
