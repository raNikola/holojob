"""The curation report and the baseline, on fictional frames."""

import json

import pytest

from match_engine import competency_report as report
from match_engine.competencies import alias_index

COMPS = [
    {"id": "team-spirit", "definition": "Works well in a team; not leadership.", "kind": "skill",
     "aliases": ["team spirit", "strong team spirit"]},
    {"id": "map-reading", "definition": "Reading maps; not drawing them.", "kind": "skill",
     "aliases": ["map reading"]},
]


def req(text, rid="prov:abc", kind="skill"):
    return {"id": rid, "text": text, "kind": kind, "importance": "must"}


FRAMES = {
    "ad1": [req("Strong team spirit"), req("Plays the kazoo"), req("python", rid="python")],
    "ad2": [req("strong team spirit."), req("Plays the kazoo"), req("Map reading")],
    "ad3": [req("Plays the kazoo!"), req("Teem spirit")],
    "ad4": [],
}


def test_only_provisional_requirements_are_grouped_by_alias_key():
    groups = report.provisional_groups(FRAMES)
    assert "python" not in groups
    spirit = groups["strong team spirit"]
    assert spirit["occurrences"] == 2 and spirit["ads"] == {"ad1", "ad2"}
    assert set(spirit["wordings"]) == {"Strong team spirit", "strong team spirit."}


def test_baseline_counts_exact_alias_matches():
    groups = report.provisional_groups(FRAMES)
    assert report.baseline(groups, alias_index(COMPS)) == {
        "occurrences": 7, "occurrencesResolved": 3,
        "distinctTexts": 5, "distinctTextsResolved": 2,
        "ads": 3, "adsWithAResolved": 2,
    }


def test_baseline_of_nothing_is_zero():
    assert report.baseline({}, {}) == dict.fromkeys(
        ["occurrences", "occurrencesResolved", "distinctTexts", "distinctTextsResolved", "ads", "adsWithAResolved"], 0)


def test_closest_is_a_near_alias_or_nothing():
    index = alias_index(COMPS)
    near = report.closest("team spirt", index)
    assert near["competency"] == "team-spirit" and near["similarity"] >= report.NEAR_THRESHOLD
    assert report.closest("plays the kazoo", index) is None


def test_report_groups_are_frequent_ranked_and_labelled():
    rep = report.build_report(FRAMES, COMPS, min_ads=2)
    texts = [g["text"] for g in rep["groups"]]
    assert texts == ["plays the kazoo", "strong team spirit"]
    kazoo, spirit = rep["groups"]
    assert kazoo["ads"] == 2 and kazoo["status"] == "new candidate" and kazoo["closest"] is None
    assert spirit["status"] == "alias" and spirit["closest"]["competency"] == "team-spirit"
    assert kazoo["examples"][0] == "Plays the kazoo"
    assert rep["baseline"]["occurrencesResolved"] == 3


def test_min_ads_one_lists_near_candidates_too():
    rep = report.build_report(FRAMES, COMPS, min_ads=1)
    by_text = {g["text"]: g for g in rep["groups"]}
    assert by_text["teem spirit"]["status"] == "near"
    assert by_text["teem spirit"]["closest"]["competency"] == "team-spirit"


def test_report_never_writes_outside_data():
    with pytest.raises(SystemExit):
        report.checked_out_path(report.ROOT / "docs" / "report.json")
    assert report.checked_out_path(report.DEFAULT_OUT) == report.DEFAULT_OUT.resolve()


def test_main_prints_counts_only_and_writes_the_file(tmp_path, monkeypatch, capsys):
    frames = tmp_path / "frames.json"
    frames.write_text(json.dumps(FRAMES), encoding="utf-8")
    data = tmp_path / "data"
    monkeypatch.setattr(report, "DATA_DIR", data)
    monkeypatch.setattr(report.competencies, "load", lambda family: COMPS)
    out = data / "r.json"
    assert report.main(["--frames", str(frames), "--out", str(out), "--min-ads", "2"]) == 0
    printed = capsys.readouterr().out
    assert "3 of 7" in printed and "kazoo" not in printed
    assert json.loads(out.read_text(encoding="utf-8"))["groups"]


def test_main_refuses_an_invalid_list(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(report.competencies, "load", lambda family: [{"id": "Bad Id"}])
    assert report.main(["--frames", str(tmp_path / "none.json"), "--out", str(report.DATA_DIR / "x.json")]) == 1
    assert not (report.DATA_DIR / "x.json").exists()


def test_review_lists_every_competency_in_order_with_header_counts():
    comps = [*COMPS, {"id": "kid", "definition": "A child; not the parent.", "kind": "domain",
                      "parent": "map-reading", "aliases": ["kid one", "kid two"]}]
    md = report.review_markdown(comps, "fiction")
    assert "4 competencies" not in md and "3 competencies, 5 aliases." in md
    assert md.index("## team-spirit") < md.index("## map-reading") < md.index("## kid")
    kid = md[md.index("## kid"):]
    assert "- Kind: domain" in kid and "- Parent: map-reading" in kid
    assert "- Definition: A child; not the parent." in kid and "  - kid two" in kid
    assert "Parent" not in md[: md.index("## kid")]


def test_write_review_refuses_outside_data_and_invalid_lists(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(report.competencies, "load", lambda family: COMPS)
    with pytest.raises(SystemExit):
        report.write_review("fiction", tmp_path / "elsewhere.md")
    out = report.write_review("fiction", tmp_path / "data" / "r.md")
    assert out.read_text(encoding="utf-8").startswith("# Competency review: fiction")
    monkeypatch.setattr(report.competencies, "load", lambda family: [{"id": "Bad Id"}])
    with pytest.raises(SystemExit):
        report.write_review("fiction", tmp_path / "data" / "r2.md")
    assert not (tmp_path / "data" / "r2.md").exists()


def test_candidates_are_the_most_frequent_uncovered_groups_with_their_closest():
    frames = {
        "ad1": [req("Plays the kazoo"), req("Strong team spirit"), req("Team spirited people"), req("Folds maps")],
        "ad2": [req("plays the kazoo."), req("Folds maps"), req("Map readin")],
        "ad3": [req("Plays the kazoo"), req("Plays the kazoo!"), req("Juggles")],
    }
    rows = report.candidate_rows(frames, COMPS, limit=2)
    assert [r["text"] for r in rows] == ["plays the kazoo", "folds maps"]
    assert rows[0]["ads"] == 3 and rows[0]["examples"][0] == "Plays the kazoo"
    assert len(rows[0]["examples"]) <= 3 and rows[0]["closest"] is None
    everything = {r["text"]: r for r in report.candidate_rows(frames, COMPS)}
    assert "strong team spirit" not in everything and "map readin" not in everything
    assert everything["team spirited people"]["closest"]["competency"] == "team-spirit"
    assert 0 < everything["team spirited people"]["closest"]["similarity"] <= 1


def test_candidates_file_is_written_under_data_only(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "DATA_DIR", tmp_path / "data")
    frames = {"ad1": [req("Plays the kazoo")], "ad2": [req("Plays the kazoo")]}
    with pytest.raises(SystemExit):
        report.write_candidates(frames, COMPS, tmp_path / "elsewhere.md")
    out = report.write_candidates(frames, COMPS, tmp_path / "data" / "c.md")
    text = out.read_text(encoding="utf-8")
    assert "## plays the kazoo" in text and "- Ads: 2" in text and "- Closest: none" in text
    with pytest.raises(SystemExit):
        report.write_candidates(frames, [{"id": "Bad Id"}], tmp_path / "data" / "c2.md")
    assert not (tmp_path / "data" / "c2.md").exists()
