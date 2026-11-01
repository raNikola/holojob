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
    "linkedin_multi_role": {
        "source": "linkedin_pdf",
        "entries": [
            ("Head of Product", "Northwind Software", "Remote", "April 2024", "Present", 1),
            ("Senior Product Manager", "Northwind Software", "Remote", "June 2021", "March 2024", 1),
        ],
    },
    "linkedin_three_roles": {
        "source": "linkedin_pdf",
        "entries": [
            ("Chief Product Officer", "Northwind Software", "Remote", "January 2025", "Present", 1),
            ("Head of Product", "Northwind Software", "Remote", "April 2022", "December 2024", 1),
            ("Product Manager", "Northwind Software", "Remote", "September 2019", "March 2022", 1),
        ],
    },
    "linkedin_two_companies": {
        "source": "linkedin_pdf",
        "entries": [
            ("Head of Product", "Northwind Software", "Remote", "April 2024", "Present", 1),
            ("Senior Product Manager", "Globex Corp", "Belgrade, Serbia", "June 2021", "March 2024", 1),
            ("Product Manager", "Globex Corp", "Belgrade, Serbia", "March 2020", "May 2021", 1),
        ],
    },
    # Layouts the parser does not read yet. Each is a strict xfail below, so a fix shows up as a failure to remove the mark.
    "date_first_no_suffix": {
        "entries": [
            ("Product Manager", "Northwind", "", "2021", "Present", 1),
            ("Business Analyst", "Globex", "", "2016", "2021", 1),
        ],
    },
    "company_above_title_below": {
        "entries": [
            ("Head of Product", "Northwind Software", "", "April 2024", "Present", 1),
            ("Senior Product Manager", "Globex Corp", "", "June 2021", "March 2024", 1),
        ],
    },
}

KNOWN_FAILING: dict[str, str] = {
    "date_first_no_suffix:entries": "'Title, Company' beside the dates with no legal suffix and no pipe place stays whole in Title (low, warned): a bare comma is not enough evidence",
    "company_above_title_below:entries": "company above the dates and title below them (a mixed layout): the title line under the dates is read as description",
}


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


@pytest.mark.parametrize("name", [n for n in cases("entries") if f"{n.values[0]}:entries" not in KNOWN_FAILING])
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


SUMMARIES = {
    "title_comma_company_pipe": "Product leader with 12 years in B2B software. Builds teams and ships platforms that customers pay for.",
    "linkedin_pdf": "Product leader with 12 years in B2B software. Builds teams and ships platforms.",
    "two_column_flattened": "Product leader with 12 years in B2B software.",
    "company_dash_title_dates": "Product leader with 12 years in B2B software.",
    "no_bullets": "Product leader with 12 years in B2B software.",
}


@pytest.mark.parametrize("name", [pytest.param(n, id=n) for n in SUMMARIES])
def test_summary_fills_its_own_field_under_any_heading(name):
    """Summary, Profile, About and About me all name the section; wrapped lines are one paragraph."""
    draft = load(name)
    assert draft["summary"] == SUMMARIES[name]
    assert not [u for u in draft["unplaced"] if "product leader" in u["text"].lower()]


def test_a_blank_line_is_a_paragraph_break_in_the_summary():
    draft = parse_text("SUMMARY\nFirst paragraph line one\nline two.\n\nSecond paragraph.\n\nEXPERIENCE\nHead of Product | Acme Corp\nJan 2020 – Present\n• Did it.")
    assert draft["summary"] == "First paragraph line one line two.\nSecond paragraph."


def test_no_summary_section_means_an_empty_summary():
    draft = load("date_first")
    assert draft["summary"] == "" and "summary" not in draft["confidence"]


# (degree, school, year) of each education entry
EDUCATION = {
    "title_comma_company_pipe": [("B. Sc. Software Engineering", "", "2016"), ("M.Sc. Computer Science", "Springfield University", "2018")],
    "linkedin_pdf": [("Bachelor of Science, Software Engineering", "Springfield University", "2012 - 2016")],
    "date_first": [("Software Engineering", "Springfield University", "2016")],
    "two_column_flattened": [("Bachelor of Science", "Springfield University", "2012 - 2016")],
    "company_dash_title_dates": [("BSc Software Engineering", "Springfield University", "2016")],
    "no_bullets": [("B.Sc. Software Engineering", "", "2016")],
}


@pytest.mark.parametrize("name", [pytest.param(n, id=n) for n in EDUCATION])
def test_education_is_read_into_degree_school_and_year(name):
    detail = load(name)["parsedData"]["educationDetail"]
    assert [(d["degree"], d["school"], d["year"]) for d in detail] == EDUCATION[name]


@pytest.mark.parametrize("name", [pytest.param(n, id=n) for n in EDUCATION])
def test_every_education_line_is_kept_as_text_and_matches_its_detail(name):
    parsed = load(name)["parsedData"]
    assert [d["text"] for d in parsed["educationDetail"]] == parsed["education"]


EDUCATION_LINES = [
    ("B. Sc. Software Engineering | 2016", "B. Sc. Software Engineering", "", "2016"),
    ("B.Sc. Software Engineering | 2016", "B.Sc. Software Engineering", "", "2016"),
    ("BSc, Springfield University, 2016", "BSc", "Springfield University", "2016"),
    ("MBA — Springfield Business School (2019)", "MBA", "Springfield Business School", "2019"),
    ("Springfield University | BSc Software Engineering | 2012 - 2016", "BSc Software Engineering", "Springfield University", "2012 - 2016"),
    ("Springfield University", "", "Springfield University", ""),
    ("Master of Arts, Philosophy, Northwind College, 2011", "Master of Arts, Philosophy", "Northwind College", "2011"),
]


@pytest.mark.parametrize(("line", "degree", "school", "year"), EDUCATION_LINES)
def test_education_line_table(line, degree, school, year):
    from profile_import.text_parser import split_education

    got = split_education(line)
    assert (got["degree"], got["school"], got["year"]) == (degree, school, year)
    assert "undecided" not in got


@pytest.mark.parametrize("line", ["MSc Physics, MIT, 2014", "Some Course, Another Thing"])
def test_an_education_line_that_does_not_fall_into_place_leaves_degree_and_school_empty(line):
    from profile_import.text_parser import split_education

    got = split_education(line)
    assert got["undecided"] and got["degree"] == "" and got["school"] == ""
    assert got["text"] == line  # the line itself is kept as text
    assert got["year"] == ("2014" if "2014" in line else "")


def test_a_degree_with_spaced_initials_is_placed_under_a_combined_heading():
    text = "EDUCATION & CERTIFICATIONS\nB. Sc. Software Engineering | 2016\nCertified Scrum Product Owner (CSPO), Scrum Alliance, 2019"
    draft = parse_text(text)
    assert draft["parsedData"]["education"] == ["B. Sc. Software Engineering | 2016"]
    assert len(draft["parsedData"]["certifications"]) == 1
    assert not [u for u in draft["unplaced"] if "Education" in u["label"]]


def test_an_undecided_education_line_warns_by_entry_number_without_quoting_it():
    draft = parse_text("EDUCATION\nMSc Physics, MIT, 2014")
    assert draft["confidence"]["educationDetail.0"] == "low"
    assert any(w.startswith("Education entry 1") for w in draft["warnings"])
    assert not any("MIT" in w for w in draft["warnings"])


def test_a_duration_line_is_not_a_company():
    entries = load("linkedin_multi_role")["parsedData"]["experienceDetail"]
    assert entries[0]["title"] == "Head of Product" and entries[0]["company"] == "Northwind Software"


@pytest.mark.parametrize(("name", "inherited"), [("linkedin_multi_role", [1]), ("linkedin_three_roles", [1, 2]), ("linkedin_two_companies", [2])])
def test_an_inherited_company_is_medium_and_noted(name, inherited):
    draft = load(name)
    notes = [w for w in draft["warnings"] if w.startswith("Company of experience entry")]
    assert len(notes) == len(inherited)
    for k in inherited:
        assert draft["confidence"][f"experienceDetail.{k}"] == "medium"
        assert any(f"entry {k + 1} " in w for w in notes)


def test_roles_without_a_duration_line_do_not_inherit_a_company():
    text = "Experience\nNorthwind Software\nHead of Product\nApril 2024 - Present\n• A.\nSenior Product Manager\nJune 2021 - March 2024\n• B.\nLinkedIn"
    entries = parse_text(text, "linkedin_pdf")["parsedData"]["experienceDetail"]
    assert entries[1]["company"] == ""
