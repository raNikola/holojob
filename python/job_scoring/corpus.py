"""Run-local inverse document frequency over the jobs being scored.

A term that appears in most listings says nothing about fit: "product",
"management" and "stakeholder" are in nearly every product-manager ad, so
counting them equally with rare terms flattens every score into the same
band. A term few listings use is what separates one from another.

Frequency is measured over the current run's corpus rather than a fixed stop
list, so it follows whatever the search is currently returning and nobody has
to maintain a word list.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from text_utils import term_tokens


def flat_idf(token: str) -> float:
    """Neutral weighting — every term counts the same."""
    _ = token
    return 1.0


def build_idf(jobs: list[dict]) -> Callable[[str], float]:
    """Return idf(token) in 0..1 over these jobs.

    0 means the token is in every listing, 1 means it is in none of the
    others. Normalised by corpus size so values stay comparable between runs
    of different lengths.
    """
    documents = [
        term_tokens(f"{job.get('title', '')} {job.get('description', '')}")
        for job in jobs
    ]
    total = len(documents)
    denominator = math.log(total + 1) if total else 0.0
    if not total or denominator == 0:
        return flat_idf

    frequency: dict[str, int] = {}
    for tokens in documents:
        for token in tokens:
            frequency[token] = frequency.get(token, 0) + 1

    cache: dict[str, float] = {}

    def idf(token: str) -> float:
        cached = cache.get(token)
        if cached is not None:
            return cached
        value = math.log((total + 1) / (frequency.get(token, 0) + 1)) / denominator
        value = max(0.0, min(1.0, value))
        cache[token] = value
        return value

    return idf