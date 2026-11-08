"""Infostud provider -- coverage of the Serbian domestic job market.

LinkedIn, via JobSpy, carries international and remote roles but very little
of what Serbian employers post locally. Infostud is where those ads live.

Role filtering happens in infostud_client, not through filter_jobs(). The
client matches on Infostud's hand-assigned standardizedPosition, which
catches ads whose title never spells out the role -- "Customer Channels AI
Product and Delivery Expert" is tagged Product Manager by the board itself.
Running matches_search_terms() on top would discard exactly those.
"""

from __future__ import annotations

import logging

from providers import infostud_client
from providers.base_provider import (
    READ_INCOMPLETE,
    JobProvider,
    ProviderOutcome,
    board_read,
    build_canonical_job,
    dropped_ad,
    place_drop_reason,
)

logger = logging.getLogger(__name__)

SUPPORTED_COUNTRIES = {"serbia", "srbija"}


BOARD = "infostud"  # the whole six-category listing is one board: it has one reported total

# Reasons a listing read is not proof that it was whole (Wave 4, c). They end up as the board's `reason` in the staging footer.
CAP_HIT = "the page cap stopped the read before the reported total"
CLAMP_HIT = "a page held no new ad before the reported total was reached"
EMPTY_BEFORE_TOTAL = "an empty page ended the read before the reported total"
NO_TOTAL = "the site reported no total, so the read cannot be checked"
TOTAL_MISMATCH = "the ads read differ in number from the reported total"


def completeness(read: int, reported: int | None, facts: dict | None) -> tuple[bool, str | None]:
    """(complete, reason): was the listing read whole? True only when the read ended by reaching the reported total, the ads read
    are exactly that many, and neither the page cap, the clamp guard nor an empty page stopped it. Nothing else is proof; a
    missing `facts` (an old caller) is never proof."""
    facts = facts or {}
    if not reported:
        return False, NO_TOTAL
    if facts.get("capHit"):
        return False, CAP_HIT
    if facts.get("clampHit"):
        return False, CLAMP_HIT
    if facts.get("emptyEnd") and read < reported:
        return False, EMPTY_BEFORE_TOTAL
    if read != reported:
        return False, TOTAL_MISMATCH
    if not facts.get("reachedTotal"):
        return False, EMPTY_BEFORE_TOTAL
    return True, None


class InfostudProvider(JobProvider):
    provider_name = "infostud"

    def fetch_jobs(
        self,
        search_terms: list[str],
        locations: list[str],
        remote_filters: list[str],
        country: str,
    ) -> list[dict]:
        if (country or "").strip().lower() not in SUPPORTED_COUNTRIES:
            logger.info(
                "Infostud covers Serbia only -- skipping for country=%r", country
            )
            self.last_outcome = ProviderOutcome(status="skipped", skip_reason=f"Infostud covers Serbia only, not {country!r}")
            return []

        counts: dict = {}
        canonical: list[dict] = []

        def drop_at_listing(dropped: list) -> None:
            # The role filter has run over the whole listing: its drops are known before the slow part begins.
            self.stage([], part="listing", read=counts.get("read"), dropped=[
                dropped_ad(self._to_canonical(raw), reason, raw.get("externalId")) for raw, reason in dropped
            ])

        def keep_as_it_comes(raw: dict) -> None:
            # An ad is final once its full description is read, and that is one slow request per ad, so it is staged
            # here, not at the end. The same object is returned below, so what is staged is what the run gets.
            job = self._to_canonical(raw)
            canonical.append(job)
            reason = place_drop_reason(job, locations, remote_filters, country)
            if reason is None:
                self.stage([job], part=job["jobId"], external_ids={job["jobId"]: raw.get("externalId")})
            else:
                self.stage([], part=job["jobId"], dropped=[dropped_ad(job, reason, raw.get("externalId"))])

        try:
            raw_jobs = infostud_client.fetch_jobs(
                extra_terms=tuple(search_terms or ()),
                counts=counts,
                on_job=keep_as_it_comes,
                on_drop=drop_at_listing,
            )
        except Exception as exc:
            logger.exception("Infostud fetch failed; continuing without it")
            self.last_outcome = ProviderOutcome(status="failed", error=str(exc))
            return []

        logger.info("Infostud: %d relevant ads before geo filtering", len(raw_jobs))

        jobs = canonical if len(canonical) == len(raw_jobs) else [self._to_canonical(job) for job in raw_jobs]
        kept = [
            job
            for job in jobs
            if place_drop_reason(job, locations, remote_filters, country) is None
        ]
        logger.info("Infostud: %d jobs after geo filtering", len(kept))
        read = counts.get("read", len(raw_jobs))
        complete, why = completeness(read, counts.get("reported"), counts.get("facts"))
        facts = counts.get("facts") or {}
        # Wave 4 (c): the proof is recorded on every run, but Infostud stays search-based until job_history.SNAPSHOT_AFTER_PROOF is set,
        # so nothing is closed by it. An incomplete read is also called incomplete, as for the other sources.
        self.last_outcome = ProviderOutcome(
            read=read, kept=len(kept), total_reported=counts.get("reported"),
            read_class=None if complete or not read else READ_INCOMPLETE,
            boards_read=[board_read(
                BOARD, read=read, postings=read, complete=complete, reason=why, reportedTotal=counts.get("reported"),
                pages=facts.get("pages"), capHit=bool(facts.get("capHit")), clampHit=bool(facts.get("clampHit")),
            )],
        )
        return kept

    @staticmethod
    def _to_canonical(job: dict) -> dict:
        canonical = build_canonical_job(
            provider="infostud",
            source="infostud",
            site="infostud",
            title=job.get("title", ""),
            company=job.get("company", ""),
            location=job.get("location", ""),
            job_url=job.get("jobUrl", ""),
            description=job.get("description", ""),
            salary=job.get("salary") or "",
            employment_type=job.get("employmentType") or "",
            is_remote=bool(job.get("isRemote")),
            date_posted=job.get("datePosted") or "",
            search_location="Serbia",
        )
        # Infostud-specific context the canonical shape has no slot for.
        canonical["workMode"] = job.get("workMode")
        canonical["expiresAt"] = job.get("expiresAt")
        canonical["category"] = job.get("category")
        canonical["standardizedPosition"] = job.get("standardizedPosition")
        canonical["tags"] = job.get("tags") or []
        return canonical