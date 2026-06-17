"""Deterministic Markdown scorecard renderer for a grounded capability rating.

Reuses portfolio.render._escape for safe Markdown interpolation.
Emits NO percentile, population-comparison, or external-baseline wording.
"""

from __future__ import annotations

from portfolio.model import Portfolio
from portfolio.render import _escape
from rating.grade import GradeResult
from rating.profile import ProfileResult

# Fixed rubric table — pinned values, shown in every rendered scorecard.
_RUBRIC_TABLE = """\
| Grade | Score band |
|-------|------------|
| S     | 96–100     |
| A     | 85–95      |
| B     | 70–84      |
| C     | 55–69      |
| D     | 0–54       |"""


def render_rating(
    portfolio: Portfolio,
    profile_result: ProfileResult,
    grade_result: GradeResult,
) -> str:
    """Render a grounded capability rating scorecard to Markdown.

    Includes: grade, score, per-dimension metrics with evidence refs and bands,
    grounded reasoning/highlights, and the fixed rubric table.
    Contains NO percentile, external-baseline, or population-comparison wording.
    """
    lines: list[str] = []

    lines.append(f"# Capability Rating — {_escape(portfolio.subject)}")
    lines.append("")
    lines.append(
        f"**Grade: {grade_result.grade}** | **Score: {grade_result.score}** "
        f"(band {profile_result.score_min}–{profile_result.score_max})"
    )
    lines.append("")
    lines.append(
        "> This score is a rubric-based assessment of this developer's own "
        "grounded evidence — not a comparison to other engineers or a position "
        "in any population."
    )
    lines.append("")

    # --- Per-dimension metrics ---
    lines.append("## Dimensions")
    lines.append("")
    for dim_name, dim in profile_result.dimensions.items():
        heading = dim_name.replace("_", " ").title()
        lines.append(f"### {_escape(heading)}")
        lines.append(f"- Value: {dim.value}  Band: {dim.band}  Points: {dim.points}")
        if dim.evidence_refs:
            refs_str = ", ".join(_escape(r) for r in dim.evidence_refs)
            lines.append(f"- Evidence refs: {refs_str}")
        lines.append("")

    # --- Grounded reasoning / highlights ---
    lines.append("## Assessment")
    lines.append("")
    for bullet in grade_result.reasoning:
        text = _escape(bullet["text"])
        refs = bullet.get("evidence_refs", [])
        if refs:
            refs_str = ", ".join(_escape(r) for r in refs)
            lines.append(f"- {text} _(refs: {refs_str})_")
        else:
            lines.append(f"- {text}")
    lines.append("")

    # --- Fixed rubric table ---
    lines.append("## Rubric")
    lines.append("")
    lines.append(_RUBRIC_TABLE)
    lines.append("")

    return "\n".join(lines)
