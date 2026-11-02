"""ATS-safe plain DOCX resume export (no tables/columns)."""

from __future__ import annotations

import os
from pathlib import Path

from atomic_write import PRIVATE_FILE_MODE, make_private_dirs


def render_resume_docx(ctx: dict, output_path: Path) -> bool:
    try:
        from docx import Document
        from docx.shared import Pt
    except ImportError:
        return False

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    name = ctx.get("name") or "Candidate"
    doc.add_heading(name, level=0)
    if ctx.get("subtitle"):
        doc.add_paragraph(ctx["subtitle"])
    if ctx.get("contact"):
        doc.add_paragraph(ctx["contact"])

    summary = ctx.get("summary") or ctx.get("about_me") or ""
    if summary:
        doc.add_heading("Professional Summary", level=1)
        doc.add_paragraph(summary)

    experience = ctx.get("experience") or []
    if experience:
        doc.add_heading("Experience", level=1)
        for job in experience:
            header = f"{job.get('company', '')} — {job.get('title', '')}"
            dates = job.get("dates") or ""
            p = doc.add_paragraph()
            p.add_run(header).bold = True
            if dates:
                p.add_run(f" ({dates})")
            for bullet in job.get("bullets") or []:
                doc.add_paragraph(bullet, style="List Bullet")

    skills = ctx.get("skill_categories") or []
    if skills:
        doc.add_heading("Skills", level=1)
        for cat in skills:
            label = cat.get("label") or "Skills"
            items = ", ".join(cat.get("skills") or [])
            if items:
                doc.add_paragraph(f"{label}: {items}")

    education = ctx.get("education")
    if isinstance(education, dict):
        # Same parts and order as the HTML: degree, school, year. A part the
        # profile does not state is left out, never filled in.
        line = ", ".join(p for p in (education.get("degree"), education.get("school")) if p)
        if education.get("graduated"):
            line = f"{line} ({education['graduated']})" if line else ""
        if line:
            doc.add_heading("Education", level=1)
            doc.add_paragraph(line)
    elif education:
        doc.add_heading("Education", level=1)
        doc.add_paragraph(str(education))

    if ctx.get("languages_text"):
        doc.add_heading("Languages", level=1)
        doc.add_paragraph(ctx["languages_text"])

    make_private_dirs(output_path.parent)
    existed = output_path.exists()
    doc.save(str(output_path))
    if not existed:
        os.chmod(output_path, PRIVATE_FILE_MODE)  # python-docx writes the file itself; rewriting one keeps its mode
    return True
