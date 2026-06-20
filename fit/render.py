"""Markdown renderer for /fit results.

Pure function: reuses portfolio.render._escape; no model/subprocess/network call.
"""

from __future__ import annotations

from fit.grade import GradeResult
from fit.score import ScoreResult
from portfolio.render import _escape


def render_fit(score_result: ScoreResult, grade_result: GradeResult, *, show_refs: bool = False) -> str:
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
    lines: list[str] = []

    grade = score_result.grade
    score = grade_result.score
    band = score_result.band
    coverage_pct = score_result.coverage_pct

    lines.append(f"# Fit Assessment — Grade {_escape(grade)}")
    lines.append("")
    lines.append(f"**Score:** {score} / 100  (band: {band[0]}–{band[1]})")
    lines.append("")
    lines.append(f"**JD Coverage:** {coverage_pct:.0f}%")
    lines.append("")

    # Covered requirements
    lines.append("## Covered Requirements")
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
        lines.append("_none_")
    lines.append("")

    # Gaps
    lines.append("## Gaps")
    lines.append("")
    if score_result.gaps:
        for kw in sorted(score_result.gaps):
            lines.append(f"- `{_escape(kw)}`")
    else:
        lines.append("_none_")
    lines.append("")

    # Grounded reasoning
    lines.append("## Grounded Reasoning")
    lines.append("")
    if grade_result.reasoning:
        for bullet in grade_result.reasoning:
            text = _escape(str(bullet.get("text", "")))
            refs = bullet.get("evidence_refs", [])
            if show_refs and refs:
                refs_str = ", ".join(_escape(r) for r in refs)
                lines.append(f"- {text} _(refs: {refs_str})_")
            else:
                lines.append(f"- {text}")
    else:
        lines.append("_no grounded reasoning provided_")
    lines.append("")

    # Grade→band rubric table
    lines.append("## Grade Rubric")
    lines.append("")
    lines.append("| Grade | Coverage% | Score Band |")
    lines.append("|-------|-----------|------------|")
    lines.append("| S     | ≥90%      | 96–100     |")
    lines.append("| A     | ≥75%      | 85–95      |")
    lines.append("| B     | ≥55%      | 70–84      |")
    lines.append("| C     | ≥35%      | 55–69      |")
    lines.append("| D     | <35%      | 0–54       |")
    lines.append("")

    return "\n".join(lines)
