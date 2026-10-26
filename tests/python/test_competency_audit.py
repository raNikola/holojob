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


def item(text, kind="skill", competency=None):
    return {"text": text, "kind": kind, "importance": "must", "posting_quote": text,
            "previous_id": None, "competency_id": competency}


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


def test_counts_routes_and_picks(env, capsys):
    run = [
        [item("Can toot a kazoo", competency="kazoo-playing"), item("Map reading"), item("Python"),
         item("Broad thing", competency="NONE")],
        [item("Invented", competency="made-up"), item("Knows juggling", competency="juggling-degree"),
         item("Plain thing")],
    ]
    script(env, run, run)
    assert main(env, "--ads", "2", "--yes") == 0
    out = capsys.readouterr().out
    assert "run 1: 7 requirements" in out and "run 2: 7 requirements" in out
    assert "ids by route: frame 0, alias 1, dictionary 1, model 1, provisional 4" in out
    assert "model picks: accepted 1, none 2, rejected: not on the list 1, rejected: kind differs 1" in out
    assert "still provisional (including those kept from a previous frame): 4" in out
    # the second run starts from the same state as the first: it makes the same pick again, not an alias hit
    assert out.count("model 1,") == 2


def test_stability_counts_same_ids_and_mapped_disagreement(env, capsys):
    one = [[item("Can toot a kazoo", competency="kazoo-playing"), item("Stable thing"), item("Only first")]]
    two = [[item("Can toot a kazoo", competency=None), item("Stable thing"), item("Only second")]]
    script(env, one, two)
    assert main(env, "--ads", "1", "--yes") == 0
    out = capsys.readouterr().out
    assert "over 2 requirements stated in the same words in both runs (2 stated in only one)" in out
    assert "same id in both runs: 1 (50.0%)" in out
    assert "runs disagree about mapped vs not mapped: 1 (50.0%)" in out


def test_stability_function_with_nothing_paired():
    run = {"ads": {"a": {"requirements": [{"text": "x", "id": "p:1"}]}}}
    other = {"ads": {"a": {"requirements": [{"text": "y", "id": "p:2"}]}}}
    s = audit.stability(run, other)
    assert s["paired"] == 0 and s["unpaired"] == 2 and s["sameIdShare"] is None


def test_live_files_are_untouched_and_everything_lands_in_scratch(env, monkeypatch):
    live_alias = {"old text": {"competencyId": "map-reading", "status": "pending"}}
    cm._write(cm.ALIASES_PATH, live_alias)
    cm._write(cm.REMAP_PATH, {"prov:old": "map-reading"})
    frames = {rf.frame_key(ad(1)): [{"id": "prov:old", "text": "Old text", "kind": "skill", "importance": "must"}]}
    rf.save(frames)
    live = {p: p.read_bytes() for p in (cm.ALIASES_PATH, cm.REMAP_PATH, rf.FRAMES_PATH)}
    jobs_before = env.jobs.read_bytes()

    run = [[item("Can toot a kazoo", competency="kazoo-playing")], [item("Plain thing")]]
    script(env, run, [[item("Plain thing")], [item("Plain thing")]])
    assert main(env, "--ads", "2", "--yes") == 0

    assert {p: p.read_bytes() for p in live} == live
    assert env.jobs.read_bytes() == jobs_before
    scratch = env.data / audit.SCRATCH_NAME
    for n in (1, 2):
        names = {p.name for p in (scratch / f"run{n}").iterdir()}
        assert names == {"competency-aliases.json", "requirement-remap.json", "requirement-frames.json", "requirements.json"}
    learned = json.loads((scratch / "run1" / "competency-aliases.json").read_text())
    assert learned["can toot a kazoo"]["status"] == "pending" and "old text" in learned
    remap = json.loads((scratch / "run1" / "requirement-remap.json").read_text())
    assert remap[provisional_id("Can toot a kazoo")] == "kazoo-playing" and remap["prov:old"] == "map-reading"
    # run 2 did not inherit run 1's pending alias
    assert "can toot a kazoo" not in json.loads((scratch / "run2" / "competency-aliases.json").read_text())


def test_live_files_are_not_created_when_absent(env):
    script(env, [[item("Can toot a kazoo", competency="kazoo-playing")]], [[item("Plain thing")]])
    assert main(env, "--ads", "1", "--yes") == 0
    assert not cm.ALIASES_PATH.exists() and not cm.REMAP_PATH.exists() and not rf.FRAMES_PATH.exists()


def test_the_audit_file_has_both_sections_flags_compounds_and_names_the_closest(env):
    run1 = [[item("Can toot a kazoo", competency="kazoo-playing"), item("Maps and charts", competency="map-reading"),
             item("Map readin"), item("Broad thing", competency="NONE"), item("Python")]]
    script(env, run1, run1)
    assert main(env, "--ads", "1", "--yes") == 0
    text = (env.data / audit.AUDIT_NAME).read_text(encoding="utf-8")
    a, b = text.split("## B.")
    assert "1. Can toot a kazoo\n   - Picked: kazoo-playing\n   - Definition: Playing the kazoo; not other wind" in a
    assert "Maps and charts **COMPOUND?**" in a and "Can toot a kazoo **COMPOUND?**" not in a
    assert "Map readin\n   - Closest: map-reading (0.9" in b and "Broad thing\n   - Closest:" in b
    assert "Python" not in b, "a dictionary term is mapped, so it is not an open requirement"
    assert "Plays" not in text


def test_section_limits(env, monkeypatch):
    monkeypatch.setattr(audit, "SECTION_A_LIMIT", 2)
    monkeypatch.setattr(audit, "SECTION_B_LIMIT", 1)
    run1 = [[item(f"Pick {i}", competency="kazoo-playing") for i in range(5)]
            + [item(f"Open {i}") for i in range(5)]]
    script(env, run1, run1)
    assert main(env, "--ads", "1", "--yes") == 0
    a, b = (env.data / audit.AUDIT_NAME).read_text().split("## B.")
    assert a.count("   - Picked:") == 2 and b.count("   - Closest:") == 1


def test_refuses_to_write_outside_data(env, monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "audit_path", lambda: tmp_path / "elsewhere.md")
    with pytest.raises(SystemExit):
        main(env, "--ads", "1", "--yes")
    monkeypatch.setattr(audit, "audit_path", lambda: env.data / audit.AUDIT_NAME)
    monkeypatch.setattr(audit, "scratch_dir", lambda: tmp_path / "scratch")
    with pytest.raises(SystemExit):
        main(env, "--ads", "1", "--yes")
    assert not (tmp_path / "scratch").exists()


def test_an_unknown_family_cannot_be_audited(env, capsys):
    assert audit.main(["--family", "astronaut", "--jobs", str(env.jobs)]) == 1
