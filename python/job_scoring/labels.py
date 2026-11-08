"""Score labels and recommendations."""

from __future__ import annotations


# Apply starts at 70: a job below it is not worth an application. P1 is the
# smaller "apply first" list inside Apply. On the 2026-10-24 run (430 jobs) a P1
# line of 70 took 175 jobs (41%): role, culture and location are near-constant
# across the jobs that survive the hard caps, so about 70 points are everyone's
# and the median uncapped job scores 70. 76 keeps 37 jobs (9%). Recalibrate this
# one number against a real run; the tailor step and the P1 view follow it.
APPLY_MIN_SCORE = 70
P1_MIN_SCORE = 76


# The state of an ad that says too little to score (data_sufficiency.py). It is not a band: none of the three
# values below is ever produced from a number, and no number is ever read back as one of them.
INSUFFICIENT_LABEL = "Insufficient data"
INSUFFICIENT_PRIORITY = "Unrated"
INSUFFICIENT_APPLY = "Not assessed"


def match_label(score: int) -> str:
    if score >= 85:
        return "Excellent"
    if score >= 70:
        return "Strong"
    if score >= 55:
        return "Good"
    if score >= 40:
        return "Weak"
    return "Reject"


def apply_recommendation(score: int, red_flags: list[str]) -> str:
    if any("Avoid role" in f or "Avoided industry" in f for f in red_flags):
        return "Skip"
    if score >= APPLY_MIN_SCORE:
        return "Apply"
    if score >= 40:
        return "Maybe"
    return "Skip"


def priority(score: int, apply_rec: str, red_flags: list[str]) -> str:
    if apply_rec == "Skip" or score < 40:
        return "Reject"
    if any("Avoid role" in f for f in red_flags):
        return "Reject"
    if score >= P1_MIN_SCORE:
        return "P1"
    if score >= 55:
        return "P2"
    return "P3"
