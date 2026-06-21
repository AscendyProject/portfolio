"""Markdown renderer for /fit results.

Pure function: reuses portfolio.render._escape; no model/subprocess/network call.
"""

from __future__ import annotations

from fit.grade import GradeResult
from fit.score import ScoreResult
from portfolio.i18n import LANGS
from portfolio.render import _escape


def render_fit(
    score_result: ScoreResult,
    grade_result: GradeResult,
    *,
    show_refs: bool = False,
    lang: str = "en",
) -> str:
    """Render the /fit analysis as a Markdown string.

    Contains:
    - Grade letter and score
    - Coverage%
    - Covered requirements section (JD keywords + grounded refs)
    - Gaps section (uncovered JD keywords)
    - Grounded reasoning bullets
    - Full grade→band rubric table

    Makes no model, subprocess, or network call.
    """
    strings = LANGS[lang]
    lines: list[str] = []

    grade = score_result.grade
    score = grade_result.score
    band = score_result.band
    coverage_pct = score_result.coverage_pct

    lines.append(f"# {strings['title_fit']} — {strings['grade_label']} {_escape(grade)}")
    lines.append("")
    lines.append(f"**{strings['score_label']}:** {score} / 100  ({strings['band_label']}: {band[0]}–{band[1]})")
    lines.append("")
    lines.append(f"**{strings['jd_coverage_label']}:** {coverage_pct:.0f}%")
    lines.append("")

    # Covered requirements
    lines.append(f"## {strings['section_covered']}")
    lines.append("")
    if score_result.covered:
        for kw in sorted(score_result.covered.keys()):
            refs = score_result.covered[kw]
            if show_refs:
                refs_str = ", ".join(_escape(r) for r in refs)
                lines.append(f"- `{_escape(kw)}` — {refs_str}")
            else:
                lines.append(f"- `{_escape(kw)}`")
    else:
        lines.append(strings["none_notice"])
    lines.append("")

    # Gaps
    lines.append(f"## {strings['section_gaps']}")
    lines.append("")
    if score_result.gaps:
        for kw in sorted(score_result.gaps):
            lines.append(f"- `{_escape(kw)}`")
    else:
        lines.append(strings["none_notice"])
    lines.append("")

    # Grounded reasoning
    lines.append(f"## {strings['section_grounded_reasoning']}")
    lines.append("")
    if grade_result.reasoning:
        for bullet in grade_result.reasoning:
            text = _escape(str(bullet.get("text", "")))
            refs = bullet.get("evidence_refs", [])
            if show_refs and refs:
                refs_str = ", ".join(_escape(r) for r in refs)
                lines.append(f"- {text} _({strings['refs_inline_label']}: {refs_str})_")
            else:
                lines.append(f"- {text}")
    else:
        lines.append(strings["no_grounded_reasoning"])
    lines.append("")

    # Grade→band rubric table
    lines.append(f"## {strings['section_grade_rubric']}")
    lines.append("")
    lines.append(strings["fit_rubric"])
    lines.append("")

    return "\n".join(lines)
