"""scripts/select-extraction-ads.py: which ads the next paid extraction reads."""
import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("sel", Path(__file__).resolve().parents[2] / "scripts/select-extraction-ads.py")
sel = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sel)


def row(i, before, score=50, **extra):
    return {"jobId": i, "title": "Product Manager", "company": "Acme", "location": "Berlin, Germany",
            "description": "Own the roadmap.", "scoreBeforeCaps": before, "matchScore": score, **extra}


def test_ranks_by_score_before_caps_and_leaves_out_closed_rejected_and_applied():
    rows = [row("low", 60), row("top", 90, 30), row("tie1", 70, 40), row("tie2", 70, 45), row("closed", 99, isClosed=True),
            row("rej", 95), row("app", 96), row("man", 97, manualEntry=True)]
    chosen, eligible, why = sel.select(rows, {"jobs": {}}, {}, {"rej", "app"}, 3)
    assert [j["jobId"] for j in chosen] == ["top", "tie2", "tie1"]
    assert eligible == 4 and why["closed_or_manual"] == 2 and why["rejected_or_applied"] == 2


def test_only_rejected_state_entries_are_excluded():
    state = {"jobs": {"k1": {"jobId": "a", "status": "rejected"}, "k2": {"jobId": "b", "status": "saved"}}}
    assert sel.rejected_ids(state) == {"a"}


def test_ledger_spend_sums_per_feature_and_counts_refusals():
    spec = importlib.util.spec_from_file_location("ls", Path(__file__).resolve().parents[2] / "scripts/ledger-spend.py")
    ls = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ls)
    import json
    lines = [json.dumps(r) for r in (
        {"type": "call", "id": "1", "feature": "enrichment", "decision": "allowed", "cost": 0.01},
        {"type": "result", "id": "1", "inputTokens": 100, "outputTokens": 20, "cost": 0.002},
        {"type": "call", "id": "2", "feature": "enrichment", "decision": "refused"},
        {"type": "call", "id": "3", "feature": "enrichment", "decision": "allowed", "cost": 0.004})]
    f = ls.summarise(lines)["enrichment"]
    assert (f["calls"], f["refused"], f["noResult"], f["in"], f["out"]) == (2, 1, 1, 100, 20)
    assert round(f["cost"], 6) == 0.006
