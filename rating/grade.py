"""Bounded agent grader.

Calls an injectable grader_runner deterministically (temperature=0), clamps the
score to the locked band, grounding-checks the reasoning bullets (drops any bullet
whose evidence_refs ⊄ portfolio.evidence refs), and handles malformed responses
defensively (midpoint score + safe reasoning, no crash, no fabricated refs).

The model may NOT change the grade — grade is always the deterministic grade
computed by rating.profile.profile().
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from portfolio.i18n import language_name
from portfolio.model import Portfolio
from rating.profile import ProfileResult

# A grader runner callable: (prompt, temperature=0) → raw response string.
# The default temperature argument ensures callers signal intent even if the
# underlying service ignores the kwarg.
GraderRunner = Callable[..., str]


@dataclass
class GradeResult:
    score: int
    grade: str  # always == profile_result.grade; model cannot change this
    reasoning: list[dict]  # grounding-checked bullets: [{"text": ..., "evidence_refs": [...]}]


def _build_prompt(portfolio: Portfolio, profile_result: ProfileResult, lang: str = "en") -> str:
    """Build a fixed, deterministic prompt for the grader.

    Same portfolio + profile_result + lang → identical prompt across calls.
    """
    grade = profile_result.grade
    score_min = profile_result.score_min
    score_max = profile_result.score_max

    claims_text = (
        "\n".join(f"- {c.text} (refs: {', '.join(c.evidence_refs)})" for c in portfolio.claims)
        or "(no grounded claims)"
    )

    allowed_refs = ", ".join(e.ref for e in portfolio.evidence) or "(none)"

    return (
        f"You are assessing a developer's capability from their grounded portfolio.\n\n"
        f"LOCKED GRADE: {grade}\n"
        f"SCORE BAND: {score_min}–{score_max}\n\n"
        f"GROUNDED CLAIMS:\n{claims_text}\n\n"
        f"ALLOWED EVIDENCE REFS: {allowed_refs}\n\n"
        f"Your job: pick a score between {score_min} and {score_max} (inclusive) and write "
        f"concise reasoning bullets. Each bullet MUST cite at least one ref from "
        f"ALLOWED EVIDENCE REFS. "
        f"You MUST NOT change the grade. "
        f"You MUST NOT claim a percentile, comparison to a population, or external baseline.\n\n"
        f"Output STRICT JSON only:\n"
        f'{{"score": <integer {score_min}–{score_max}>, '
        f'"reasoning": [{{"text": "<bullet>", "evidence_refs": ["<ref>", ...]}}]}}\n'
        f"No prose, no code fences. JSON only.\n\n"
        f"Write all prose in {language_name(lang)}."
    )


def _midpoint(score_min: int, score_max: int) -> int:
    return (score_min + score_max) // 2


_SAFE_REASONING = [{"text": "Assessment based on grounded evidence.", "evidence_refs": []}]


def _parse_response(
    raw: str,
    portfolio: Portfolio,
    score_min: int,
    score_max: int,
) -> tuple[int, list[dict]]:
    """Parse and validate the grader response.

    Returns (clamped_score, grounding-checked reasoning).
    Malformed response → (midpoint, safe reasoning).
    Reasoning bullets whose evidence_refs ⊄ portfolio.evidence refs are dropped.
    """
    evidence_refs_set = {e.ref for e in portfolio.evidence}

    text = raw.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return _midpoint(score_min, score_max), list(_SAFE_REASONING)

    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return _midpoint(score_min, score_max), list(_SAFE_REASONING)

    if not isinstance(data, dict):
        return _midpoint(score_min, score_max), list(_SAFE_REASONING)

    # Parse and clamp score.
    raw_score = data.get("score")
    if not isinstance(raw_score, (int, float)):
        score = _midpoint(score_min, score_max)
    else:
        score = max(score_min, min(score_max, int(raw_score)))

    # Parse and grounding-check reasoning bullets.
    raw_reasoning = data.get("reasoning")
    if not isinstance(raw_reasoning, list):
        return _midpoint(score_min, score_max), list(_SAFE_REASONING)

    checked: list[dict] = []
    for item in raw_reasoning:
        if not isinstance(item, dict):
            continue
        text_val = item.get("text", "")
        if not isinstance(text_val, str) or not text_val.strip():
            continue
        refs = item.get("evidence_refs", [])
        if not isinstance(refs, list):
            refs = []
        refs = [r for r in refs if isinstance(r, str)]
        # Grounding gate: a model-authored bullet must cite at least one real ref.
        # Drop it if its refs are empty OR any ref is not in the portfolio's
        # evidence set (an uncited bullet must never ship — IR-002).
        if refs and all(r in evidence_refs_set for r in refs):
            checked.append({"text": text_val.strip(), "evidence_refs": refs})

    if not checked:
        return score, list(_SAFE_REASONING)

    return score, checked


def grade(
    portfolio: Portfolio,
    profile_result: ProfileResult,
    grader_runner: GraderRunner,
    lang: str = "en",
) -> GradeResult:
    """Call grader_runner deterministically and return a bounded GradeResult.

    The grade is ALWAYS taken from profile_result (model cannot change it).
    The score is clamped to [score_min, score_max].
    Reasoning bullets whose refs are not in portfolio.evidence are dropped.
    Malformed grader responses yield midpoint score + safe reasoning (no crash).
    """
    prompt = _build_prompt(portfolio, profile_result, lang=lang)
    raw = grader_runner(prompt, temperature=0)
    score, reasoning = _parse_response(raw, portfolio, profile_result.score_min, profile_result.score_max)
    return GradeResult(
        score=score,
        grade=profile_result.grade,  # model cannot change the grade
        reasoning=reasoning,
    )
