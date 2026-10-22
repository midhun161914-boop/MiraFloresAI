"""The check suite as regression tests — every planted error must surface as a
computed finding, and every independent re-computation must hold."""

import pytest

PRIYA = {"X-Actor-Id": "st-01"}
DANIEL = {"X-Actor-Id": "st-02"}
MARCUS = {"X-Actor-Id": "st-04"}


@pytest.fixture(scope="module")
def run(client):
    return client.get("/api/checks", headers=PRIYA).json()


def finding(run, code, contains=""):
    hits = [f for f in run["findings"] if f["code"] == code and contains in f["id"] + f["title"]]
    assert hits, f"no {code} finding containing {contains!r}"
    return hits[0]


# ------------------------------------------------------------------ planted errors → findings
def test_broker_mismatch_is_explained_by_unread_page_with_tax_effect(run):
    f = finding(run, "BROKER_SUMMARY_DETAIL_MISMATCH")
    assert f["severity"] == "error" and "250.00" in f["title"]
    assert any("M18" in x and "proceeds 250.00" in x and "(60.00)" in x for x in f["facts"])
    assert f["tax_effect"]["change"] == -60.0 and f["tax_effect"]["category"] == "stcg"
    assert f["tax_effect"]["federal_tax"] == round(-60 * 0.348)
    assert "doc:D31#page32" in f["refs"] and f["engine_diagnostic"] == "BROKER_SUMMARY_DETAIL_MISMATCH"


def test_duplicate_w2_counted_once(run):
    f = finding(run, "DUPLICATE_DOCUMENT", "D10")
    assert f["status"] == "resolved" and "D09" in f["title"]


def test_duplicate_interest_detected_by_shared_account(run):
    f = finding(run, "DUPLICATE_INCOME_LINE")
    assert "SchB.1.1" in f["lines"] and "SchB.1.2" in f["lines"] and "7731" in f["summary"]
    assert f["tax_effect"]["change"] == -1840


def test_rsu_zero_basis_uses_supplemental_statement(run):
    f = finding(run, "ZERO_BASIS_WITH_KNOWN_BASIS")
    assert f["severity"] == "error" and f["tax_effect"]["change"] == -47620
    assert {"F8949.B.N1", "F8949.B.N3", "F8949.E.N4"} <= set(f["lines"])
    assert "ca_source_income" in f["tax_effect"]["basis"]  # N1, N3 sold during CA residency


def test_crypto_missing_basis_is_an_upper_bound(run):
    f = finding(run, "DIGITAL_ASSET_BASIS_MISSING")
    assert f["tax_effect"]["bound"] == "upper_bound" and f["engine_diagnostic"] == "DIGITAL_ASSET_BASIS_MISSING"


def test_questionnaire_conflicts(run):
    sales = finding(run, "QUESTIONNAIRE_SALES_CONFLICT", "sales")
    assert "282" in sales["title"] and "qa-14" in sales["refs"]
    assert finding(run, "QUESTIONNAIRE_CONFLICT", "ira")


def test_low_confidence_read_has_alternative_reading_effect(run):
    f = finding(run, "LOW_CONFIDENCE_READ", "ev-1049")
    assert "SchA.11" in f["lines"] and f["tax_effect"]["change"] == 6000  # 1,500 vs 7,500


def test_ein_misread_is_flagged(run):
    f = finding(run, "READ_NOT_ON_PAGE", "ev-1045")
    assert f["severity"] == "warning" and "F2441.1b" in f["lines"]


def test_payments_disagree_with_agency_records(run):
    fed = finding(run, "ESTIMATED_PAYMENTS_MISMATCH")
    assert fed["tax_effect"]["federal_balance_due"] == 1000
    ca = finding(run, "CA_ESTIMATED_PAYMENTS_MISMATCH")
    assert ca["tax_effect"]["california_balance_due"] == 3500 and any("tax year 2024" in x for x in ca["facts"])


def test_fx_wrong_year(run):
    f = finding(run, "FX_RATE_WRONG_YEAR")
    assert f["lines"] == ["SchB.1.6"] and "2025" in f["title"]


def test_outside_filings_and_due_diligence(run):
    assert finding(run, "FBAR_OUTSIDE_RETURN")["engine_diagnostic"] == "FBAR_OUTSIDE_RETURN"
    nec = finding(run, "FORM_1099_FILING")
    assert "Mara Quintero" in nec["summary"] and "Dev Patel" in nec["summary"]
    assert finding(run, "DUE_DILIGENCE_REQUIRED")
    filings = {o["filing"] for o in run["outside_filings"]}
    assert any("FBAR" in x for x in filings) and any("Arizona" in x for x in filings)


def test_basis_findings(run):
    assert finding(run, "DISTRIBUTIONS_EXCEED_BASIS")
    assert finding(run, "BASIS_GAP", "partnership")
    scorp = next(c for c in run["checks"] if c["id"] == "RECON_SCORP_BASIS")
    assert scorp["metrics"]["recomputed_beginning_2025"] == scorp["metrics"]["F7203.1"] == 2300


# ------------------------------------------------------------------ independent checks
@pytest.mark.parametrize("check_id", ["IND_8949_CROSSFOOT", "IND_DEPRECIATION", "IND_SUPERSEDED", "COMP_DOCUMENTS"])
def test_independent_checks_pass(run, check_id):
    assert next(c for c in run["checks"] if c["id"] == check_id)["status"] == "pass"


def test_footing_explains_incomplete_inputs(run):
    foot = next(c for c in run["checks"] if c["id"] == "IND_FOOTING")
    assert foot["metrics"]["not_reproduced"] == 0
    f = finding(run, "INPUTS_INCOMPLETE", "SchCA540NR.1.D")
    assert "SchCA540NR.1.C" in f["lines"]


def test_engine_diagnostics_cross_referenced(run):
    covered = {d["code"] for d in run["engine_diagnostics"] if d["covered_by"]}
    assert {"BROKER_SUMMARY_DETAIL_MISMATCH", "DIGITAL_ASSET_BASIS_MISSING", "QUESTIONNAIRE_SALES_CONFLICT",
            "LOW_CONFIDENCE_READ", "FORM_1099_FILING", "FBAR_OUTSIDE_RETURN", "DUE_DILIGENCE_REQUIRED"} <= covered
    assert run["counts"]["engine_missed"] >= 8


# ------------------------------------------------------------------ variance + areas
def test_variance_applies_firm_rule_exactly(client):
    v = client.get("/api/variance", headers=PRIYA).json()
    assert v["rule"] == {"compare_to": "prior_year", "flag_if_change_over_percent": 10.0, "and_over_amount": 1000.0}
    wages = next(f for f in v["flags"] if f["line"] == "F1040.1a")
    assert wages["pct"] == 36.1 and wages["prior"] == 156039
    for f in v["flags"]:
        assert abs(f["delta"]) > 1000 and (f["pct"] is None or abs(f["pct"]) > 10)


def test_eight_areas_with_owner_and_status(client):
    h = client.get("/api/return-health", headers=PRIYA).json()
    assert [a["name"] for a in h["areas"]] == ["Wages & stock comp", "Investments & digital assets", "Business",
                                              "Rentals & sale", "Pass-throughs & basis", "Deductions & credits",
                                              "California", "Payments"]
    inv = next(a for a in h["areas"] if a["id"] == "investments")
    assert inv["status"] == "attention" and inv["findings_error"] >= 3 and inv["owner"]["name"] == "Priya Raman"
    ca = next(a for a in h["areas"] if a["id"] == "california")
    assert ca["prior"] == 12520  # vs the 2024 resident CA540.64


# ------------------------------------------------------------------ dispositions are events with rules
def test_dispositions(fresh):
    run = fresh.get("/api/checks", headers=PRIYA).json()
    fid = next(f["id"] for f in run["findings"] if f["code"] == "ESTIMATED_PAYMENTS_MISMATCH")
    r = fresh.post(f"/api/findings/{fid}/disposition", json={"disposition": "not_an_issue", "note": "x"}, headers=PRIYA)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "REVIEW_REQUIRED"
    r = fresh.post(f"/api/findings/{fid}/disposition", json={"disposition": "accepted", "note": ""}, headers=PRIYA)
    assert r.status_code == 403
    r = fresh.post(f"/api/findings/{fid}/disposition",
                   json={"disposition": "accepted", "note": "Will claim 12,000 per transcript (M5 adjustment)."}, headers=PRIYA)
    assert r.status_code == 200
    f = next(x for x in fresh.get("/api/checks", headers=PRIYA).json()["findings"] if x["id"] == fid)
    assert f["status"] == "accepted" and f["disposition"]["actor"] == "st-01"
    assert fresh.post("/api/variance/F1040.1a/explain", json={"text": "New job at Halvorsen from June."},
                      headers=PRIYA).status_code == 200
    w = next(x for x in fresh.get("/api/variance", headers=PRIYA).json()["flags"] if x["line"] == "F1040.1a")
    assert w["explanation"]["text"].startswith("New job")


def test_checks_masked_for_uncleared(client):
    import re
    body = client.get("/api/checks", headers=MARCUS).text
    assert not re.search(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)", body)


def test_cross_form_prior_pairing_requires_matching_labels(client):
    """540NR and the 2024 resident 540 share some line numbers but not all: line 32 is
    California AGI on the 540NR and exemption credits on the 540. Never compare those."""
    flags = {f["line"]: f for f in client.get("/api/variance", headers=PRIYA).json()["flags"]}
    assert "F540NR.32" not in flags
    assert "CA540.64" in flags["F540NR.64"]["label"]
