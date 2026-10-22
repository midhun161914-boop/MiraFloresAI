import pytest

from app.services.refs import all_packet_refs


def test_every_reference_in_the_packet_resolves(idx, resolver):
    refs = all_packet_refs(idx)
    assert len(refs) > 2000
    unresolved = sorted(r for r in refs if not resolver.resolve(r).found)
    assert unresolved == []


@pytest.mark.parametrize(
    "ref, kind",
    [
        ("ev-0035", "extracted_value"),
        ("D09", "document"),
        ("doc:D30#page32", "document_page"),
        ("qa-31", "questionnaire"),
        ("msg-04", "message"),
        ("call-01", "call_note"),
        ("py:/carryovers_into_2025/capital_loss_short", "prior_year"),
        ("py:/return_2024/lines/F8606.14", "prior_year"),
        ("agency:/notices/1", "agency_record"),
        ("asset:AUS-BLDG", "asset"),
        ("household:theo", "person"),
        ("ref:param.salt_cap", "parameter"),
        ("ref:fx.SEK.2025_average", "fx_rate"),
        ("timeline:extension-2026-04-14", "timeline_event"),
        ("timeline:tl-01", "timeline_event"),
        ("v2", "return_version"),
        ("R-W2-BOX1-SUM", "rule"),
        ("F1040.11", "return_line"),
        ("F4562-E.total-A", "return_line"),
    ],
)
def test_each_grammar_form(resolver, ref, kind):
    res = resolver.resolve(ref)
    assert res.found, res.label
    assert res.kind == kind
    assert res.label and res.link


def test_extracted_value_carries_the_trace_contract(resolver):
    res = resolver.resolve("ev-0035")
    assert (res.document_id, res.page) == ("D09", 1)
    assert set(res.position) == {"x0", "y0", "x1", "y1"}
    assert res.link == "/documents/D09?page=1&ev=ev-0035"


def test_unextracted_page_is_explained(resolver):
    res = resolver.resolve("doc:D30#page32")
    assert res.note == "No values were extracted from this page."


def test_json_pointer_escape_and_missing(resolver):
    assert resolver.resolve("py:/does_not_exist").found is False
    assert resolver.resolve("agency:/notices/99").found is False


def test_line_falls_back_to_the_version_that_has_it(idx, resolver):
    removed = [c.key for c in idx.versions["v3"].changes_from_previous if c.change == "removed"]
    added = [c.key for c in idx.versions["v3"].changes_from_previous if c.change == "added"]
    if added:
        res = resolver.resolve(added[0], version="v1")
        assert res.found and res.version == "v3" and "Not in v1" in res.note
    if removed:
        res = resolver.resolve(removed[0])
        assert res.found and res.version != "v3"


def test_alias_and_unknown(resolver):
    res = resolver.resolve("prior_preparer_depreciation_schedule")
    assert res.found and "Alias of" in res.note
    assert resolver.resolve("nonsense").found is False
    assert resolver.resolve("ev-9999").found is False
