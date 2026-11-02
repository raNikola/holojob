"""Render HTML to PDF via Playwright Chromium.

Margins live in the template CSS (HOLOJOB_GENERATION_CONTEXT.md Part 6), so Chromium
margins are zero. Includes the single-page overflow ladder from Part 2.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable

from atomic_write import PRIVATE_FILE_MODE, make_private_dirs

logger = logging.getLogger(__name__)

# Part 2 overflow ladder — applied in order, one small step at a time.
FIT_LADDER: list[dict] = [
    {},
    {"sec_before": 10},
    {"sec_before": 10, "rule_after": 6},
    {"sec_before": 10, "rule_after": 6, "body_leading": 11.7},
    {"sec_before": 10, "rule_after": 6, "body_leading": 11.7, "job_gap": 6},
    {"sec_before": 10, "rule_after": 6, "body_leading": 11.7, "job_gap": 6, "skills_leading": 12.0},
    {"sec_before": 10, "rule_after": 6, "body_leading": 11.5, "job_gap": 6, "skills_leading": 12.0},
]


# Chromium's own page counter: "Page 1 of 1" printed on every page was wrong on a longer CV.
FOOTER_TEMPLATE = (
    '<div style="width:100%;font-size:8pt;color:#718096;text-align:right;'
    'padding-right:42.52pt;font-family:Helvetica,Arial,sans-serif;">'
    'Page <span class="pageNumber"></span> of <span class="totalPages"></span></div>'
)


def render_pdf(html: str, output_path: Path, *, paper_format: str = "A4", footer: bool = False) -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Playwright not installed; skipping PDF generation")
        return False

    make_private_dirs(output_path.parent)
    existed = output_path.exists()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html, wait_until="networkidle")
            options: dict = {
                "path": str(output_path),
                "format": paper_format,
                "print_background": True,
                "prefer_css_page_size": True,
                "margin": {"top": "0", "bottom": "0", "left": "0", "right": "0"},
            }
            if footer:
                # Room for the footer is the template's bottom page margin (30pt top,
                # 40pt bottom). Playwright takes px, in, mm or cm, not pt.
                options.update(
                    display_header_footer=True,
                    header_template="<span></span>",
                    footer_template=FOOTER_TEMPLATE,
                    margin={"top": "10.58mm", "bottom": "14.11mm", "left": "0", "right": "0"},
                )
            page.pdf(**options)
            browser.close()
        if not existed:
            os.chmod(output_path, PRIVATE_FILE_MODE)  # Playwright writes the file itself; rewriting one keeps its mode
        return True
    except Exception as exc:
        logger.warning("PDF render failed: %s", exc)
        return False


def count_pdf_pages(pdf_path: Path) -> int:
    """Page count for the single-page validation step. -1 if unreadable."""
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(pdf_path)).pages)
    except Exception as exc:
        logger.warning("Page count failed for %s: %s", pdf_path, exc)
        return -1


def render_single_page_pdf(
    render_html: Callable[[dict], str], output_path: Path, *, footer: bool = False
) -> tuple[bool, int]:
    """Render, then walk the fit ladder until the document is one page.

    render_html receives a `fit` dict of CSS overrides. Returns (rendered, final_page_count).
    """
    pages = -1
    for fit in FIT_LADDER:
        if not render_pdf(render_html(fit), output_path, footer=footer):
            return False, -1
        pages = count_pdf_pages(output_path)
        if pages <= 1:
            return True, pages
        logger.info("%s is %d pages with fit=%s; tightening", output_path.name, pages, fit)
    logger.warning("%s still %d pages after full fit ladder — trim content", output_path.name, pages)
    return True, pages
