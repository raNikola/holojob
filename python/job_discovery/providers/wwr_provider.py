"""We Work Remotely RSS feed provider."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET

import requests

from providers.base_provider import JobProvider, build_canonical_job, dropped_ad, filter_jobs, parts_outcome, split_by_filter

logger = logging.getLogger(__name__)

RSS_FEEDS = [
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
]


class WWRProvider(JobProvider):
    provider_name = "wwr"

    def _parse_feed(self, url: str) -> list[dict]:
        """The feed's postings; raises when it cannot be read."""
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        items = []
        for item in root.findall(".//item"):
            title_raw = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            description = (item.findtext("description") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            company, title = self._split_title(title_raw)
            items.append({
                "guid": (item.findtext("guid") or "").strip(),
                "title": title,
                "company": company,
                "link": link,
                "description": description,
                "pubDate": pub_date,
            })
        return items

    @staticmethod
    def _split_title(title_raw: str) -> tuple[str, str]:
        """WWR titles are often 'Company: Role'."""
        if ":" in title_raw:
            parts = title_raw.split(":", 1)
            return parts[0].strip(), parts[1].strip()
        return "Unknown", title_raw

    def fetch_jobs(
        self,
        search_terms: list[str],
        locations: list[str],
        remote_filters: list[str],
        country: str,
    ) -> list[dict]:
        primary_term = search_terms[0] if search_terms else ""
        primary_loc = locations[0] if locations else ""
        all_jobs: list[dict] = []
        seen_urls: set[str] = set()
        failures: dict[str, str] = {}

        for feed_url in RSS_FEEDS:
            try:
                postings = self._parse_feed(feed_url)
            except Exception as exc:
                logger.warning("WWR feed %s failed: %s", feed_url, exc)
                failures[feed_url] = str(exc)
                continue
            feed_jobs, external, dropped = [], {}, []
            for posting in postings:
                url = posting.get("link") or ""
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                description = re.sub(r"<[^>]+>", " ", posting.get("description") or "")
                job = build_canonical_job(
                    provider="wwr",
                    source="weworkremotely",
                    title=posting.get("title") or "",
                    company=posting.get("company") or "Unknown",
                    location="Remote",
                    job_url=url,
                    description=description,
                    is_remote=True,
                    date_posted=posting.get("pubDate") or "",
                    search_term=primary_term,
                    search_location=primary_loc,
                    site="weworkremotely",
                )
                if job["title"]:
                    feed_jobs.append(job)
                    external[job["jobId"]] = posting.get("guid")
                else:  # never counted as read
                    dropped.append(dropped_ad(job, "no_title", posting.get("guid"), counted=False))
            all_jobs.extend(feed_jobs)
            # The feed is staged as soon as it is read (filtered the way the whole list is below), so a stop keeps it.
            feed_kept, feed_dropped = split_by_filter(feed_jobs, search_terms, locations, remote_filters, country)
            self.stage(
                feed_kept, part=feed_url, read=len(feed_jobs), external_ids=external,
                dropped=dropped + [dropped_ad(job, reason, external.get(job["jobId"])) for job, reason in feed_dropped],
            )

        kept = filter_jobs(all_jobs, search_terms, locations, remote_filters, country)
        self.last_outcome = parts_outcome(read=len(all_jobs), kept=len(kept), total=len(RSS_FEEDS), failures=failures)
        return kept
