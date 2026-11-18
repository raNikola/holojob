"""embed() (W5 step 4 experiment): takes only a list of cleaned ad texts, goes through the AI gate, counts truncations, prices from the shipped entry.

Mocked responses only: requests.post is replaced in every test (the conftest tripwire fails any real POST). Every path is a temp dir.
"""

import json
import sys
from pathlib import Path

import pytest
import requests

import ai_gate
import llm_client

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import measure_embedding_signal as mes  # noqa: E402


class _Response:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload
        self.ok = 200 <= status < 300
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


@pytest.fixture
def api(tmp_path, monkeypatch):
    (tmp_path / "ai").mkdir(exist_ok=True)
    (tmp_path / "ai" / "settings.json").write_text(json.dumps({"dailyLimit": 10, "monthlyLimit": 25}))
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)
    sent = []

    def post(url, headers=None, json=None, timeout=None):
        sent.append({"url": url, "body": dict(json)})
        return _Response(200, {"data": [{"index": n, "embedding": [float(n), 1.0]} for n in range(len(json["input"]))],
                               "usage": {"prompt_tokens": 1000 * len(json["input"]), "total_tokens": 1000 * len(json["input"])}})

    monkeypatch.setattr(requests, "post", post)
    return sent


@pytest.mark.parametrize("bad", [
    "one text", ("a", "b"), [], None, [{"title": "x", "label": "apply"}], [["a"]], ["ok", None], ["ok", 3], ["   "], [b"bytes"],
    {"profile": "x"},
])
def test_embed_accepts_only_a_list_of_non_empty_strings(api, monkeypatch, bad):
    monkeypatch.setattr(ai_gate, "check", lambda *a, **k: pytest.fail("the gate must not be reached for a refused input"))
    with pytest.raises(llm_client.EmbedInputRefused):
        llm_client.embed(bad, confirm=True, max_usd=0.2)
    assert api == []


def test_embed_sends_nothing_without_confirm_or_a_positive_cap(api):
    with pytest.raises(llm_client.LlmRefused):
        llm_client.embed(["a text"], confirm=False, max_usd=0.2)
    with pytest.raises(llm_client.LlmRefused):
        llm_client.embed(["a text"], confirm=True, max_usd=0)
    assert api == []


def test_embed_sends_exactly_the_texts_and_nothing_else(api):
    result = llm_client.embed(["first ad text", "second ad text"], confirm=True, max_usd=0.2)
    assert len(api) == 1 and api[0]["url"].endswith("/embeddings")
    assert api[0]["body"] == {"model": "text-embedding-3-small", "input": ["first ad text", "second ad text"], "encoding_format": "float"}
    assert len(result["vectors"]) == 2 and result["truncated"] == [] and result["inputTokens"] == 2000


def test_embed_goes_through_the_gate_and_is_priced_from_the_shipped_entry(api):
    result = llm_client.embed(["an ad"], confirm=True, max_usd=0.2)
    rows = ai_gate.read_ledger()
    call = [r for r in rows if r["type"] == "call"][-1]
    done = [r for r in rows if r["type"] == "result"][-1]
    assert call["decision"] == "allowed" and call["feature"] == "embedding-experiment" and call["model"] == "text-embedding-3-small"
    assert "serviceTierRequested" not in call and call["priceKnown"] is True
    assert done["ok"] is True and done["inputTokens"] == 1000 and done["outputTokens"] == 0
    assert done["cost"] == pytest.approx(1000 * 0.02 / 1e6) and result["costUsd"] == pytest.approx(0.00002)


def test_embed_refused_by_the_gate_is_recorded_and_sends_nothing(api, tmp_path):
    (tmp_path / "ai" / "settings.json").write_text(json.dumps({"dailyLimit": 0, "monthlyLimit": 0}))
    with pytest.raises(llm_client.GuardrailRefused):
        llm_client.embed(["an ad"], confirm=True, max_usd=0.2)
    assert api == [] and [r for r in ai_gate.read_ledger() if r.get("decision") == "refused"]


def test_embed_refuses_an_estimate_above_the_cap(api):
    with pytest.raises(llm_client.LlmRefused):
        llm_client.embed(["x" * 15000] * 40, confirm=True, max_usd=0.000001)
    assert api == []


def test_texts_above_the_character_cap_are_truncated_and_counted(api):
    long_text = "y" * (llm_client.EMBED_MAX_CHARS + 500)
    result = llm_client.embed(["short", long_text, "short too"], confirm=True, max_usd=0.2)
    assert result["truncated"] == [1]
    assert [len(t) for t in api[0]["body"]["input"]] == [5, llm_client.EMBED_MAX_CHARS, 9]


def test_a_failed_request_is_recorded_and_raised(api, monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Response(400, {"error": {"message": "too long"}}))
    with pytest.raises(llm_client.LlmRefused):
        llm_client.embed(["an ad"], confirm=True, max_usd=0.2)
    done = [r for r in ai_gate.read_ledger() if r["type"] == "result"][-1]
    assert done["ok"] is False and done["cost"] == 0.0


# --- the experiment script: cleaning, what is embedded, the evaluation rule ---------------------------------------------------------------------

def test_clean_text_unescapes_and_strips_markup():
    assert mes.clean_text("<p>Lead &amp; ship</p><script>x()</script><ul><li>One&nbsp;thing</li></ul>") == "Lead & ship\nOne thing"
    assert mes.clean_text("&lt;b&gt;bold&lt;/b&gt; text") == "bold text"


def test_embed_text_has_only_title_and_description():
    ad = {"id": "a", "title": "Senior TPM", "company": "Acme Ltd", "description": "Do things.", "label": "apply", "set": "holdout"}
    assert mes.embed_text(ad) == "Senior TPM\nDo things."


def _toy():
    ads = {i: {"company": c, "title": "t", "label": lab, "set": "holdout"} for i, c, lab in
           [("a1", "A", "apply"), ("a2", "B", "apply"), ("s1", "C", "fit_skip"), ("s2", "D", "fit_skip"), ("m1", "E", "maybe")]}
    vectors = {"a1": [1, 0.1], "a2": [1, 0.2], "s1": [0.1, 1], "s2": [0.2, 1], "m1": [1, 0]}
    return ads, vectors


def test_crossfit_never_trains_on_the_own_company_or_other_labels():
    ads, vectors = _toy()
    labels = {i: a["label"] for i, a in ads.items()}
    companies = {i: a["company"] for i, a in ads.items()}
    scores = mes.crossfit_scores(vectors, labels, companies)
    assert scores["a1"] > 0 > scores["s1"]
    # the maybe ad is scored but is in no centroid: changing it changes no other score
    changed = mes.crossfit_scores({**vectors, "m1": [0, 1]}, labels, companies)
    assert all(changed[i] == scores[i] for i in scores if i != "m1")
    # a fold with no Apply left in training has no score
    only = mes.crossfit_scores({"a1": [1, 0], "s1": [0, 1]}, {"a1": "apply", "s1": "fit_skip"}, {"a1": "A", "s1": "B"})
    assert only == {"a1": None, "s1": None}


def test_tie_break_only_acts_inside_a_role_class_and_ties_count_half():
    classes = {"p": "target", "n1": "target", "n2": "other", "n3": "adjacent"}
    assert mes.pair_value("p", "n2", classes, None) == 1.0 and mes.pair_value("p", "n1", classes, None) == 0.5
    assert mes.pair_value("n2", "p", classes, {"n2": 9.0, "p": 0.0}) == 0.0  # a better score never outranks a better class
    assert mes.pair_value("p", "n1", classes, {"p": 0.3, "n1": 0.1}) == 1.0
    assert mes.pair_value("p", "n1", classes, {"p": 0.1, "n1": 0.1}) == 0.5
    assert mes.auc(["p"], ["n1", "n2", "n3"], classes, None) == pytest.approx((0.5 + 1 + 1) / 3)


def test_verdict_rule():
    assert mes.verdict_of([0.01, 0.4]) == "WIN"
    assert mes.verdict_of([-0.1, 0.4]) == "INCONCLUSIVE"
    assert mes.verdict_of([0.0, 0.4]) == "INCONCLUSIVE"
    assert mes.verdict_of([-0.4, -0.01]) == "NO HELP"


def test_bootstrap_is_deterministic_and_discards_degenerate_resamples():
    groups = {"A": ["a1"], "B": ["s1"], "C": ["s2"]}
    labels = {"a1": "apply", "s1": "fit_skip", "s2": "fit_skip"}
    stat = lambda ids: ({"x": float(len(ids))} if any(labels[i] == "fit_skip" for i in ids) else None)
    one = mes.bootstrap(groups, {"A"}, stat, b=200, seed=1)
    assert one == mes.bootstrap(groups, {"A"}, stat, b=200, seed=1)
    assert one["B"] == 200 and one["discardedResamples"] >= 0


def test_evaluate_runs_end_to_end_on_toy_data():
    ads, vectors = _toy()
    classes = {i: "target" for i in ads}
    ads["x1"] = {"company": "F", "title": "t", "label": "applied", "set": "applied"}
    vectors["x1"] = [1, 0.3]
    out = mes.evaluate(ads, classes, vectors)
    assert out["verdict"] in ("WIN", "INCONCLUSIVE", "NO HELP") and out["point"]["aucTieBreak"] == 1.0 and out["point"]["aucBaseline"] == 0.5
    assert out["applied"]["embeddingOnlyAucVsFitSkip"] == 1.0


def test_seventy_texts_go_in_one_request(api):
    result = llm_client.embed([f"ad number {n}" for n in range(70)], confirm=True, max_usd=0.2)
    assert len(api) == 1 and len(api[0]["body"]["input"]) == 70 and len(result["vectors"]) == 70


def test_level_gain_is_the_tie_break_effect_inside_role_classes():
    classes = {"a": "target", "b": "target", "c": "target", "d": "other", "e": "other"}
    levels = {"a": 3, "b": 2, "c": 1, "d": 1, "e": 0}
    good = {"a": 0.9, "b": 0.5, "c": 0.1, "d": 0.6, "e": 0.2}
    bad = {"a": 0.1, "b": 0.5, "c": 0.9, "d": 0.2, "e": 0.6}
    up = mes.level_metrics(list(levels), levels, classes, good)
    down = mes.level_metrics(list(levels), levels, classes, bad)
    assert up["rhoTieBreak"] > up["rhoRoleOnly"] and up["gain"] > 0 > down["gain"]
    assert up["rhoRoleOnly"] == down["rhoRoleOnly"]
    assert mes.level_metrics(["a", "b"], levels, classes, good) is None  # fewer than three ads
    assert mes.level_metrics(list(levels), {i: 1 for i in levels}, classes, good) is None  # a constant level


def test_level_task_reports_aggregates_only():
    ads = {i: {"company": c, "set": "dev"} for i, c in zip("abcdef", "ABCDEF")}
    classes = dict(zip("abcdef", ["other", "other", "adjacent", "target", "adjacent", "target"]))
    levels = dict(zip("abcdef", [0, 1, 2, 3, 1, 2]))
    scores = dict(zip("abcdef", [0.1, 0.2, 0.3, 0.4, 0.15, 0.35]))
    out = mes.level_task(ads, classes, scores, {i: a["company"] for i, a in ads.items()}, levels)
    assert out["verdict"] in ("WIN", "INCONCLUSIVE", "NO HELP") and out["ads"] == 6 and out["companyGroups"] == 6
    assert not any(i in out for i in "abcdef") and not {"a", "b", "c", "d", "e", "f"} & set(json.dumps(out).replace('"', " ").replace(":", " ").replace(",", " ").split())
