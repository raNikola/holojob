"""The one fingerprint of a job ad's content.

Enrichment caches its facts under it, and the job history ledger uses it to tell
whether an ad changed between runs. It covers what enrichment reads: the title,
the company and the opening of the description, plus the prompt version, so a
new question re-reads every ad.
"""

from __future__ import annotations

import hashlib

# Bump when the enrichment prompt changes: every ad is then read again rather
# than served from a cache built by an older question.
PROMPT_VERSION = 2

# Everything extracted is stated in the opening half of an ad. The rest is
# benefits copy and equal-opportunity boilerplate.
MAX_DESCRIPTION_CHARS = 9000


def job_fingerprint(job: dict) -> str:
    raw = "|".join(
        [
            str(PROMPT_VERSION),
            job.get("title") or "",
            job.get("company") or "",
            (job.get("description") or "")[:MAX_DESCRIPTION_CHARS],
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
