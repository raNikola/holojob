"""The 10-fixture calibration run, pinned (step 7).

tests/fixtures/engine-snapshot.json holds one matcher run on the owner's
evidence index, as verified requirements without any candidate text and the
five gate results, plus what the engine made of them. Re-scoring those same
inputs under the current constants must give the same results, so a change
to constants.py or fit.py fails here and the diff names every fixture it
moves. After a deliberate change, regenerate with

    .venv/bin/python python/match_engine/calibrate.py --snapshot tests/fixtures/engine-snapshot.json
"""

import json
from pathlib import Path

import pytest

from match_engine.fit import score

SNAPSHOT = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "engine-snapshot.json").read_text(encoding="utf-8")
)


def test_snapshot_covers_every_fixture():
    postings = Path(__file__).resolve().parents[1] / "fixtures" / "postings"
    assert sorted(SNAPSHOT) == sorted(p.name for p in postings.glob("*.json"))


@pytest.mark.parametrize("fixture", sorted(SNAPSHOT))
def test_fixture_result_is_pinned(fixture):
    entry = SNAPSHOT[fixture]
    gates = [{**g, "quote": None} for g in entry["gates"]]
    result = score(entry["requirements"], gates)
    assert {k: result[k] for k in entry["expected"]} == entry["expected"]


def test_label_and_bucket_table():
    """The whole run at a glance: what a constant change moves shows up as one diff."""
    table = {}
    for fixture, entry in sorted(SNAPSHOT.items()):
        result = score(entry["requirements"], [{**g, "quote": None} for g in entry["gates"]])
        table[fixture] = (result["label"], result["bucket"])
    assert table == {
        "ashby-1.json": ("Incomplete", "blocked"),
        "greenhouse-1.json": ("Incomplete", "blocked"),
        "greenhouse-2.json": ("Incomplete", "blocked"),
        "greenhouse-3.json": ("Incomplete", "blocked"),
        "infostud-1.json": ("Incomplete", "check_first"),
        "infostud-2.json": ("Incomplete", "blocked"),
        "linkedin-1.json": ("Good", "apply"),
        "linkedin-2.json": ("Incomplete", "check_first"),
        "workable-1.json": ("Incomplete", "check_first"),
        "workable-2.json": ("Good", "apply"),
    }
