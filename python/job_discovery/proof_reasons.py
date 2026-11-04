"""Why a source or a board did or did not count as proven in a run (S7a). Stdlib only.

The importer already decides this (`importer._search_proof_reasons`, `importer.board_evidence`); this module only names the answers, so
the run record can keep the reason and the Activity screen can show it. The codes are the contract with the screen: the text for each
lives in `src/data/proofReasons.json`, and `tests/python/test_proof_reasons.py` fails when this set and that file differ.

"Proven" means a run may count towards Stale and, for a board, may support closing. It does not mean the run was good.
"""

from __future__ import annotations

# A search-based source, and the run-level facts that apply to every source.
PROVEN = "proven"
NOT_FINISHED = "not_finished"
SOURCE_FAILED = "source_failed"
SOURCE_PARTIAL = "source_partial"
SOURCE_SKIPPED = "source_skipped"
NOTHING_READ = "nothing_read"
ADS_NOT_WHOLE = "ads_not_whole"
STAGED_DIFFERS = "staged_differs"
FILES_TORN = "files_torn"
DISCARDS_MISMATCH = "discards_mismatch"
DISCARDS_DAMAGED = "discards_damaged"
PARTS_FAILED = "parts_failed"
NO_SEARCH_KEY = "no_search_key"
RUN_CANCELLED = "run_cancelled"

# A board source (Greenhouse, Lever, Ashby), per board and for the source.
BOARD_COMPLETE = "board_complete"
BOARD_UNREADABLE = "board_unreadable"
BOARD_EMPTY = "board_empty"
NO_TOTAL = "no_total"
TOTAL_DIFFERS = "total_differs"
END_NOT_CHECKED = "end_not_checked"
END_CHECK_FAILED = "end_check_failed"
END_CHECK_NOT_A_LIST = "end_check_not_a_list"
POSTINGS_PAST_END = "postings_past_end"
NO_PROOF_AVAILABLE = "no_proof_available"
BOARD_ANOMALIES = "board_anomalies"
FILES_DONT_ADD_UP = "files_dont_add_up"
SOURCE_IN_DOUBT = "source_in_doubt"
BOARD_NOT_COMPLETE = "board_not_complete"  # the provider said not complete in words this module does not know
NO_BOARD_EVIDENCE = "no_board_evidence"
BOARDS_NOT_PROVEN = "boards_not_proven"

ALL_CODES = frozenset(
    value for name, value in globals().items() if name.isupper() and isinstance(value, str) and name != "ALL_CODES"
)

# The provider's own words for "this board is not complete" (providers/*.py), by their start. Order matters: first match wins.
_PROVIDER_REASONS = (
    ("the board could not be read", BOARD_UNREADABLE),
    ("the board answered with no ads", BOARD_EMPTY),
    ("the answer reports no total", NO_TOTAL),
    ("the answer reports ", TOTAL_DIFFERS),
    ("the end of the list was not checked", END_NOT_CHECKED),
    ("the end-of-list request failed", END_CHECK_FAILED),
    ("the end-of-list request did not answer with a list", END_CHECK_NOT_A_LIST),
    ("the end-of-list request returned postings past", POSTINGS_PAST_END),
    ("no completeness proof available", NO_PROOF_AVAILABLE),
)


def board_reason_code(reason) -> str:
    """The code for a provider's `board_read(... reason=...)` text. A text it does not know is BOARD_NOT_COMPLETE, never a silent pass."""
    text = reason if isinstance(reason, str) else ""
    for start, code in _PROVIDER_REASONS:
        if text.startswith(start):
            return code
    return BOARD_NOT_COMPLETE


def once(codes) -> list[str]:
    """The codes in the order given, each once."""
    seen: list[str] = []
    for code in codes:
        if code not in seen:
            seen.append(code)
    return seen
