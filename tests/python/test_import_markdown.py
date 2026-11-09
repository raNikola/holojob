"""Wave 7 S2: TXT / MD files go through the same parser after the Markdown markup is removed."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from profile_import.markdown_text import to_plain
from profile_import.text_parser import TextImportError, parse_text

ROOT = Path(__file__).resolve().parents[2]

MARKDOWN = """# Jane Sample

jane@example.invalid | +1 555 010 0100 | [Site](https://example.invalid/jane)

## Summary

Product leader with **10+ years** shipping *B2B* software.

## Experience

### Head of Product — Northwind
April 2024 – Present
- Grew ARR by **40%**.
- Built the `payments` roadmap.

### Analyst, Beta Corp
2016 – 2019
+ Wrote weekly reports.

## Skills

Roadmapping, SQL, snake_case_names

## Education

BSc Economics, University of Springfield, 2012
"""

PLAIN = """Jane Sample
jane@example.invalid

Summary
Product leader with 10+ years shipping B2B software.

Experience
Head of Product — Northwind
April 2024 – Present
- Grew ARR by 40%.

Skills
Roadmapping, SQL

Education
BSc Economics, University of Springfield, 2012
"""


class TestToPlain:
    def test_headings_lose_their_hashes_and_setext_underlines_go(self):
        assert to_plain("# A\n## B ##\nC\n====\nD\n---") == "A\nB\nC\nD"

    def test_emphasis_code_and_links_keep_the_words(self):
        out = to_plain("**bold** and *it* and __b2__ and _i2_ and `code` and ~~gone~~ [label](https://e.invalid/x) ![alt](https://e.invalid/i.png)")
        assert out == "bold and it and b2 and i2 and code and gone label https://e.invalid/x alt"

    def test_underscores_and_stars_inside_words_are_not_emphasis(self):
        assert to_plain("snake_case_name and 2*3*4 and a_b") == "snake_case_name and 2*3*4 and a_b"

    def test_list_markers_stay_for_the_parser_and_plus_becomes_a_dash(self):
        assert to_plain("- a\n* b\n1. c\n+ d") == "- a\n* b\n1. c\n- d"

    def test_tables_become_lines_and_separators_disappear(self):
        assert to_plain("| Role | Years |\n|---|---|\n| PM | 5 |") == "Role | Years\nPM | 5"

    def test_fences_and_quotes_and_html_are_removed_but_their_content_stays(self):
        assert to_plain("```\ncode line\n```\n> quoted <b>x</b>\n<!-- c -->y") == "code line\nquoted x\ny"

    def test_a_plain_text_file_passes_through_unchanged(self):
        assert to_plain(PLAIN) == PLAIN.replace("\r", "")

    def test_a_non_string_is_returned_for_the_parser_to_refuse(self):
        assert to_plain(None) is None and to_plain(5) == 5


class TestTextFileSource:
    def test_markdown_and_plain_text_give_the_same_reading(self):
        md = parse_text(MARKDOWN, "text_file")
        assert md["source"] == "text_file"
        assert md["basicProfile"]["email"] == "jane@example.invalid"
        assert md["summary"].startswith("Product leader with 10+ years")
        entries = md["parsedData"]["experienceDetail"]
        assert [e["company"] for e in entries][:1] == ["Northwind"]
        assert entries[0]["bullets"][:1] == ["Grew ARR by 40%."]
        assert "Roadmapping" in md["parsedData"]["skills"]
        assert "snake_case_names" in md["parsedData"]["skills"]
        assert md["parsedData"]["education"] and "Springfield" in md["parsedData"]["education"][0]
        assert "**" not in md["rawText"] and "##" not in md["rawText"]

    def test_plain_text_reads_like_paste(self):
        a, b = parse_text(PLAIN, "text_file"), parse_text(PLAIN, "paste")
        for key in ("basicProfile", "summary", "parsedData", "languages", "links", "confidence"):
            assert a[key] == b[key]

    def test_the_other_sources_do_not_strip_markup(self):
        assert "**" in parse_text("**Skills**\nSQL", "paste")["rawText"]

    def test_empty_after_stripping_is_the_empty_code(self):
        for text in ("---\n***", "```\n```", "   \n"):
            with pytest.raises(TextImportError) as err:
                parse_text(text, "text_file")
            assert err.value.code == "empty"

    def test_the_size_limit_still_applies(self):
        with pytest.raises(TextImportError) as err:
            parse_text("a" * (200 * 1024 + 10), "text_file")
        assert err.value.code == "too_large"

    def test_the_runner_accepts_the_source_and_prints_nothing_to_stderr(self):
        done = subprocess.run([sys.executable, "-I", str(ROOT / "python/profile_import/run_text_import.py")],
                              input=json.dumps({"text": MARKDOWN, "source": "text_file"}), capture_output=True, text=True)
        assert json.loads(done.stdout)["ok"] is True and done.stderr == ""

    def test_markup_cannot_smuggle_an_identifier_past_the_scrub(self):
        draft = parse_text("# Skills\n[mail](mailto:hidden@canary-3.invalid) **hidden2@canary-3.invalid**\nSQL", "text_file")
        body = json.dumps({k: v for k, v in draft.items() if k not in ("basicProfile", "links", "rawText")})
        assert "canary-3" not in body
