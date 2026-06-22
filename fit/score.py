"""Deterministic JD coverage scoring and grade assignment.

Pure function: no model call, no subprocess, no network, no file I/O.
Stdlib-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from portfolio.model import Portfolio
from resume.select import jd_keywords

# ── Pinned coverage% → grade cutoffs ─────────────────────────────────────────
# Importable so tests can assert them directly.
# Read as "≥ this value → this grade" (checked S first, then A, B, C, else D).
COVERAGE_CUTOFFS: dict[str, int] = {
    "S": 90,
    "A": 75,
    "B": 55,
    "C": 35,
}

# ── Pinned grade → score band [min, max] ─────────────────────────────────────
GRADE_BANDS: dict[str, tuple[int, int]] = {
    "S": (96, 100),
    "A": (85, 95),
    "B": (70, 84),
    "C": (55, 69),
    "D": (0, 54),
}

# ── Non-codeable axes (Part C) ────────────────────────────────────────────────
# Stored in their _stem'd form so they compare correctly against stemmed JD tokens.
# _stem("japanese") = "japanese", _stem("english") = "english",
# _stem("korean") = "korean", _stem("years") = "year",
# _stem("bachelors") = "bachelor", _stem("degree") = "degree",
# _stem("bs") = "bs", _stem("ms") = "ms", _stem("phd") = "phd",
# _stem("master") = "master", _stem("masters") = "master",
# _stem("sales") = "sale"
NON_CODE_AXES: frozenset[str] = frozenset(
    {
        "japanese",
        "english",
        "korean",
        "year",
        "bachelor",
        "degree",
        "bs",
        "ms",
        "phd",
        "master",
        "sale",
    }
)


def _claim_tokens(claim_text: str, evidence_refs: list[str]) -> set[str]:
    """Derive tokens from a claim's text + evidence_refs using the same rule as jd_keywords.

    Replicates the `claim.text + " " + " ".join(evidence_refs)` → jd_keywords rule
    locally without making resume.select._claim_tokens public.
    """
    combined = claim_text + " " + " ".join(evidence_refs)
    return jd_keywords(combined)


@dataclass
class ScoreResult:
    """Result of scoring a portfolio against a JD."""

    coverage_pct: float
    covered: dict[str, list[str]]  # keyword → list of evidence_refs that covered it
    gaps: set[str]  # JD keywords not covered by any valid grounded claim
    grade: str  # one of S/A/B/C/D
    band: tuple[int, int]  # [min, max] score band for the grade
    non_code_requirements: set[str] = field(default_factory=set)  # JD tokens excluded as non-codeable axes


def score_fit(portfolio: Portfolio, jd_text: str) -> ScoreResult:
    """Compute JD coverage and deterministic grade for a grounded portfolio.

    Deterministic: same portfolio + jd_text → identical result across repeated calls.
    Performs no model call, no subprocess, no network, no file I/O.

    A claim contributes to coverage only if:
    - Its evidence_refs is non-empty, AND
    - All its evidence_refs are ⊆ the portfolio's evidence ref set.

    Any claim failing those conditions is silently ignored; its JD overlap falls
    into the gap set if no other valid claim covers those keywords.

    Part C: NON_CODE_AXES tokens are excluded from both numerator and denominator.
    """
    jd_kw_all = jd_keywords(jd_text)
    real_refs = {e.ref for e in portfolio.evidence}

    # Separate non-codeable axes from codeable requirements
    non_code = jd_kw_all & NON_CODE_AXES
    jd_kw = jd_kw_all - NON_CODE_AXES

    covered: dict[str, list[str]] = {}  # keyword → evidence_refs from the covering claim

    for claim in portfolio.claims:
        refs = claim.evidence_refs
        # A claim contributes only if it has refs AND all refs are in the portfolio
        if not refs:
            continue
        if not set(refs) <= real_refs:
            continue
        # Compute token overlap with JD keywords (codeable only)
        tokens = _claim_tokens(claim.text, refs)
        overlap = jd_kw & tokens
        for kw in overlap:
            if kw not in covered:
                covered[kw] = list(refs)

    gaps = jd_kw - set(covered.keys())

    if jd_kw:
        coverage_pct = len(covered) / len(jd_kw) * 100
    else:
        coverage_pct = 100.0

    # Assign grade from pinned cutoffs (checked in order: S, A, B, C, else D)
    grade = "D"
    for g in ("S", "A", "B", "C"):
        if coverage_pct >= COVERAGE_CUTOFFS[g]:
            grade = g
            break

    band = GRADE_BANDS[grade]
    return ScoreResult(
        coverage_pct=coverage_pct,
        covered=covered,
        gaps=gaps,
        grade=grade,
        band=band,
        non_code_requirements=non_code,
    )
