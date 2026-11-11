"""Serbian title wording in the title tiers (Latin with and without diacritics, Cyrillic); no provider, no real data."""

import pytest

from role_tier import NEAR, UNRELATED, title_tier

EVIDENCE = "Owns the product roadmap"
PRODUCT_FACTS = {"roleTrack": "product_management", "roleTrackEvidence": EVIDENCE}
DELIVERY_FACTS = {"roleTrack": "project_delivery", "roleTrackEvidence": "Runs delivery"}

# A product role in Serbian words: near, on the title alone (role_score is the neutral 45 that a Serbian title gets).
SERBIAN_PRODUCT = [
    "Menadžer proizvoda",
    "Menadzer proizvoda",
    "МЕНАЏЕР ПРОИЗВОДА",
    "Менаџер производа",
    "Menadžerka proizvoda",
    "Menadžer digitalnih proizvoda",
    "Menadžer za proizvod",
    "Senior menadžer proizvoda (m/ž)",
    "Vlasnik proizvoda",
    "Власник производа",
    "Vlasnik digitalnog proizvoda",
    "Rukovodilac proizvoda",
    "Руководилац производа",
    "Direktor proizvoda",
    "Директор производа",
    "Potreban menadžer proizvoda u Nišu",
    "Upravljanje proizvodom",
    "Управљање производом",
    "Lider digitalne platforme za finansije",
    "Lider proizvoda",
    "Лидер платформе",
]

# A Serbian project or delivery manager: judged by function, exactly as the English titles.
SERBIAN_PROJECT = [
    "Menadžer projekata",
    "Menadzer projekata",
    "Menadžer za upravljanje projektima",
    "Menadzer za upravljanje projektima",
    "Менаџер пројеката",
    "Менаџер за управљање пројектима",
    "Projektni menadžer",
    "Projektni menadzer",
    "Projekt menadžer",
    "Пројектни менаџер",
    "Rukovodilac projekta",
    "Руководилац пројекта",
    "Rukovodilac IT projekata",
    "Voditelj projekta",
    "Upravljanje projektima",
    "Управљање пројектима",
    "Menadžer isporuke",
    "Projektni menadžer – rukovodilac građevinskog projekta",
]

# Serbian wording that must reach neither branch: a bare "lider" / "menadžer", other functions, production, sales.
SERBIAN_NEITHER = [
    "Lider tima",
    "Menadžer",
    "Menadžer prodaje",
    "Menadžer proizvodnje",
    "Direktor proizvodnje",
    "Menadžer ljudskih resursa",
    "Менаџер продаје",
    "Лидер тима",
    "Programer",
    "Rukovodilac gradilišta",
]


@pytest.mark.parametrize("title", SERBIAN_PRODUCT)
def test_a_serbian_product_title_is_near(title):
    assert title_tier(title, 45, "product") == NEAR
    assert title_tier(title, 45, "product", {}) == NEAR


@pytest.mark.parametrize("title", SERBIAN_PROJECT)
def test_a_serbian_project_title_without_facts_stays_unrelated(title):
    assert title_tier(title, 45, "product") == UNRELATED
    assert title_tier(title, 45, "product", {}) == UNRELATED
    assert title_tier(title, 45, "product", {"roleTrack": "product_management", "roleTrackEvidence": " "}) == UNRELATED


@pytest.mark.parametrize("title", SERBIAN_PROJECT)
def test_a_serbian_project_title_with_product_evidence_is_near(title):
    assert title_tier(title, 45, "product", PRODUCT_FACTS) == NEAR
    assert title_tier(title, 45, "product", {"roleTrack": "product_ownership", "roleTrackEvidence": EVIDENCE}) == NEAR


@pytest.mark.parametrize("title", SERBIAN_PROJECT)
def test_a_serbian_project_title_with_a_delivery_track_stays_unrelated(title):
    assert title_tier(title, 45, "product", DELIVERY_FACTS) == UNRELATED


@pytest.mark.parametrize("title", SERBIAN_NEITHER)
def test_other_serbian_wording_is_unrelated(title):
    assert title_tier(title, 45, "product", PRODUCT_FACTS) == UNRELATED


def test_a_serbian_project_equivalent_treats_the_facts_like_its_english_twin():
    for serbian, english in [("Menadžer projekata", "Project Manager"), ("Менаџер пројеката", "Delivery Manager")]:
        for facts in (None, {}, PRODUCT_FACTS, DELIVERY_FACTS):
            assert title_tier(serbian, 45, "product", facts) == title_tier(english, 45, "product", facts)


@pytest.mark.parametrize(
    ("title", "score", "expected"),
    [
        ("Senior Product Manager", 95, "target"),
        ("Product Owner", 80, "target"),
        ("Technical Program Manager", 45, NEAR),
        ("Director of Product, Ecosystem", 45, NEAR),
        ("Product Operations Manager", 45, NEAR),
        ("Platform Product Domain Lead", 45, NEAR),
        ("Manager, Product Platform", 65, NEAR),
        ("Senior Product Designer", 45, UNRELATED),
        ("Senior Product Design Manager", 65, UNRELATED),
        ("Head of Product Marketing", 45, UNRELATED),
        ("Platform Lead", 45, UNRELATED),
        ("Team Lead", 45, UNRELATED),
        ("Production Manager", 45, UNRELATED),
        ("Senior Software Engineer", 45, UNRELATED),
        ("Technical Project Manager", 45, UNRELATED),
        ("Project Manager - Rukovodilac gradilišta", 45, UNRELATED),
    ],
)
def test_english_titles_keep_their_tier(title, score, expected):
    assert title_tier(title, score, "product", {}) == expected


def test_english_project_titles_keep_their_fact_rule():
    assert title_tier("Technical Project Manager", 45, "product", PRODUCT_FACTS) == NEAR
    assert title_tier("Project Manager - Rukovodilac gradilišta", 45, "product", PRODUCT_FACTS) == NEAR
    assert title_tier("Delivery Manager", 45, "product", DELIVERY_FACTS) == UNRELATED
