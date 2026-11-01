"""The entry-header recogniser of the import parser: one header string -> title / company / place.

The expectations come from what each line means, not from what the parser printed. A line the evidence
cannot decide stays whole in Title with confidence "low" and a warning (DECISIONS: no guessing)."""

import pytest

from profile_import.text_parser import parse_text, split_entry_header

# header, title, company, location
DECIDED = [
    # a) the families named in the task
    ("Senior Product Manager, ACME SOFTWARE | Remote", "Senior Product Manager", "ACME SOFTWARE", "Remote"),
    ("Head of Product, Northwind Software | Belgrade, Serbia", "Head of Product", "Northwind Software", "Belgrade, Serbia"),
    ("Senior Product Manager, Acme | Belgrade", "Senior Product Manager", "Acme", "Belgrade"),
    ("Product Manager at Acme Corp", "Product Manager", "Acme Corp", ""),
    ("Product Manager @ Acme Corp", "Product Manager", "Acme Corp", ""),
    ("Product Manager - Acme Corp", "Product Manager", "Acme Corp", ""),
    ("Product Manager – Acme Corp", "Product Manager", "Acme Corp", ""),
    ("Product Manager — Acme Corp", "Product Manager", "Acme Corp", ""),
    ("Product Manager | Acme Corp", "Product Manager", "Acme Corp", ""),
    ("Product Manager (Acme Corp)", "Product Manager", "Acme Corp", ""),
    ("Product Manager, Acme Inc.", "Product Manager", "Acme Inc.", ""),
    ("Product Manager, Acme Corp, Berlin, Germany", "Product Manager", "Acme Corp", "Berlin, Germany"),
    # the company first
    ("Acme Corp | Product Manager", "Product Manager", "Acme Corp", ""),
    ("Acme Corp – Product Manager", "Product Manager", "Acme Corp", ""),
    ("Acme Corp (Product Manager)", "Product Manager", "Acme Corp", ""),
    ("Northwind Software – Head of Product", "Head of Product", "Northwind Software", ""),
    # dots and remarks beside a title
    ("Product Manager · Acme Corp · Full-time", "Product Manager", "Acme Corp", ""),
    ("Product Manager | Acme Corp | Remote", "Product Manager", "Acme Corp", "Remote"),
    ("Product Manager | Acme Corp, Belgrade, Serbia", "Product Manager", "Acme Corp", "Belgrade, Serbia"),
]

# header, expected title kept whole
UNDECIDED = [
    "Product Manager, Payments",  # a team after a comma is not a company
    "Director of Sales, EMEA",  # a region is not a company
    "Acme Corp – Globex Ltd",  # two names, no role word
    "Product Manager - Engineering Manager",  # two roles
    "Product Manager, Acme",  # a bare comma with no other evidence
]


@pytest.mark.parametrize(("header", "title", "company", "location"), DECIDED)
def test_decided_headers(header, title, company, location):
    result = split_entry_header(header)
    assert (result.title, result.company, result.location) == (title, company, location)
    assert result.level == "medium"


@pytest.mark.parametrize("header", UNDECIDED)
def test_undecided_headers_stay_whole_and_low(header):
    result = split_entry_header(header)
    assert (result.title, result.company, result.location, result.level) == (header, "", "", "low")


def test_a_title_alone_is_a_title():
    result = split_entry_header("Senior Product Manager")
    assert (result.title, result.company) == ("Senior Product Manager", "")


def entries(*header_lines: str, date_after: bool = True):
    body = "\n".join(f"{h}\nJan 2020 – Present\n• Did the work." if date_after else f"Jan 2020 – Present {h}\n• Did the work." for h in header_lines)
    return parse_text(f"EXPERIENCE\n{body}")


def test_an_undecided_line_warns_by_entry_number():
    draft = entries("Product Manager, Payments")
    entry = draft["parsedData"]["experienceDetail"][0]
    assert entry["title"] == "Product Manager, Payments" and entry["company"] == ""
    assert draft["confidence"]["experienceDetail.0"] == "low"
    assert any("Experience entry 1" in w for w in draft["warnings"])
    assert not any("Payments" in w for w in draft["warnings"])  # warnings never repeat CV text


def test_a_title_alone_does_not_warn():
    draft = entries("Senior Product Manager")
    assert draft["confidence"]["experienceDetail.0"] == "low"
    assert not any("Experience entry" in w for w in draft["warnings"])


def test_a_comma_split_in_one_entry_loosens_the_others_in_the_section():
    draft = entries("Product Manager, Acme Inc.", "QA Engineer, Globex")
    first, second = draft["parsedData"]["experienceDetail"]
    assert (first["title"], first["company"]) == ("Product Manager", "Acme Inc.")
    assert (second["title"], second["company"]) == ("QA Engineer", "Globex")


def test_without_that_evidence_a_lone_comma_line_stays_whole():
    draft = entries("QA Engineer, Globex")
    entry = draft["parsedData"]["experienceDetail"][0]
    assert (entry["title"], entry["company"]) == ("QA Engineer, Globex", "")


def test_two_header_lines_are_ordered_by_the_role_word():
    for first, second in (("Acme Corp", "Product Manager"), ("Product Manager", "Acme Corp")):
        draft = parse_text(f"EXPERIENCE\n{first}\n{second}\nJan 2020 – Present\n• Did the work.")
        entry = draft["parsedData"]["experienceDetail"][0]
        assert (entry["title"], entry["company"]) == ("Product Manager", "Acme Corp")


def test_a_weak_role_word_does_not_make_a_company_a_title():
    draft = parse_text("EXPERIENCE\nNorthwind Software\nHead of Product\nJan 2020 – Present\n• Did the work.")
    entry = draft["parsedData"]["experienceDetail"][0]
    assert (entry["title"], entry["company"]) == ("Head of Product", "Northwind Software")


def test_a_parenthetical_after_the_dates_is_a_note_not_a_company():
    text = "EXPERIENCE\nProduct Manager, Acme Inc.\nApril 2024 – Present | (US-based remote startup)\n• Did the work."
    entry = parse_text(text)["parsedData"]["experienceDetail"][0]
    assert (entry["title"], entry["company"]) == ("Product Manager", "Acme Inc.")
    assert entry["description"] == "US-based remote startup"


def test_a_parenthetical_place_after_the_dates_is_the_location():
    text = "EXPERIENCE\nProduct Manager | Acme Inc.\nApril 2024 – Present (Remote)\n• Did the work."
    entry = parse_text(text)["parsedData"]["experienceDetail"][0]
    assert entry["location"] == "Remote" and entry["description"] == ""


def test_dates_in_brackets_leave_no_empty_brackets():
    entry = parse_text("EXPERIENCE\nAcme Corp – Product Manager (Jan 2020 – Present)\n• Did the work.")["parsedData"]["experienceDetail"][0]
    assert (entry["title"], entry["company"], entry["start"], entry["end"]) == ("Product Manager", "Acme Corp", "Jan 2020", "Present")
