"""Round 2 text rules (package 4). What would hurt: a soft rule that drops an ad, an empty text that drops one, or a hard class
that does not drop."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python" / "job_discovery" / "providers"))
sys.path.insert(0, str(ROOT / "python" / "llm"))

import role_filter as rf  # noqa: E402
import text_rules  # noqa: E402

AD = ("Senior Product Manager. Fluent German required. At least 7 years of experience. No visa sponsorship. "
      "On-site only, full-time.")


def test_every_rule_has_a_class_and_none_is_hard_yet():
    assert set(text_rules.TEXT_RULE_CLASSES) == {"language", "years", "onsite", "visa", "employment"}
    assert set(text_rules.TEXT_RULE_CLASSES.values()) == {text_rules.SOFT}


def test_text_rules_label_and_never_drop():
    decision = rf.assess("Product Manager", "", (), AD)
    assert decision.reason is None and decision.tier == rf.TARGET
    assert {"language:german", "years:7", "visa:no_sponsorship", "onsite:only", "employment:full_time"} <= set(decision.labels)


def test_empty_text_and_remote_signal_continue_without_a_label():
    assert rf.assess("Product Manager", "", (), "").labels == ()
    assert rf.assess("Product Manager", "", (), None).labels == ()
    mixed = rf.assess("Product Manager", "", (), "On-site only for most, but hybrid is possible.")
    assert "onsite:only" not in mixed.labels


def test_a_hard_class_drops_with_its_own_reason(monkeypatch):
    monkeypatch.setitem(text_rules.TEXT_RULE_CLASSES, "visa", text_rules.HARD)
    decision = rf.assess("Product Manager", "", (), AD)
    assert decision.tier == rf.EXCLUDED and decision.reason == "text_rule:visa:no_sponsorship" and decision.rule == rf.HARD
