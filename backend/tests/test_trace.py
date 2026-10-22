"""Tracing both ways: number -> evidence, number -> math, document -> where it landed."""

import re

import pytest

FULL_SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")


# ------------------------------------------------------------ number -> evidence
def test_wages_trace_to_both_w2_box1_values(client):
    t = client.get("/api/lines/F1040.1a").json()
    assert t["line"]["value"] == 212400
    assert t["rule_text"].startswith("Sum box 1 of each distinct Form W-2")
    srcs = {s["ref"]: s for s in t["sources"]}
    assert set(srcs) == {"ev-0016", "ev-0035"}
    box1 = srcs["ev-0035"]["resolution"]
    # the {document_id, page, position} trace contract, straight from resolve_ref
    assert (box1["document_id"], box1["page"]) == ("D09", 1)
    assert set(box1["position"]) == {"x0", "y0", "x1", "y1"}
    assert box1["link"] == "/documents/D09?page=1&ev=ev-0035"
    ex = srcs["ev-0035"]["excerpt"]
    assert ex["text"][ex["start"]:ex["end"]] == "107,800.00"
    # the two sources add up to the line (independent of the engine)
    assert sum(s["resolution"]["target"]["value"] for s in t["sources"]) == 212400


def test_every_source_of_every_line_resolves(idx, client):
    for ln in idx.current.lines[:: 25]:  # sample across forms; full sweep is in test_refs
        t = client.get(f"/api/lines/{ln.key}").json()
        assert all(s["resolution"]["found"] for s in t["sources"]), ln.key


def test_record_sources_expose_the_evidence_behind_them(client):
    t = client.get("/api/lines/F8606.2").json()
    py = next(s for s in t["sources"] if s["ref"].startswith("py:/return_2024/lines/"))
    assert py["behind"] and py["behind"][0]["resolution"]["document_id"] == "D06"


def test_value_by_version_and_prior_year(client):
    t = client.get("/api/lines/F1040.1a").json()
    assert [b["version"] for b in t["by_version"]] == ["v1", "v2", "v3"]
    assert t["prior_year"]["ref"] == "py:/return_2024/lines/F1040.1a"


# ---------------------------------------------------------------- number -> math
def test_calc_graph_down_reaches_wages_from_total_tax(client):
    g = client.get("/api/lines/F1040.24/graph").json()
    assert g["direction"] == "down" and g["depth"] >= 10
    assert "F1040.1a" in g["nodes"]
    for node in g["nodes"].values():  # closed under inputs
        assert all(i in g["nodes"] for i in node["inputs"])
        assert node["rule"] and node["rule_text"]


def test_calc_graph_up_shows_where_wages_go(client):
    g = client.get("/api/lines/F1040.1a/graph", params={"direction": "up"}).json()
    assert g["nodes"]["F1040.1a"]["used_by"] == ["F1040.1z"]
    assert "F1040.24" in g["nodes"]  # wages roll all the way up to total tax


def test_unknown_line_404(client):
    assert client.get("/api/lines/F9999.1").status_code == 404
    assert client.get("/api/lines/F1040.1a", params={"version": "v9"}).status_code == 404


# ------------------------------------------------------- document -> where it landed
def landing(client, doc):
    return client.get(f"/api/documents/{doc}/landing").json()


def test_w2_lands_in_wages(client):
    land = landing(client, "D09")
    assert land["status"] == "lands"
    assert "F1040.1a" in [x["line"]["key"] for x in land["lines"]]


def test_duplicate_image_is_explained_not_silent(client):
    land = landing(client, "D10")
    assert land["status"] == "duplicate" and land["duplicate_of"] == "D09"
    reason = land["reasons"][0]
    assert reason["code"] == "DUPLICATE" and "F1040.1a" in reason["refs"]


def test_superseded_original_points_to_corrected(client):
    land = landing(client, "D30")
    assert land["status"] == "superseded" and land["replaced_by"] == "D31"
    by = {b["version"]: b for b in land["by_version"]}
    assert by["v1"]["use"] == "used" and by["v1"]["lines"] > 0
    assert by["v3"]["use"] == "superseded" and by["v3"]["lines"] == 0


def test_partial_extraction_names_the_unread_page_and_what_it_prints(client):
    land = landing(client, "D31")
    assert land["status"] == "lands"
    assert land["unread_pages"] == [32]  # filler pages 11-31 are not "unread"
    partial = next(r for r in land["reasons"] if r["code"] == "PARTIAL")
    assert "proceeds 250.00" in partial["detail"]


def test_not_extracted_carries_the_pipeline_reason(client):
    land = landing(client, "D07")
    assert land["status"] == "not_extracted"
    assert "prior_preparer_workpaper" in land["reasons"][0]["detail"]


def test_indirect_landing_through_prior_year_records(client):
    land = landing(client, "D06")
    assert land["status"] == "lands_indirectly"
    assert all(e["via"] for x in land["lines"] for e in x["evidence"])


def test_every_document_has_a_status_and_non_landing_ones_a_reason(idx, client):
    for d in idx.packet.documents:
        land = landing(client, d.id)
        if land["status"] not in ("lands", "lands_indirectly"):
            assert land["reasons"], d.id


def test_values_and_documents_carry_landing_summaries(client):
    v = client.get("/api/values/ev-0035").json()
    assert v["lands_in"] == ["F1040.1a"] or "F1040.1a" in v["lands_in"]
    docs = {d["id"]: d for d in client.get("/api/documents").json()}
    assert docs["D10"]["landing_status"] == "duplicate" and docs["D09"]["lines_fed"] > 0


def test_summary_figures_map_to_their_lines(client):
    v3 = next(v for v in client.get("/api/versions").json() if v["version"] == "v3")
    assert v3["summary_lines"]["federal"]["total_tax"] == "F1040.24"
    assert v3["summary_lines"]["federal"]["agi"] == "F1040.11"


def test_lines_listing_carries_changes(client):
    body = client.get("/api/versions/v3/lines", params={"changed": True}).json()
    assert body["total"] > 0 and all(r["change"] for r in body["items"])
    assert "F1040" in body["forms"]


@pytest.mark.parametrize("path", ["/api/lines/F1040.1a", "/api/documents/D09/landing"])
def test_trace_respects_clearance(client, path):
    body = client.get(path, headers={"X-Actor-Id": "st-04"}).text
    assert not FULL_SSN.search(body)
