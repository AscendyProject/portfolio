"""Deterministic Markdown scorecard renderer for a grounded capability rating.

Reuses portfolio.render._escape for safe Markdown interpolation.
Emits NO percentile, population-comparison, or external-baseline wording.
"""

from __future__ import annotations

from portfolio.i18n import LANGS
from portfolio.model import Portfolio
from portfolio.render import _escape
from rating.grade import GradeResult
from rating.profile import ProfileResult


def render_rating(
    portfolio: Portfolio,
    profile_result: ProfileResult,
    grade_result: GradeResult,
    *,
    show_refs: bool = False,
    lang: str = "en",
) -> str:
    """Render a grounded capability rating scorecard to Markdown.

    Includes: grade, score, per-dimension metrics with evidence refs and bands,
    grounded reasoning/highlights, and the fixed rubric table.
    Contains NO percentile, external-baseline, or population-comparison wording.
    """
    strings = LANGS[lang]
    lines: list[str] = []

    lines.append(f"# {strings['title_rating']} — {_escape(portfolio.subject)}")
    lines.append("")
    lines.append(
        f"**{strings['grade_label']}: {grade_result.grade}** | **{strings['score_label_rating']}: {grade_result.score}** "
        f"({strings['band_label']} {profile_result.score_min}–{profile_result.score_max})"
    )
    lines.append("")
    lines.append(strings["rating_disclaimer"])
    lines.append("")

    # --- Per-dimension metrics ---
    lines.append(f"## {strings['section_dimensions']}")
    lines.append("")
    dimension_names = strings.get("dimension_names", {})
    band_labels = strings.get("band_labels", {})
    for dim_name, dim in profile_result.dimensions.items():
        # All real dimension keys / band values are mapped in LANGS for every
        # supported language (enforced by test_dimension_band_tables_complete),
        # so these lookups never fall back to the raw identifier — no
        # untranslated English UI can leak into a localized render (IR-004).
        heading = dimension_names.get(dim_name, dim_name)
        band_label = band_labels.get(dim.band, dim.band)
        lines.append(f"### {_escape(heading)}")
        lines.append(
            f"- {strings['dim_value_label']}: {dim.value}  "
            f"{strings['dim_band_label']}: {band_label}  "
            f"{strings['dim_points_label']}: {dim.points}"
        )
        if show_refs and dim.evidence_refs:
            refs_str = ", ".join(_escape(r) for r in dim.evidence_refs)
            lines.append(f"- {strings['evidence_refs_label']}: {refs_str}")
        lines.append("")

    # --- Grounded reasoning / highlights ---
    lines.append(f"## {strings['section_assessment']}")
    lines.append("")
    for bullet in grade_result.reasoning:
        text = _escape(bullet["text"])
        refs = bullet.get("evidence_refs", [])
        if show_refs and refs:
            refs_str = ", ".join(_escape(r) for r in refs)
            lines.append(f"- {text} _({strings['refs_inline_label']}: {refs_str})_")
        else:
            lines.append(f"- {text}")
    lines.append("")

    # --- Fixed rubric table ---
    lines.append(f"## {strings['section_rubric']}")
    lines.append("")
    lines.append(strings["rating_rubric"])
    lines.append("")

    return "\n".join(lines)
