"""LinkedIn ranks its free-text search loosely; the JobSpy provider must drop
what the title filter rejects, as the other providers do, and say how many."""

import logging

import pandas as pd

from providers import jobspy_provider
from providers.jobspy_provider import JobSpyProvider


def _frame(titles):
    return pd.DataFrame([
        {"title": t, "company": "Acme", "location": "Berlin, Germany", "job_url": f"https://x/{i}",
         "description": "product manager roadmap", "site": "linkedin"}
        for i, t in enumerate(titles)
    ])


def test_jobspy_drops_loosely_related_titles_and_logs_the_count(monkeypatch, caplog):
    titles = ["Senior Product Manager", "SAP Consultant", "Product Lead", "Sales Engineer"]
    monkeypatch.setattr(jobspy_provider, "fetch_jobs", lambda *a, **k: _frame(titles))

    with caplog.at_level(logging.INFO):
        jobs = JobSpyProvider().fetch_jobs(["Product Lead"], ["Berlin"], [], "germany")

    kept = {j["title"] for j in jobs}
    assert "Senior Product Manager" in kept and "Product Lead" in kept
    assert "SAP Consultant" not in kept and "Sales Engineer" not in kept
    assert "4 ads fetched, 2 kept after title filtering" in caplog.text
