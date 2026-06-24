"""Markdown renderer for /fit results.

Pure function: reuses portfolio.render._escape; no model/subprocess/network call.
"""

from __future__ import annotations

from fit.grade import GradeResult
from fit.score import ScoreResult
from portfolio.i18n import LANGS
from portfolio.render import _escape

_TOP_GAPS_N = 5


def _escape_cell(text: str) -> str:
    """Escape a value for use inside a Markdown table cell.

    Handles:
    - Carriage returns (\\r): replaced with a single space before delegating
    - Newlines (\\n): delegated to portfolio.render._escape (replaced with space)
    - Markdown-significant characters (`` ` [ ] \\ * _ # < > ``): delegated to _escape
    - Pipe (|): backslash-escaped as \\|
    """
    # Replace \r first so _escape sees spaces not CR
    text = text.replace("\r", " ")
    # Delegate to the existing escaper for \n and Markdown specials
    text = _escape(text)
    # Escape pipes (table cell delimiter not handled by portfolio.render._escape)
    return text.replace("|", "\\|")


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


def render_fit_batch(
    results: list[tuple[str, ScoreResult]],
    lang: str = "en",
) -> str:
    """Render a ranked Markdown table of batch JD scoring results.

    Columns (in order): JD, Grade, Score, Coverage%, Top Gaps.
    Rows are sorted: Score descending, Coverage% descending, JD basename ascending.
    Score is the band midpoint (min + max) // 2.
    Top Gaps is the first 5 elements of sorted(score_result.gaps).
    Column headers come from LANGS[lang]; no hardcoded English UI strings.

    Cell values are escaped with _escape_cell (handles |, \\r, \\n, Markdown specials).
    UI strings (none_notice, column headers) are rendered directly without escaping.
    """
    strings = LANGS[lang]

    col_jd = strings["batch_col_jd"]
    col_grade = strings["batch_col_grade"]
    col_score = strings["batch_col_score"]
    col_coverage = strings["batch_col_coverage"]
    col_top_gaps = strings["batch_col_top_gaps"]

    def _sort_key(item: tuple[str, ScoreResult]) -> tuple:
        basename, sr = item
        score = (sr.band[0] + sr.band[1]) // 2
        return (-score, -sr.coverage_pct, basename)

    sorted_results = sorted(results, key=_sort_key)

    header = f"| {col_jd} | {col_grade} | {col_score} | {col_coverage} | {col_top_gaps} |"
    sep = (
        f"|{'-' * (len(col_jd) + 2)}"
        f"|{'-' * (len(col_grade) + 2)}"
        f"|{'-' * (len(col_score) + 2)}"
        f"|{'-' * (len(col_coverage) + 2)}"
        f"|{'-' * (len(col_top_gaps) + 2)}|"
    )

    lines = [header, sep]

    for basename, sr in sorted_results:
        score = (sr.band[0] + sr.band[1]) // 2
        coverage_str = f"{sr.coverage_pct:.0f}%"

        top_gap_tokens = sorted(sr.gaps)[:_TOP_GAPS_N]
        if top_gap_tokens:
            gaps_str = ", ".join(_escape_cell(g) for g in top_gap_tokens)
        else:
            gaps_str = strings["none_notice"]

        lines.append(f"| {_escape_cell(basename)} | {_escape_cell(sr.grade)} | {score} | {coverage_str} | {gaps_str} |")

    return "\n".join(lines) + "\n"
