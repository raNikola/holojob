"""The import parser on CV layouts that differ in where the title, company, dates and bullets sit.

Each fixture in tests/python/fixtures/import_layouts is a synthetic CV (invented people and companies,
example.com addresses). The expected values below are written from what each CV says, not from the
parser's output. One test id per layout, so `pytest -v` is the per-layout report; a layout the parser
still gets wrong is marked `xfail(strict=True)` with the reason, so a fix turns it into a failure to
remove the mark."""

from pathlib import Path

import pytest

from profile_import.text_parser import parse_text

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "import_layouts"

# (title, company, location, start, end, number of bullets)
LAYOUTS = {
    "title_comma_company_pipe": {
        "entries": [
            ("Head of Product", "NORTHWIND SOFTWARE", "Remote", "April 2024", "Present", 2),
            ("Senior Product Manager", "GLOBEX CORP", "Belgrade, Serbia", "June 2021", "March 2024", 2),
        ],
    },
    "linkedin_pdf": {
        "source": "linkedin_pdf",
        "entries": [
            ("Head of Product", "Northwind Software", "Remote", "April 2024", "Present", 2),
            ("Senior Product Manager", "Globex Corp", "Belgrade, Serbia", "June 2021", "March 2024", 1),
        ],
    },
    "date_first": {
        "entries": [
            ("Product Manager", "Northwind Corp", "", "2021", "Present", 2),
            ("Business Analyst", "Globex Ltd", "", "2016", "2021", 2),
        ],
    },
    "two_column_flattened": {
        "entries": [
            ("Head of Product", "Northwind Software", "Remote", "April 2024", "Present", 2),
            ("Senior Product Manager", "Globex Corp", "Belgrade, Serbia", "June 2021", "March 2024", 1),
        ],
    },
    "company_dash_title_dates": {
        "entries": [
            ("Head of Product", "Northwind Software", "", "April 2024", "Present", 2),
            ("Senior Product Manager", "Globex Corp", "", "June 2021", "March 2024", 1),
        ],
    },
    "no_bullets": {
        "entries": [
            ("Head of Product", "Northwind Software", "", "April 2024", "Present", 0),
            ("Senior Product Manager", "Globex Corp", "", "June 2021", "March 2024", 0),
        ],
    },
    "bare_markers": {
        "entries": [("Head of Product", "Northwind Software", "", "April 2024", "Present", 5)],
    },
    "title_paren_company": {
        "entries": [
            ("Head of Product", "Northwind Software", "", "April 2024", "Present", 1),
            ("Senior Product Manager", "Globex Corp", "", "June 2021", "March 2024", 1),
        ],
    },
}

KNOWN_FAILING: dict[str, str] = {}


def load(name: str) -> dict:
    spec = LAYOUTS[name]
    return parse_text((FIXTURES / f"{name}.txt").read_text(encoding="utf-8"), spec.get("source", "paste"))


def cases(key: str):
    for name, spec in LAYOUTS.items():
        if key not in spec:
            continue
        marks = [pytest.mark.xfail(strict=True, reason=KNOWN_FAILING[f"{name}:{key}"])] if f"{name}:{key}" in KNOWN_FAILING else []
        yield pytest.param(name, id=name, marks=marks)


@pytest.mark.parametrize("name", cases("entries"))
def test_entries(name):
    entries = load(name)["parsedData"]["experienceDetail"]
    got = [(e["title"], e["company"], e["location"], e["start"], e["end"], len(e["bullets"])) for e in entries]
    assert got == LAYOUTS[name]["entries"]


@pytest.mark.parametrize("name", cases("entries"))
def test_a_decided_layout_has_no_low_entries_and_no_header_warnings(name):
    draft = load(name)
    levels = [draft["confidence"][f"experienceDetail.{i}"] for i in range(len(LAYOUTS[name]["entries"]))]
    assert "low" not in levels
    assert not [w for w in draft["warnings"] if w.startswith("Experience entry")]


def test_the_observed_layout_in_detail():
    first = load("title_comma_company_pipe")["parsedData"]["experienceDetail"][0]
    # the parenthetical after the dates is a note in the description, not the company
    assert first["description"].startswith("US-based growth-stage startup")
    assert "payments suite" in first["description"]
    # the sub-heading closes the description and is not part of it or of a bullet
    assert "Key Outcomes" not in first["description"] + " ".join(first["bullets"])
    # a wrapped line continues its bullet
    assert first["bullets"][0] == "Grew recurring revenue by 40% in 18 months by repricing and a self-service upgrade path."
    assert first["bullets"][1].endswith("kept attrition at zero.")


def test_a_sub_heading_is_reported_as_ignored_not_dropped():
    draft = load("title_comma_company_pipe")
    assert {"name": "Sub-heading: Key Outcomes & Leadership Impact"}.items() <= {"name": draft["ignored"][0]["name"]}.items()


def test_bare_markers_open_the_bullet_on_the_next_line():
    bullets = load("bare_markers")["parsedData"]["experienceDetail"][0]["bullets"]
    assert bullets[0] == "Grew recurring revenue by 40% in 18 months across the payments suite."
    # a capitalised wrapped line right before the next bullet is a continuation, not a sub-heading
    assert bullets[1].endswith("working with the Customer Success Team")
    assert bullets[2:] == ["Introduced quarterly OKRs.", "Moved the roadmap to a public changelog.", "Reported to the CEO and the board."]


def test_without_bullets_the_text_is_the_description():
    entry = load("no_bullets")["parsedData"]["experienceDetail"][0]
    assert entry["bullets"] == []
    assert "Owns the product strategy" in entry["description"] and "Grew recurring revenue" in entry["description"]


def test_a_bullet_starts_only_on_a_marker():
    text = "EXPERIENCE\nHead of Product | Acme Corp\nJan 2020 – Present\n- First point\nSecond line of it\nThird line of it\n- Next point"
    bullets = parse_text(text)["parsedData"]["experienceDetail"][0]["bullets"]
    assert bullets == ["First point Second line of it Third line of it", "Next point"]


@pytest.mark.parametrize("label", ["Key Outcomes:", "Responsibilities", "Selected Achievements & Results"])
def test_sub_headings_close_the_description(label):
    text = f"EXPERIENCE\nHead of Product | Acme Corp\nJan 2020 – Present\nOwned the roadmap.\n{label}\n• Grew revenue by 10%."
    entry = parse_text(text)["parsedData"]["experienceDetail"][0]
    assert entry["description"] == "Owned the roadmap."
    assert entry["bullets"] == ["Grew revenue by 10%."]


@pytest.mark.parametrize("line", ["Led the payments squad", "Owned the roadmap for the billing platform", "Grew revenue by 10 percent."])
def test_ordinary_text_before_a_bullet_is_not_a_sub_heading(line):
    text = f"EXPERIENCE\nHead of Product | Acme Corp\nJan 2020 – Present\n{line}\n• Grew revenue by 10%."
    entry = parse_text(text)["parsedData"]["experienceDetail"][0]
    assert entry["description"] == line


def test_a_wrapped_title_case_line_inside_a_bullet_is_not_a_sub_heading():
    text = "EXPERIENCE\nHead of Product | Acme Corp\nJan 2020 – Present\n• Worked with the\nCustomer Success Team\n• Grew revenue by 10%."
    bullets = parse_text(text)["parsedData"]["experienceDetail"][0]["bullets"]
    assert bullets == ["Worked with the Customer Success Team", "Grew revenue by 10%."]
