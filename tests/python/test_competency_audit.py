"""The mapping audit tool, on fictional ads and a mocked model."""

import json

import pytest

import competency_mapping as cm
import enrich_jobs
import requirement_frames as rf
from match_engine import competency_audit as audit
from match_engine import competency_report as report
from requirement_ids import provisional_id

COMPS = [
    {"id": "kazoo-playing", "definition": "Playing the kazoo; not other wind instruments.", "kind": "skill",
     "aliases": ["kazoo playing"]},
    {"id": "map-reading", "definition": "Reading maps; not drawing them.", "kind": "skill", "aliases": ["map reading"]},
    {"id": "juggling-degree", "definition": "A degree in juggling; not a course.", "kind": "education",
     "aliases": ["juggling degree"]},
]


def ad(n, requirements=True):
    job = {"jobId": f"j{n}", "title": f"Clown {n}", "company": "Circus", "location": "Remote", "description": f"Ad {n}."}
    if requirements:
        job["llmFacts"] = {"requirements": [{"id": "x", "text": "t", "kind": "skill", "importance": "must"}]}
    return job


def item(text, kind="skill", competency=None, covers=None):
    return {"text": text, "kind": kind, "importance": "must", "posting_quote": text,
            "previous_id": None, "competency_id": competency,
            "covers": covers or ("none" if competency in (None, "NONE") else "whole")}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Fictional jobs file, a data dir, a seed for family 'fiction' and a model that replies from a script."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(report, "DATA_DIR", data)
    monkeypatch.setattr(cm.competencies, "load", lambda family: COMPS if family == "fiction" else [])
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({"jobs": [ad(1), ad(2), ad(3, requirements=False), ad(4)]}), encoding="utf-8")
    replies = []

    def complete(prompt, schema=None, model=None, provider=None):
        return {"requirements": replies.pop(0)}

    monkeypatch.setattr(enrich_jobs, "complete_json", complete)
    return type("Env", (), {"data": data, "jobs": jobs, "replies": replies})


def main(env, *extra):
    return audit.main(["--family", "fiction", "--jobs", str(env.jobs), "--workers", "1", *extra])


def test_compound_flag():
    for text in ("Python and SQL", "Agile or Scrum", "B2B/B2C sales", "Python, SQL, R", "  Python  AND SQL"):
        assert audit.looks_compound(text), text
    for text in ("Plays the kazoo", "Android development", "Brandon"):
        assert not audit.looks_compound(text), text


def test_sample_takes_only_extracted_ads_by_seed_in_file_order():
    jobs = [ad(i, requirements=i % 3 != 0) for i in range(30)]
    first = audit.sample_ads(jobs, 5, seed=1)
    assert first == audit.sample_ads(jobs, 5, seed=1)
    assert first != audit.sample_ads(jobs, 5, seed=2)
    assert all(j["llmFacts"] for j in first)
    assert [j["jobId"] for j in first] == sorted((j["jobId"] for j in first), key=lambda s: int(s[1:]))
    assert len(audit.sample_ads(jobs, 500, seed=1)) == 20


def test_without_yes_nothing_is_sent(env, capsys):
    env.replies.append("would fail if popped")
    assert main(env) == 0
    out = capsys.readouterr().out
    assert "6 extraction calls" in out and "(seed 1)" in out and "nothing sent" in out
    assert env.replies == ["would fail if popped"]
    assert not (env.data / audit.AUDIT_NAME).exists()


def test_cost_note_counts_two_calls_per_sampled_ad(env, capsys):
    main(env, "--ads", "2")
    assert "4 extraction calls" in capsys.readouterr().out


def script(env, run1, run2):
    """Replies for two ads in two runs, one list of requirement items per call."""
    env.replies.extend([*run1, *run2])


def test_counts_routes_covers_and_rejections(env, capsys):
    run = [
        [item("Can toot a kazoo", competency="kazoo-playing"), item("Map reading"), item("Python"),
         item("Broad thing", competency="NONE"), item("Kazoo and maps", competency="kazoo-playing", covers="part")],
        [item("Invented", competency="made-up"), item("Knows juggling", competency="juggling-degree"),
         item("Plain thing"), item("Odd", competency="kazoo-playing", covers="none"),
         item("Odder", competency=None, covers="whole")],
    ]
    script(env, run, run)
    assert main(env, "--ads", "2", "--yes") == 0
    out = capsys.readouterr().out
    assert "run 1: 10 requirements" in out and "run 2: 10 requirements" in out
    assert "ids by route: frame 0, alias 1, dictionary 1, model 1, provisional 7" in out
    assert "covers: whole accepted 1, part 1, none 2, inconsistent 2" in out
    assert "rejected: not on the list 1, kind differs 1" in out
    assert "still provisional (including those kept from a previous frame): 7" in out
    assert "picks the kind check refused, by (requirement kind, competency kind), both runs: skill/education 2" in out


def test_stability_counts_same_ids_same_covers_and_mapped_disagreement(env, capsys):
    one = [[item("Can toot a kazoo", competency="kazoo-playing"), item("Stable thing"),
            item("Two things", competency="kazoo-playing", covers="part"), item("Only first")]]
    two = [[item("Can toot a kazoo", competency=None), item("Stable thing"),
            item("Two things", competency="kazoo-playing", covers="part"), item("Only second")]]
    script(env, one, two)
    assert main(env, "--ads", "1", "--yes") == 0
    out = capsys.readouterr().out
    assert "over 3 requirements stated in the same words in both runs (2 stated in only one)" in out
    assert "same id in both runs: 2 (66.7%)" in out
    assert "same covers answer, over 3 suggestions consulted in both: 2 (66.7%)" in out
    assert "runs disagree about mapped vs not mapped: 1 (33.3%)" in out


def test_stability_function_with_nothing_paired():
    class M:
        decisions = []

    run = {"ads": {"a": {"requirements": [{"text": "x", "id": "p:1"}]}}, "mapper": M}
    other = {"ads": {"a": {"requirements": [{"text": "y", "id": "p:2"}]}}, "mapper": M}
    s = audit.stability(run, other)
    assert s["paired"] == 0 and s["unpaired"] == 2 and s["sameIdShare"] is None and s["sameCoversShare"] is None


def test_avoid_seed_gives_a_disjoint_sample():
    jobs = [ad(i) for i in range(100)]
    first = audit.sample_ads(jobs, 30, seed=1)
    second = audit.sample_ads(jobs, 30, seed=2, avoid_seed=1)
    assert len(second) == 30
    assert not {j["jobId"] for j in first} & {j["jobId"] for j in second}
    assert audit.sample_ads(jobs, 30, seed=2) != second
    assert len(audit.sample_ads(jobs[:40], 30, seed=2, avoid_seed=1)) == 10


def live_state(env):
    cm._write(cm.ALIASES_PATH, {"old text": {"competencyId": "map-reading", "status": "pending"}})
    cm._write(cm.REMAP_PATH, {"prov:old": "map-reading"})
    rf.save({rf.frame_key(ad(1)): [{"id": "prov:old", "text": "Old text", "kind": "skill", "importance": "must"}]})
    return {p: p.read_bytes() for p in (cm.ALIASES_PATH, cm.REMAP_PATH, rf.FRAMES_PATH, env.jobs)}


SCRATCH_FILES = {"competency-aliases.json", "requirement-remap.json", "requirement-frames.json", "requirements.json"}


def test_fresh_frames_start_empty_and_leave_the_live_files_untouched(env, monkeypatch):
    live = live_state(env)
    seen = []
    real = enrich_jobs.extract

    def spy(job, model, provider, previous=None, mapper=None):
        seen.append((previous, dict(mapper.learned), dict(mapper.remap)))
        return real(job, model, provider, previous, mapper=mapper)

    monkeypatch.setattr(enrich_jobs, "extract", spy)
    run = [[item("Can toot a kazoo", competency="kazoo-playing")], [item("Plain thing")]]
    script(env, run, [[item("Plain thing")], [item("Plain thing")]])
    assert main(env, "--ads", "2", "--yes") == 0

    assert {p: p.read_bytes() for p in live} == live
    assert [previous for previous, _, _ in seen] == [None] * 4, "no previous frame, even for ads with their own llmFacts"
    assert seen[0][1:] == ({}, {}) and seen[2][1:] == ({}, {}), "each run starts with no aliases and no remap"
    scratch = env.data / "competency-audit-2-scratch"
    assert {p.name for p in (scratch / "run1").iterdir()} == SCRATCH_FILES
    assert {p.name for p in (scratch / "run2").iterdir()} == {"requirement-frames.json", "requirements.json"}
    learned = json.loads((scratch / "run1" / "competency-aliases.json").read_text())
    assert list(learned) == ["can toot a kazoo"] and learned["can toot a kazoo"]["status"] == "pending"
    assert json.loads((scratch / "run1" / "requirement-remap.json").read_text()) == {
        provisional_id("Can toot a kazoo"): "kazoo-playing"}


def test_no_fresh_frames_copies_the_live_state_into_scratch_only(env):
    live = live_state(env)
    run = [[item("Can toot a kazoo", competency="kazoo-playing")], [item("Plain thing")]]
    script(env, run, [[item("Plain thing")], [item("Plain thing")]])
    assert main(env, "--ads", "2", "--yes", "--no-fresh-frames") == 0
    assert {p: p.read_bytes() for p in live} == live
    scratch = env.data / "competency-audit-2-scratch"
    learned = json.loads((scratch / "run1" / "competency-aliases.json").read_text())
    assert "old text" in learned and "can toot a kazoo" in learned
    assert "can toot a kazoo" not in json.loads((scratch / "run2" / "competency-aliases.json").read_text())


def test_live_files_are_not_created_when_absent(env):
    script(env, [[item("Can toot a kazoo", competency="kazoo-playing")]], [[item("Plain thing")]])
    assert main(env, "--ads", "1", "--yes") == 0
    assert not cm.ALIASES_PATH.exists() and not cm.REMAP_PATH.exists() and not rf.FRAMES_PATH.exists()


def test_the_audit_file_has_sections_a_p_b(env):
    run1 = [[item("Can toot a kazoo", competency="kazoo-playing"), item("Maps and charts", competency="map-reading"),
             item("Kazoo for ten years", competency="kazoo-playing", covers="part"),
             item("Map readin"), item("Broad thing", competency="NONE"), item("Python")]]
    script(env, run1, run1)
    assert main(env, "--ads", "1", "--yes") == 0
    text = (env.data / audit.AUDIT_NAME).read_text(encoding="utf-8")
    assert [h for h in text.splitlines() if h.startswith("## ")][0].startswith("## A.")
    a, rest = text.split("## P.")
    p, b = rest.split("## B.")
    assert "1. Can toot a kazoo\n   - Picked: kazoo-playing\n   - Definition: Playing the kazoo; not other wind" in a
    assert "Maps and charts **COMPOUND?**" in a and "Can toot a kazoo **COMPOUND?**" not in a
    assert "Kazoo for ten years" not in a and "Map readin" not in a
    assert "1. Kazoo for ten years\n   - Named: kazoo-playing\n   - Definition: Playing the kazoo" in p
    assert "Map readin\n   - Closest: map-reading (0.9" in b and "Broad thing\n   - Closest:" in b
    assert "Kazoo for ten years\n   - Closest:" in b, "a part answer is still provisional"
    assert "Python" not in b, "a dictionary term is mapped, so it is not an open requirement"


def test_section_limits(env, monkeypatch):
    monkeypatch.setattr(audit, "SECTION_A_LIMIT", 2)
    monkeypatch.setattr(audit, "SECTION_P_LIMIT", 3)
    monkeypatch.setattr(audit, "SECTION_B_LIMIT", 1)
    run1 = [[item(f"Pick {i}", competency="kazoo-playing") for i in range(5)]
            + [item(f"Part {i}", competency="map-reading", covers="part") for i in range(5)]
            + [item(f"Open {i}") for i in range(5)]]
    script(env, run1, run1)
    assert main(env, "--ads", "1", "--yes") == 0
    a, rest = (env.data / audit.AUDIT_NAME).read_text().split("## P.")
    p, b = rest.split("## B.")
    assert a.count("   - Picked:") == 2 and p.count("   - Named:") == 3 and b.count("   - Closest:") == 1


def test_out_names_the_review_file_and_its_scratch_directory(env):
    script(env, [[item("Plain thing")]], [[item("Plain thing")]])
    assert main(env, "--ads", "1", "--yes", "--out", str(env.data / "competency-audit-2b.md")) == 0
    assert (env.data / "competency-audit-2b.md").exists() and (env.data / "competency-audit-2b-scratch" / "run1").is_dir()
    assert not (env.data / audit.AUDIT_NAME).exists()


def test_refuses_to_write_outside_data(env, tmp_path):
    with pytest.raises(SystemExit):
        main(env, "--ads", "1", "--yes", "--out", str(tmp_path / "elsewhere.md"))
    assert not (tmp_path / "elsewhere-scratch").exists() and env.replies == []


def test_an_unknown_family_cannot_be_audited(env, capsys):
    assert audit.main(["--family", "astronaut", "--jobs", str(env.jobs)]) == 1
