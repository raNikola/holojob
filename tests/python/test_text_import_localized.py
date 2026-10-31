"""The paste parser on CVs with Serbian headings, and the shared heading vocabulary."""

import json
from pathlib import Path

import pytest

from profile_import import vocabulary
from profile_import.text_parser import parse_text

SECTIONS_FILE = Path(__file__).resolve().parents[2] / "src" / "data" / "sectionHeadings.json"
DATA = json.loads(SECTIONS_FILE.read_text(encoding="utf-8"))
TO_CYRILLIC = {latin: cyr for cyr, latin in DATA["transliteration"]["cyrillicToLatin"].items()}

LATIN = """LIČNI PODACI
Ime i prezime: Marija Testić
Telefon: 064 123 4567
E-pošta: marija.testic@example.invalid
Adresa: Ulica Primer 1, Niš

OBRAZOVANJE:
- Diplomirani pedagog, Filozofski fakultet Niš, 2013
- Medicinska sestra-tehničar, srednja medicinska škola, 2007

RADNO ISKUSTVO:
- Stručni saradnik-pedagog, OŠ "Primer", Niš, 2024
- Učiteljica u produženom boravku, OŠ "Uzorak", Niš, 2025

STRUČNO USAVRŠAVANJE (izbor):
- Tehnike terapije igrom, 2025
- Agile Scrum Practitioner, 2019

DODATNA ZNANJA I VEŠTINE:
- Rad na računaru: MS Office, Google Cloud, SPSS Statistics, Canva
- Jezici: engleski (srednji), nemački (početni)

HOBI:
Planinarenje, čitanje.
"""

CYRILLIC = """ЛИЧНИ ПОДАЦИ
Име и презиме: Марија Тестић
Телефон: 064 123 4567

ОБРАЗОВАЊЕ:
- Дипломирани педагог, Филозофски факултет Ниш, 2013

РАДНО ИСКУСТВО:
- Стручни сарадник-педагог, ОШ Пример, Ниш, 2024

ВЕШТИНЕ:
- Agile, Scrum

ЈЕЗИЦИ:
- енглески (средњи)
"""


def to_cyrillic(text: str) -> str:
    out, i = [], 0
    while i < len(text):
        for size in (2, 1):
            chunk = text[i : i + size]
            if chunk in TO_CYRILLIC:
                out.append(TO_CYRILLIC[chunk])
                i += size
                break
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def spellings(phrase: str) -> list[str]:
    folded = vocabulary.fold_text(phrase)
    return [phrase, phrase.upper(), folded, to_cyrillic(folded)]


def test_every_section_phrase_in_the_file_is_recognised_in_four_spellings():
    for lang in DATA["languages"].values():
        for key, phrases in lang["sections"].items():
            for phrase in phrases:
                for spelling in spellings(phrase):
                    assert vocabulary.SECTION_OF.get(vocabulary.normalize_phrase(spelling)) == key, (key, spelling)
        for phrase in lang["unplacedSections"]:
            for spelling in spellings(phrase):
                assert vocabulary.normalize_phrase(spelling) in vocabulary.UNPLACED_HEADERS, spelling


def test_fold_and_labels():
    assert vocabulary.fold_text("VEŠTINE") == "vestine" == vocabulary.fold_text("ВЕШТИНЕ")
    assert vocabulary.normalize_phrase("Znanja & veštine") == vocabulary.normalize_phrase("Znanja i veštine")
    assert vocabulary.labeled_field("Ime i prezime: Marija Testić") == ("fullName", "Marija Testić")
    assert vocabulary.labeled_field("Име и презиме: Марија") == ("fullName", "Марија")
    assert vocabulary.labeled_field("Broj telefona: 064 1") == ("phone", "064 1")
    assert vocabulary.labeled_field("Phone: 1") == ("phone", "1")
    assert vocabulary.labeled_field("Random note: x") is None
    assert vocabulary.ends_with_label("Telefon: ", "phone")
    assert not vocabulary.ends_with_label("Kontakttelefon ", "email")


class TestLatinSerbianCv:
    draft = parse_text(LATIN)

    def test_name_comes_from_the_labelled_line_not_the_section_title(self):
        assert self.draft["basicProfile"]["fullName"] == "Marija Testić"

    def test_contact_fields_are_read_from_serbian_labels(self):
        basic = self.draft["basicProfile"]
        assert basic["phone"] == "064 123 4567"
        assert basic["email"] == "marija.testic@example.invalid"
        assert basic["location"] == "Ulica Primer 1, Niš"

    def test_sections_are_placed(self):
        data = self.draft["parsedData"]
        assert len(data["education"]) == 2
        assert len(data["workExperience"]) == 2
        assert data["certifications"] == ["Tehnike terapije igrom, 2025", "Agile Scrum Practitioner, 2019"]
        assert "MS Office" in data["skills"]

    def test_languages_inside_the_skills_block_are_read_as_languages(self):
        assert self.draft["languages"] == [
            {"language": "engleski", "proficiency": "intermediate"},
            {"language": "nemački", "proficiency": "basic"},
        ]
        assert not any("Jezici" in s for s in self.draft["parsedData"]["skills"])

    def test_hobbies_are_set_aside_not_filed_under_another_section(self):
        assert any(u["label"].lower() == "hobi" for u in self.draft["unplaced"])
        assert "Planinarenje" not in json.dumps(self.draft["parsedData"], ensure_ascii=False)

    def test_headings_are_recognised_so_there_is_no_unrecognised_warning(self):
        assert not any("No section headings" in w for w in self.draft["warnings"])


def test_cyrillic_cv_reads_the_same_way():
    draft = parse_text(CYRILLIC)
    assert draft["basicProfile"]["fullName"] == "Марија Тестић"
    assert draft["basicProfile"]["phone"] == "064 123 4567"
    assert len(draft["parsedData"]["education"]) == 1
    assert len(draft["parsedData"]["workExperience"]) == 1
    assert draft["parsedData"]["skills"] == ["Agile", "Scrum"]
    assert draft["languages"] == [{"language": "енглески", "proficiency": "intermediate"}]


def test_an_unlabelled_name_under_the_personal_heading_is_still_the_name():
    draft = parse_text("LIČNI PODACI\nMarija Testić\nmarija@example.invalid\n\nOBRAZOVANJE:\n- Pedagog, 2013")
    assert draft["basicProfile"]["fullName"] == "Marija Testić"


def test_english_labels_and_headings_still_work():
    draft = parse_text("Jane Sample\nPhone: +1 415 555 0132\nLocation: Springfield, Ohio\n\nSkills\n- SQL, Jira")
    assert draft["basicProfile"]["fullName"] == "Jane Sample"
    assert draft["basicProfile"]["phone"] == "+1 415 555 0132"
    assert draft["basicProfile"]["location"] == "Springfield, Ohio"
    assert draft["parsedData"]["skills"] == ["SQL", "Jira"]
