"""Bounded agent grader.

The grade AND the score are both deterministic, computed by
rating.profile.profile() (`grade` and the continuous `score`). The model is
called (temperature=0) ONLY to write the qualitative reasoning: this function
grounding-checks those bullets (dropping any whose evidence_refs ⊄
portfolio.evidence refs) and handles malformed responses defensively (safe
reasoning, no crash, no fabricated refs). The model may change neither the
grade nor the score — removing the free, clustering score-pick.
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
        f"Your job: write concise reasoning bullets explaining this assessment. The grade and "
        f"score are fixed by deterministic metrics — you do NOT choose them. Each bullet MUST "
        f"cite at least one ref from ALLOWED EVIDENCE REFS. "
        f"You MUST NOT claim a percentile, comparison to a population, or external baseline.\n\n"
        f"Output STRICT JSON only:\n"
        f'{{"reasoning": [{{"text": "<bullet>", "evidence_refs": ["<ref>", ...]}}]}}\n'
        f"No prose, no code fences. JSON only.\n\n"
        f"Write all prose in {language_name(lang)}."
    )


_SAFE_REASONING = [{"text": "Assessment based on grounded evidence.", "evidence_refs": []}]


def _parse_reasoning(raw: str, portfolio: Portfolio) -> list[dict]:
    """Parse and grounding-check the grader's reasoning bullets.

    Returns grounding-checked reasoning; a malformed response (non-JSON, non-dict,
    wrong-typed or empty-after-grounding reasoning) yields the safe reasoning. The
    grader's response no longer carries a score — the score is deterministic.
    Bullets whose evidence_refs ⊄ portfolio.evidence refs (or that cite nothing)
    are dropped (IR-002)."""
    evidence_refs_set = {e.ref for e in portfolio.evidence}

    text = raw.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return list(_SAFE_REASONING)

    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return list(_SAFE_REASONING)

    if not isinstance(data, dict):
        return list(_SAFE_REASONING)

    raw_reasoning = data.get("reasoning")
    if not isinstance(raw_reasoning, list):
        return list(_SAFE_REASONING)

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

    return checked or list(_SAFE_REASONING)


def grade(
    portfolio: Portfolio,
    profile_result: ProfileResult,
    grader_runner: GraderRunner,
    lang: str = "en",
) -> GradeResult:
    """Call grader_runner deterministically and return a bounded GradeResult.

    Both the grade AND the score are taken from profile_result — the model
    cannot change either. The grader_runner is consulted only for the qualitative
    reasoning, which is grounding-checked; a malformed response yields safe
    reasoning (no crash, no fabricated refs).
    """
    prompt = _build_prompt(portfolio, profile_result, lang=lang)
    raw = grader_runner(prompt, temperature=0)
    reasoning = _parse_reasoning(raw, portfolio)
    return GradeResult(
        score=profile_result.score,  # deterministic; model cannot change it
        grade=profile_result.grade,  # deterministic; model cannot change it
        reasoning=reasoning,
    )
