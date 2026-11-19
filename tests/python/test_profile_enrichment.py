"""Profile enrichment: the owner's statement of absence can never become evidence of experience (synthetic data, temp dir only)."""

import json
import stat

import profile_enrichment as pe
from calibration import fit_b
from evidence_index import build_evidence
from match_engine.verify import apply_proposal

ENRICHMENT = {
    "employers": ["Acme Corp"],
    "domains": [{"id": "D1", "source": "CV", "title": "Widgets", "text": "Direct, Acme Corp, 2017-2024. Widget marketing."}],
    "history": [{"id": "H1", "source": "CV", "role": "Lead", "period": "April 2024-present", "text": "Led a team at Acme Corp."}],
    "boundaries": [
        {"id": "B1", "source": "owner-confirmed", "stance": "none", "text": "Payments: no confirmed direct experience."},
        {"id": "B2", "source": "owner-confirmed", "stance": "direct", "text": "Widgets: direct professional experience."},
    ],
}


def test_absence_statement_is_marked_and_cannot_support_a_met():
    evidence = build_evidence({}, {}, ENRICHMENT)
    by_text = {e["text"]: e for e in evidence}
    absent = by_text["Payments: no confirmed direct experience."]
    assert absent["negative"] is True and "negative" not in by_text["Widgets: direct professional experience."]
    req = {"id": "r1", "text": "Payments experience", "kind": "experience", "importance": "must"}
    proposal = {"status": "MET", "evidenceId": absent["id"], "evidenceQuote": "no confirmed direct experience", "strength": 3}
    resolved, warning = apply_proposal(req, proposal, {e["id"]: e for e in evidence})
    assert resolved["status"] == "MISSING" and resolved["evidenceId"] is None and warning


def test_history_entry_carries_its_dates_and_nothing_is_added_without_enrichment():
    assert build_evidence({}, {}) == []
    role = next(e for e in build_evidence({}, {}, ENRICHMENT) if e["role"] == "Lead")
    assert (role["source"], role["start"], role["end"]) == ("role", "2024-04", None)


def test_malformed_entries_are_dropped_and_file_is_private(tmp_path):
    path = tmp_path / "profile-enrichment.json"
    pe.save({**ENRICHMENT, "domains": [*ENRICHMENT["domains"], {"id": "x", "source": "guess", "title": "t", "text": "t"}]}, path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert len(json.loads(path.read_text())["domains"]) == 1
    assert pe.load(tmp_path / "missing.json") == pe.normalize({})


def test_b_summary_reads_enrichment_only_in_p_full_and_masks_employers():
    pub = fit_b.summary_sections("public_cv", {}, {}, ENRICHMENT)
    full = fit_b.summary_sections("public_cv_plus_confirmed_C", {}, {}, ENRICHMENT)
    assert "Domain experience" not in pub and "Experience boundaries" not in pub
    text = fit_b.render_summary(full)
    assert "Acme" not in text and "[employer]" in text and "no confirmed direct experience" in text
