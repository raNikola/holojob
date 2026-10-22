"""Serbian boards spell places both ways; a failed match is silent."""

from text_utils import contains_any, fold_accents, normalize_text


def test_nis_with_and_without_diacritic_compare_equal():
    assert normalize_text("Niš") == normalize_text("Nis") == "nis"


def test_other_serbian_letters_fold():
    assert fold_accents("Đorđe Čačak Žabalj") == "Dorde Cacak Zabalj"


def test_contains_any_ignores_case_and_diacritics():
    assert contains_any("Remote - NIŠ, Serbia", ["nis"])
    assert contains_any("Nis, Serbia", ["Niš"])


def test_contains_any_is_false_for_other_cities():
    assert not contains_any("Belgrade, Serbia", ["Niš"])


def test_html_is_stripped_and_entities_unescaped():
    assert normalize_text("<p>Ni&scaron;</p>") == "nis"
