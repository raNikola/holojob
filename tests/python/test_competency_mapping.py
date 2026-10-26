"""Competency mapping inside the extraction call (step 2c-1), on a fictional list and a mocked model."""

import json
import sys

import pytest

import competency_mapping as cm
import enrich_jobs
import job_fingerprint
import requirement_frames as rf
from enrich_jobs import _coerce, _reuse_previous, extract, fact_schema
from requirement_ids import assign_id, provisional_id

COMPS = [
    {"id": "kazoo-playing", "definition": "Playing the kazoo; not other wind instruments.", "kind": "skill",
     "aliases": ["kazoo playing", "plays the kazoo"]},
    {"id": "map-reading", "definition": "Reading maps; not drawing them.", "kind": "skill",
     "aliases": ["map reading"]},
    {"id": "juggling-degree", "definition": "A degree in juggling; not a course.", "kind": "education",
     "aliases": ["juggling degree"]},
]
AD = {"jobId": "j1", "title": "Clown", "company": "Circus", "location": "Remote", "description": "Plays the kazoo."}


def mapper(tmp_path):
    return cm.Mapper(COMPS, tmp_path / "aliases.json", tmp_path / "remap.json")


def req(text, kind="skill", suggested=None, previous=None, **extra):
    r = {"text": text, "kind": kind, "importance": "must", "postingQuote": text, "previousId": previous, **extra}
    if suggested is not None:
        r["competencyId"] = suggested
        r.setdefault("covers", "none" if suggested.lower() in cm.NONE_ANSWERS | {"none"} else "whole")
    return r


def ids(reqs):
    return [r["id"] for r in reqs]


# --- precedence --------------------------------------------------------------------

def test_previous_id_beats_an_alias(tmp_path):
    previous = [{"id": "prov:old", "text": "Something else", "kind": "skill", "importance": "must"}]
    (r,) = _reuse_previous([req("Plays the kazoo", previous="prov:old")], previous, mapper(tmp_path))
    # the previous text no longer resolves, so the previous id stays
    assert r["id"] == "prov:old" and r["text"] == "Something else"


def test_alias_beats_dictionary_term_and_model_suggestion(tmp_path):
    m = mapper(tmp_path)
    (r,) = _reuse_previous([req("Map reading", suggested="kazoo-playing")], None, m)
    assert r["id"] == "map-reading" and r["provisional"] is False
    assert m.stats["accepted"] == 0, "the suggestion was never consulted"


def test_alias_lookup_uses_the_alias_key(tmp_path):
    (r,) = _reuse_previous([req("  Plays   the KAZOO. ")], None, mapper(tmp_path))
    assert r["id"] == "kazoo-playing"


def test_dictionary_term_beats_the_model_suggestion(tmp_path):
    (r,) = _reuse_previous([req("Python", suggested="kazoo-playing")], None, mapper(tmp_path))
    assert r["id"] == "python"


def test_model_suggestion_beats_the_provisional_hash(tmp_path):
    (r,) = _reuse_previous([req("Can toot a kazoo", suggested="kazoo-playing")], None, mapper(tmp_path))
    assert r["id"] == "kazoo-playing" and r["provisional"] is False
    assert "competencyId" not in r and "previousId" not in r


def test_no_suggestion_is_provisional_as_before(tmp_path):
    (r,) = _reuse_previous([req("Can toot a kazoo")], None, mapper(tmp_path))
    assert r == {**assign_id({"text": "Can toot a kazoo", "kind": "skill", "importance": "must",
                              "postingQuote": "Can toot a kazoo"})}


# --- acceptance and rejection ------------------------------------------------------

def test_each_rejection_reason_is_counted_and_leaves_the_requirement_provisional(tmp_path):
    m = mapper(tmp_path)
    out = _reuse_previous([
        req("Can toot a kazoo", suggested="kazoo-playing"),
        req("Invented", suggested="made-up-id"),
        req("Knows about juggling", kind="skill", suggested="juggling-degree"),
        req("Broad thing", suggested="NONE"),
        req("Another broad thing", suggested="none"),
        req("Third", suggested=""),
    ], None, m)
    assert ids(out)[0] == "kazoo-playing"
    assert all(r["provisional"] for r in out[1:])
    assert m.stats == {"accepted": 1, "rejected: not on the list": 1, "rejected: kind differs": 1, "none": 3}
    assert m.summary() == "accepted 1, none 3, rejected: kind differs 1, rejected: not on the list 1"


def test_none_is_not_a_rejection(tmp_path):
    m = mapper(tmp_path)
    _reuse_previous([req("Broad thing", suggested="NONE")], None, m)
    assert not any(k.startswith("rejected") for k in m.stats)


def test_a_rejected_suggestion_stores_nothing(tmp_path):
    m = mapper(tmp_path)
    _reuse_previous([req("Invented", suggested="made-up-id")], None, m)
    m.save()
    assert not (tmp_path / "aliases.json").exists() and not (tmp_path / "remap.json").exists()


# --- learned aliases ----------------------------------------------------------------

def test_an_accepted_suggestion_is_stored_pending_and_used_on_the_next_ad(tmp_path):
    m = mapper(tmp_path)
    _reuse_previous([req("Can toot a kazoo.", suggested="kazoo-playing")], None, m)
    m.save()
    stored = json.loads((tmp_path / "aliases.json").read_text(encoding="utf-8"))
    assert stored == {"can toot a kazoo": {"competencyId": "kazoo-playing", "status": "pending"}}

    again = mapper(tmp_path)  # the next run reads the file
    (r,) = _reuse_previous([req("can toot a kazoo")], None, again)  # no suggestion this time
    assert r["id"] == "kazoo-playing"
    assert again.stats["accepted"] == 0


def test_mapping_status_tells_seed_reviewed_and_pending_apart(tmp_path):
    m = mapper(tmp_path)
    (seed,) = _reuse_previous([req("Map reading")], None, m)
    (learned,) = _reuse_previous([req("Can toot a kazoo", suggested="kazoo-playing")], None, m)
    (unmapped,) = _reuse_previous([req("Something else")], None, m)
    (dictionary,) = _reuse_previous([req("Python")], None, m)
    assert m.mapping_status(seed) == "reviewed"
    assert m.mapping_status(learned) == "pending"
    assert m.mapping_status(unmapped) is None and m.mapping_status(dictionary) is None
    m.learned["can toot a kazoo"]["status"] = "reviewed"
    assert m.mapping_status(learned) == "reviewed"


def test_a_learned_alias_cannot_take_over_a_seed_alias(tmp_path):
    (tmp_path / "aliases.json").write_text(json.dumps({"map reading": {"competencyId": "kazoo-playing", "status": "pending"}}))
    (r,) = _reuse_previous([req("map reading")], None, mapper(tmp_path))
    assert r["id"] == "map-reading"


def test_a_learned_alias_for_an_id_not_on_the_list_is_ignored(tmp_path):
    (tmp_path / "aliases.json").write_text(json.dumps({"odd text": {"competencyId": "gone", "status": "pending"}}))
    (r,) = _reuse_previous([req("odd text")], None, mapper(tmp_path))
    assert r["provisional"] is True


# --- remap table and frames ----------------------------------------------------------

def test_a_provisional_id_that_gains_a_canonical_id_is_recorded(tmp_path):
    m = mapper(tmp_path)
    _reuse_previous([req("Can toot a kazoo", suggested="kazoo-playing"), req("Map reading")], None, m)
    m.save()
    remap = cm.load_remap(tmp_path / "remap.json")
    assert remap == {provisional_id("Can toot a kazoo"): "kazoo-playing", provisional_id("Map reading"): "map-reading"}


def test_a_previous_provisional_id_is_upgraded_when_its_text_now_resolves(tmp_path):
    old = provisional_id("Map reading")
    previous = [{"id": old, "text": "Map reading", "kind": "skill", "importance": "must"}]
    m = mapper(tmp_path)
    (r,) = _reuse_previous([req("Reading of maps", previous=old)], previous, m)
    assert r["id"] == "map-reading" and r["text"] == "Map reading" and not r["provisional"]
    assert m.remap == {old: "map-reading"}


def test_a_previous_canonical_id_is_kept(tmp_path):
    previous = [{"id": "kazoo-playing", "text": "Plays the kazoo", "kind": "skill", "importance": "must"}]
    (r,) = _reuse_previous([req("Kazoo", previous="kazoo-playing")], previous, mapper(tmp_path))
    assert r["id"] == "kazoo-playing" and r["text"] == "Plays the kazoo"


def test_apply_remap_rewrites_frames_and_reports_the_count():
    frames = {"a": [{"id": "prov:1", "text": "x"}, {"id": "sql", "text": "SQL"}], "b": [{"id": "prov:1", "text": "y"}]}
    assert rf.apply_remap(frames, {"prov:1": "kazoo-playing"}) == 2
    assert [r["id"] for r in frames["a"] + frames["b"]] == ["kazoo-playing", "sql", "kazoo-playing"]
    assert rf.apply_remap(frames, {}) == 0


def test_previous_for_returns_remapped_ids_without_changing_the_store():
    frames = {rf.frame_key(AD): [{"id": "prov:1", "text": "x", "kind": "skill", "importance": "must"}]}
    assert rf.previous_for(frames, AD, {"prov:1": "kazoo-playing"})[0]["id"] == "kazoo-playing"
    assert frames[rf.frame_key(AD)][0]["id"] == "prov:1"
    fallback = {"llmFacts": {"requirements": [{"id": "prov:1", "text": "x", "kind": "skill", "importance": "must"}]}}
    assert rf.previous_for({}, fallback, {"prov:1": "kazoo-playing"})[0]["id"] == "kazoo-playing"


# --- prompt, schema, coerce ----------------------------------------------------------

def test_coerce_reads_competency_id_only_when_the_model_gave_the_field():
    base = {"text": "t", "kind": "skill", "importance": "must", "posting_quote": "t"}
    (without,) = _coerce({"requirements": [base]})["requirements"]
    (with_,) = _coerce({"requirements": [{**base, "competency_id": " kazoo-playing "}]})["requirements"]
    (null,) = _coerce({"requirements": [{**base, "competency_id": None}]})["requirements"]
    assert "competencyId" not in without
    assert with_["competencyId"] == "kazoo-playing" and null["competencyId"] == ""
    (covered,) = _coerce({"requirements": [{**base, "competency_id": "x", "covers": " Part "}]})["requirements"]
    assert covered["covers"] == "part" and with_["covers"] == ""


def test_schema_has_the_field_only_with_a_competency_list():
    plain = fact_schema(False)["schema"]["properties"]["requirements"]["items"]
    with_ = fact_schema(True)["schema"]["properties"]["requirements"]["items"]
    assert "competency_id" not in plain["properties"] and "competency_id" not in plain["required"]
    assert with_["properties"]["competency_id"] == {"type": ["string", "null"]}
    assert set(with_["required"]) == set(with_["properties"])
    assert with_["properties"]["covers"]["enum"] == ["whole", "part", "none"]
    assert "competency_id" not in enrich_jobs.FACT_SCHEMA["schema"]["properties"]["requirements"]["items"]["properties"]


@pytest.fixture
def prompts(monkeypatch):
    seen = []

    def complete(prompt, schema=None, model=None, provider=None):
        seen.append((prompt, schema))
        return {"requirements": [{"text": "Can toot a kazoo", "kind": "skill", "importance": "must",
                                  "posting_quote": "Plays the kazoo.", "previous_id": None,
                                  "competency_id": "kazoo-playing", "covers": "whole"}]}

    monkeypatch.setattr(enrich_jobs, "complete_json", complete)
    return seen


def test_extract_lists_the_competencies_and_resolves_the_models_pick(tmp_path, prompts):
    facts = extract(AD, None, None, mapper=mapper(tmp_path))
    prompt, schema = prompts[0]
    assert "=== COMPETENCIES" in prompt and '"id": "kazoo-playing"' in prompt and "competency_id" in prompt
    assert "never invent an id" in prompt
    assert "competency_id" in schema["schema"]["properties"]["requirements"]["items"]["properties"]
    assert ids(facts["requirements"]) == ["kazoo-playing"]


def test_the_competency_list_in_the_prompt_is_the_seed_and_nothing_else(tmp_path, prompts):
    m = mapper(tmp_path)
    extract(AD, None, None, mapper=m)
    prompt, _ = prompts[0]
    block = prompt[prompt.index("=== COMPETENCIES"):prompt.index("=== END COMPETENCIES ===")]
    rows = [json.loads(line) for line in block.splitlines()[1:]]
    assert rows == [{"id": c["id"], "kind": c["kind"], "definition": c["definition"]} for c in COMPS]
    # The mapper was built from the seed only; a profile's words cannot be in it.
    assert "Ada Lovelace" not in prompt and "ada@example.com" not in prompt
    assert set(json.loads(block.splitlines()[1])) == {"id", "kind", "definition"}


def test_without_a_competency_list_the_prompt_and_schema_are_unchanged(prompts):
    facts = extract(AD, None, None)
    prompt, schema = prompts[0]
    assert "COMPETENCIES" not in prompt and "competency_id" not in prompt and "13." not in prompt
    assert schema is enrich_jobs.FACT_SCHEMA
    assert ids(facts["requirements"]) == [provisional_id("Can toot a kazoo")]


def test_the_prompt_version_was_bumped():
    assert job_fingerprint.PROMPT_VERSION >= 5


def test_the_seed_competency_list_size_in_the_real_prompt():
    from match_engine import competencies

    rows = cm.list_rows(competencies.load("product"))
    assert 0 < len(rows) < 30000


# --- main wires the mapper in -------------------------------------------------------

def _run_main(tmp_path, monkeypatch, family, extra=()):
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({"jobs": [dict(AD)]}), encoding="utf-8")
    intel = tmp_path / "intel.json"
    intel.write_text(json.dumps({"roleFamily": family}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["enrich_jobs.py", "--jobs", str(jobs), "--workers", "1",
                                      "--intelligence", str(intel), "--ledger", str(tmp_path / "ledger.json"), *extra])
    return enrich_jobs.main()


def test_main_maps_with_the_family_list_and_saves_aliases_remap_and_frames(tmp_path, monkeypatch, prompts, capsys):
    monkeypatch.setattr(cm.competencies, "load", lambda family: COMPS if family == "fiction" else [])
    assert _run_main(tmp_path, monkeypatch, "fiction") == 0
    assert "competency suggestions: accepted 1" in capsys.readouterr().out
    assert "kazoo-playing" in json.dumps(cm._read(cm.ALIASES_PATH))
    assert cm.load_remap() == {provisional_id("Can toot a kazoo"): "kazoo-playing"}
    assert rf.load()[rf.frame_key(AD)][0]["id"] == "kazoo-playing"


def test_main_rewrites_a_stored_frame_whose_id_gained_a_canonical_id(tmp_path, monkeypatch, prompts):
    old = provisional_id("Reading of maps")
    rf.save({rf.frame_key(AD): [{"id": old, "text": "Reading of maps", "kind": "skill", "importance": "must"}],
             "other": [{"id": old, "text": "Reading of maps", "kind": "skill", "importance": "must"}]})
    cm._write(cm.REMAP_PATH, {old: "map-reading"})
    monkeypatch.setattr(cm.competencies, "load", lambda family: COMPS)
    assert _run_main(tmp_path, monkeypatch, "fiction") == 0
    assert rf.load()["other"][0]["id"] == "map-reading"


def test_main_with_no_seed_for_the_family_changes_nothing(tmp_path, monkeypatch, prompts, capsys):
    assert _run_main(tmp_path, monkeypatch, "astronaut") == 0
    prompt, schema = prompts[0]
    assert "COMPETENCIES" not in prompt and schema is enrich_jobs.FACT_SCHEMA
    assert "competency suggestions" not in capsys.readouterr().out
    assert not cm.ALIASES_PATH.exists() and not cm.REMAP_PATH.exists()


def test_main_with_no_family_set_changes_nothing(tmp_path, monkeypatch, prompts):
    assert _run_main(tmp_path, monkeypatch, None) == 0
    assert "COMPETENCIES" not in prompts[0][0]


def test_an_invalid_seed_leaves_requirements_unmapped(tmp_path, monkeypatch, prompts):
    monkeypatch.setattr(cm.competencies, "load", lambda family: [{"id": "Bad Id"}])
    assert cm.load_mapper("fiction") is None
    assert cm.load_mapper(None) is None


# --- covers ----------------------------------------------------------------------------

def pick(m, text="Can toot a kazoo", competency="kazoo-playing", covers="whole", kind="skill"):
    (r,) = _reuse_previous([req(text, kind=kind, suggested=competency, covers=covers)], None, m)
    return r


def test_only_a_whole_cover_is_accepted(tmp_path):
    m = mapper(tmp_path)
    assert pick(m)["id"] == "kazoo-playing"
    assert m.stats == {"accepted": 1}


def test_part_leaves_the_requirement_provisional_and_stores_no_alias(tmp_path):
    m = mapper(tmp_path)
    r = pick(m, "Five years of kazoo playing", covers="part")
    assert r["provisional"] is True and r["id"] == provisional_id("Five years of kazoo playing")
    assert m.stats == {"part": 1} and m.parts == [("Five years of kazoo playing", "kazoo-playing")]
    assert m.learned == {} and m.remap == {}
    m.save()
    assert not (tmp_path / "aliases.json").exists()


@pytest.mark.parametrize("competency,covers", [
    (None, "whole"), ("", "part"), ("kazoo-playing", "none"), ("kazoo-playing", ""), ("kazoo-playing", "mostly"),
])
def test_a_covers_that_contradicts_the_id_is_an_inconsistency_treated_as_none(tmp_path, competency, covers):
    m = mapper(tmp_path)
    r = _reuse_previous([{**req("Can toot a kazoo"), "competencyId": competency or "", "covers": covers}], None, m)[0]
    assert r["provisional"] is True
    assert m.stats == {"inconsistent": 1} and m.learned == {}


def test_none_with_no_id_is_a_plain_none_even_without_a_readable_covers(tmp_path):
    m = mapper(tmp_path)
    for covers in ("none", "", "garbage"):
        _reuse_previous([{**req("Broad thing"), "competencyId": "", "covers": covers}], None, m)
    assert m.stats == {"none": 3}


def test_whole_still_needs_the_id_on_the_list_and_the_kind(tmp_path):
    m = mapper(tmp_path)
    assert pick(m, "Invented", competency="made-up")["provisional"]
    assert pick(m, "Knows juggling", competency="juggling-degree")["provisional"]
    assert m.stats == {"rejected: not on the list": 1, "rejected: kind differs": 1}
    assert m.kind_rejections == {("skill", "education"): 1}


def test_a_part_naming_an_id_off_the_list_is_a_rejection_not_a_part(tmp_path):
    m = mapper(tmp_path)
    pick(m, "Something", competency="made-up", covers="part")
    assert m.stats == {"rejected: not on the list": 1} and m.parts == []


def test_decisions_record_every_consulted_suggestion(tmp_path):
    m = mapper(tmp_path)
    pick(m)
    pick(m, "Two things", covers="part")
    _reuse_previous([req("Broad thing", suggested="NONE")], None, m)
    assert [(d["text"], d["covers"], d["outcome"]) for d in m.decisions] == [
        ("Can toot a kazoo", "whole", "accepted"), ("Two things", "part", "part"), ("Broad thing", "none", "none")]


def test_the_prompt_rules_and_examples():
    rule = cm.COMPETENCY_RULE
    assert '"whole"' in rule and '"part"' in rule and '"none"' in rule and "When in doubt" in rule
    examples = [line for line in rule.splitlines() if line.startswith('- "') and "->" in line]
    assert 6 <= len(examples) <= 8
    assert {e.rsplit(",", 1)[-1].split("(")[0].strip() for e in examples} == {"whole", "part", "none"}
    assert any("years" in e for e in examples) and any(" and " in e or " or " in e for e in examples)


# --- the kind table ------------------------------------------------------------------------

def test_the_shipped_table_relaxes_only_the_soft_kinds():
    assert cm.KIND_GROUPS == (frozenset({"skill", "experience", "other"}),)
    assert cm.kinds_compatible("experience", "skill") and cm.kinds_compatible("other", "skill")
    assert not cm.kinds_compatible("experience", "domain") and not cm.kinds_compatible("education", "experience")


def test_an_empty_table_is_strict_and_a_group_relaxes_its_kinds(monkeypatch):
    monkeypatch.setattr(cm, "KIND_GROUPS", ())
    assert cm.kinds_compatible("skill", "skill") and not cm.kinds_compatible("skill", "experience")
    monkeypatch.setattr(cm, "KIND_GROUPS", (frozenset({"skill", "experience", "other"}),))
    assert cm.kinds_compatible("skill", "experience") and cm.kinds_compatible("other", "skill")
    assert not cm.kinds_compatible("domain", "skill") and not cm.kinds_compatible("education", "other")
    assert cm.kinds_compatible("domain", "domain")


def test_the_table_changes_acceptance(tmp_path, monkeypatch):
    m = mapper(tmp_path)
    monkeypatch.setattr(cm, "KIND_GROUPS", ())
    assert pick(m, "Plays kazoo for years", kind="experience")["provisional"]
    monkeypatch.setattr(cm, "KIND_GROUPS", (frozenset({"skill", "experience", "other"}),))
    assert pick(m, "Plays kazoo for years", kind="experience")["id"] == "kazoo-playing"
    assert pick(m, "Knows juggling", competency="juggling-degree")["provisional"], "education stays strict"
