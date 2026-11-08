"""The Infostud probe's counts (Wave 4, c): pure, offline. It decides nothing and prints no ad content."""

from providers import infostud_probe


def row(n, title, position=""):
    return {"externalId": n, "title": title, "standardizedPosition": position}


def test_counts_tiers_reasons_and_overlap_per_category():
    it = [row(1, "Product Manager"), row(2, "IT Project Manager"), row(3, "Cashier"), row(4, "Junior Product Manager")]
    marketing = [row(4, "Junior Product Manager"), row(5, "Sales Agent"), row(6, "Brand Manager")]
    out = infostud_probe.summarize({5: (it, 4), 48: (marketing, 3)})
    a, b = out["categories"][5], out["categories"][48]
    assert (a["target"], a["near"], a["excluded"]) == (1, 1, 2) and a["readMatchesReported"] is True
    assert a["excludedBy"] == {"title_not_matched": 1, "title_excluded": 1}
    assert (b["target"], b["near"], b["excluded"]) == (0, 0, 3) and b["excludedBy"] == {"title_not_matched": 1, "title_excluded": 2}
    assert out["distinctAds"] == 6 and out["inMoreThanOneCategory"] == 1 and out["sumOfReported"] == 7


def test_a_short_read_is_visible_and_the_combined_query_is_compared():
    it = [row(1, "Product Manager"), row(2, "Cashier")]
    out = infostud_probe.summarize({5: (it, 3)}, combined=(it[:1], 2))
    assert out["categories"][5]["readMatchesReported"] is False
    assert out["combined"] == {
        "reported": 2, "read": 1, "readMatchesReported": False, "sameAdsAsTheCategoriesTogether": False, "onlyInCombined": 0, "onlyInCategories": 1,
    }


def test_the_output_holds_no_title():
    out = infostud_probe.summarize({5: ([row(1, "Secret Title Product Manager", "Product Manager")], 1)})
    assert "Secret" not in repr(out) and out["categories"][5]["relevantPositions"] == {"Product Manager": 1}
