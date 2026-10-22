from collections import Counter

from app.services.locate import locate


def test_no_partial_number_match():
    assert locate("1,840.00", "Interest 11,840.00 total").status == "not_found"
    assert locate("1,840.00", "Interest 1,840.00; other 11,840.00").status == "exact"


def test_formatting_variants_from_the_typed_value():
    m = locate("01/10/2020", "M9 Northgate acquired 2020-01-10 sold", "M9_acquired", "", "2020-01-10", "date")
    assert m.status == "exact" and m.matched_text == "2020-01-10" and m.normalized
    m = locate("24,800.00", "SchE.32 Total 24,800; SchE.41", "SchE.32", "", 24800.0, "money")
    assert m.matched_text == "24,800"


def test_box_number_disambiguates_repeated_amounts():
    page = "Box 3 118,000.00; Box 4 7,316.00; Box 5 118,000.00; Box 6 1,711.00"
    m3 = locate("118,000.00", page, "box3", "Box 3 social security wages")
    m5 = locate("118,000.00", page, "box5", "Box 5 Medicare wages")
    assert m3.status == m5.status == "exact"
    assert m3.start < m5.start


def test_lot_identifier_picks_its_own_row():
    page = ("M1 Harbor 50 sh proceeds 6,420.00 wash sale loss disallowed 0.00 long-term covered; "
            "M2 Cascade 80 sh proceeds 3,100.00 wash sale loss disallowed 0.00 long-term covered")
    m = locate("X", page, "M2_covered", "Covered", True, "boolean")
    assert m.status == "exact" and m.start > page.index("M2 ")


def test_real_packet_locates_almost_everything(idx):
    counts = Counter(m.status for m in idx.text_matches.values())
    assert counts["exact"] >= 2900
    # The handwritten 0.41 read is not what the page prints: surfaced, not hidden.
    assert idx.text_matches["ev-1049"].status == "not_found"
