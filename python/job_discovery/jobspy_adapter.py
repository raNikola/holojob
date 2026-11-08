"""JobSpy adapter with per-site graceful fallback."""

from __future__ import annotations

import logging
import warnings

import pandas as pd

logger = logging.getLogger(__name__)

# JobSpy site ids (Indeed / Glassdoor require country_indeed + location for narrowing)
SITE_LINKEDIN = "linkedin"
SITE_INDEED = "indeed"
SITE_GLASSDOOR = "glassdoor"

ALL_SITES  = [SITE_LINKEDIN, SITE_INDEED, SITE_GLASSDOOR]
LINKEDIN_ONLY = [SITE_LINKEDIN]
RESULTS_PER_SEARCH = 50
HOURS_OLD = 72
DEFAULT_COUNTRY = "USA"

# Exact Indeed / Glassdoor country names (JobSpy Country.from_string compatible).
# Glassdoor support marked with * in JobSpy docs; all listed countries work on Indeed.
INDEED_GLASSDOOR_COUNTRY_NAMES = {
    "argentina": "Argentina",
    "australia": "Australia",
    "austria": "Austria",
    "bahrain": "Bahrain",
    "belgium": "Belgium",
    "brazil": "Brazil",
    "canada": "Canada",
    "chile": "Chile",
    "china": "China",
    "colombia": "Colombia",
    "costa rica": "Costa Rica",
    "czech republic": "Czech Republic",
    "czechia": "Czech Republic",
    "denmark": "Denmark",
    "ecuador": "Ecuador",
    "egypt": "Egypt",
    "finland": "Finland",
    "france": "France",
    "germany": "Germany",
    "greece": "Greece",
    "hong kong": "Hong Kong",
    "hungary": "Hungary",
    "indonesia": "Indonesia",
    "ireland": "Ireland",
    "israel": "Israel",
    "italy": "Italy",
    "japan": "Japan",
    "kuwait": "Kuwait",
    "luxembourg": "Luxembourg",
    "malaysia": "Malaysia",
    "mexico": "Mexico",
    "morocco": "Morocco",
    "netherlands": "Netherlands",
    "new zealand": "New Zealand",
    "nigeria": "Nigeria",
    "norway": "Norway",
    "oman": "Oman",
    "pakistan": "Pakistan",
    "panama": "Panama",
    "peru": "Peru",
    "philippines": "Philippines",
    "poland": "Poland",
    "portugal": "Portugal",
    "qatar": "Qatar",
    "romania": "Romania",
    "saudi arabia": "Saudi Arabia",
    "singapore": "Singapore",
    "south africa": "South Africa",
    "south korea": "South Korea",
    "spain": "Spain",
    "sweden": "Sweden",
    "switzerland": "Switzerland",
    "taiwan": "Taiwan",
    "thailand": "Thailand",
    "turkey": "Turkey",
    "türkiye": "Turkey",
    "ukraine": "Ukraine",
    "united arab emirates": "United Arab Emirates",
    "uae": "United Arab Emirates",
    "uk": "UK",
    "united kingdom": "UK",
    "gb": "UK",
    "usa": "USA",
    "us": "USA",
    "united states": "USA",
    "uruguay": "Uruguay",
    "venezuela": "Venezuela",
    "vietnam": "Vietnam",
}

def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame()

def is_country_supported(country: str) -> bool:
    """Check if a country is supported by Indeed/Glassdoor."""
    key = (country or "").strip().lower()
    return key in INDEED_GLASSDOOR_COUNTRY_NAMES


def _sites_for_country(country: str) -> list[str]:
    """Return the list of JobSpy sites to use for a given country."""
    if is_country_supported(country):
        return list(ALL_SITES)
    logger.warning(
        "Country %r not in Indeed/Glassdoor list — using LinkedIn only.", country
    )
    return list(LINKEDIN_ONLY)

def normalize_country(country: str) -> str | None:
    """Map input to exact Indeed/Glassdoor country name for country_indeed.

    Returns None if the country is not supported by Indeed/Glassdoor,
    instead of silently falling back to USA.
    """
    key = (country or "").strip().lower()
    if not key:
        return DEFAULT_COUNTRY

    exact = INDEED_GLASSDOOR_COUNTRY_NAMES.get(key)
    if exact:
        return exact

    return None


def _strip_country_suffix(location: str, country: str) -> str:
    """Remove trailing ', Country' when country_indeed already scopes the search."""
    loc = location.strip()
    country_lower = country.lower()
    for suffix in (country, country_lower):
        needle = f", {suffix}"
        if loc.lower().endswith(needle.lower()):
            return loc[: -len(needle)].strip()
    return loc


def _narrow_location_for_country(location: str, country: str) -> str:
    """Narrow location to the city part for Indeed/Glassdoor APIs."""
    # US-style "City, ST" and other "City, Region" strings pass through
    return _strip_country_suffix(location, country)


def _resolve_location(location: str, remote: bool, country: str) -> tuple[str, bool]:
    """
    Resolve location for JobSpy.

    Indeed and Glassdoor require country_indeed separately; use location only
    to narrow by city/state. For remote searches, leave location empty and set
    is_remote=True.
    """
    loc = (location or "").strip()
    if loc.lower() == "remote":
        return "", True
    if remote:
        return "", True

    country_norm = normalize_country(country)
    if not loc:
        return "", False

    # For unsupported countries, keep full location for LinkedIn global search
    if country_norm is None:
        return loc, False

    narrowed = _narrow_location_for_country(loc, country_norm)
    return narrowed, False


def _scrape(
    site_names: list[str],
    search_term: str,
    location: str,
    remote: bool,
    country: str,
) -> pd.DataFrame:
    from jobspy import scrape_jobs

    country_norm = normalize_country(country)

    scrape_kwargs = dict(
        site_name=site_names,
        search_term=search_term,
        location=location or None,
        results_wanted=RESULTS_PER_SEARCH,
        hours_old=HOURS_OLD,
        is_remote=remote,
        fetch_description=True,
        verbose=1,
    )

    # Only pass country_indeed for supported countries
    if country_norm is not None:
        scrape_kwargs["country_indeed"] = country_norm

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return scrape_jobs(**scrape_kwargs)


def fetch_jobs(
    search_term: str,
    location: str,
    remote: bool = False,
    country: str = DEFAULT_COUNTRY,
) -> pd.DataFrame:
    """Fetch jobs for one search term and location. Never raises — returns empty DataFrame on total failure."""
    loc, is_remote = _resolve_location(location, remote, country)
    sites = _sites_for_country(country)
    country_norm = normalize_country(country)

    logger.info(
        "JobSpy search: term=%r location=%r is_remote=%s country=%r "
        "country_indeed=%s sites=%s",
        search_term,
        loc or "(empty)",
        is_remote,
        country,
        country_norm or "(unsupported)",
        sites,
    )

    try:
        df = _scrape(sites, search_term, loc, is_remote, country)
        if df is not None and not df.empty:
            df.attrs["sitesFailed"] = []
            return df
    except Exception as exc:
        logger.warning("Batch scrape failed for %r @ %r: %s", search_term, loc or "remote", exc)

    frames: list[pd.DataFrame] = []
    sites_failed: list[str] = []  # sites that raised (throttle, block, timeout): their silence proves nothing
    for site in sites:
        try:
            df = _scrape([site], search_term, loc, is_remote, country)
            if df is not None and not df.empty:
                frames.append(df)
                label = "Indeed" if site == SITE_INDEED else "Glassdoor" if site == SITE_GLASSDOOR else site
                logger.info(
                    "Recovered %d jobs from %s for %r @ %r (country=%s)",
                    len(df),
                    label,
                    search_term,
                    loc or "remote",
                    country_norm,
                )
        except Exception as exc:
            sites_failed.append(site)
            label = "Indeed" if site == SITE_INDEED else "Glassdoor" if site == SITE_GLASSDOOR else site
            logger.warning(
                "%s failed for %r @ %r (country=%s): %s",
                label,
                search_term,
                loc or "remote",
                country_norm,
                exc,
            )

    frames = [f for f in frames if f is not None and not f.empty]
    if not frames:
        empty = _empty_frame()
        empty.attrs["sitesFailed"] = list(sites_failed)  # the caller tells a blocked search from a really empty one
        return empty

    merged = pd.concat(frames, ignore_index=True)
    merged.attrs["sitesFailed"] = list(sites_failed)  # ads from the sites that answered are kept
    return merged
