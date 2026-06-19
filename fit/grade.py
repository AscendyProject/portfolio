"""Feature-local grader seam and bounded grader for the /fit command.

Defines GraderRunner — a Callable with signature
    grader_runner(prompt: str, *, temperature: float = 0) -> str

This type lives ONLY here; the shared portfolio.narrative.Runner = Callable[[str], str]
contract is NOT modified.

The bounded_grade function calls the grader_runner exactly once with temperature=0
(passed as a keyword argument), parses the structured response defensively, clamps
the score into the locked band, and re-grounding-checks reasoning bullets against
the portfolio evidence.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field

from portfolio.model import Portfolio
from portfolio.narrative import run_claude

# ── Feature-local GraderRunner type alias ────────────────────────────────────
# Signature: grader_runner(prompt: str, *, temperature: float = 0) -> str
GraderRunner = Callable[..., str]


def default_grader_runner(prompt: str, *, temperature: float = 0) -> str:
    """Default grader runner wrapping portfolio.narrative.run_claude.

    NOTE: temperature=0 is best-effort at the seam's contract surface.
    The underlying `claude` CLI subprocess (run_claude) exposes no --temperature
    flag, so the temperature kwarg is accepted here but cannot be propagated to
    the model call. The reproducibility guarantee is NOT this model call — it is
    the deterministic grade + locked score band computed in fit/score.py with no
    model involvement. The within-band integer score may vary slightly run-to-run;
    that variance is bounded by the band and is acceptable.
    """
    # temperature kwarg accepted at the seam but not forwarded (see docstring)
    return run_claude(prompt)


@dataclass
class GradeResult:
    """The bounded-grader output: clamped score + re-grounded reasoning bullets."""

    score: int
    reasoning: list[dict] = field(default_factory=list)  # [{"text": ..., "evidence_refs": [...]}]


def _build_grader_prompt(portfolio: Portfolio, grade: str, band: tuple[int, int]) -> str:
    """Build a fixed, deterministic grader prompt.

    The prompt contains no clock value, no env value, no random value — so the
    same (portfolio, grade, band) inputs always produce byte-identical prompt text.
    """
    min_score, max_score = band
    evidence_lines = "\n".join(f"- {e.ref}  [{e.kind}]  {e.detail}".rstrip() for e in portfolio.evidence)
    claims_lines = "\n".join(f"- {c.text}  (refs: {', '.join(c.evidence_refs)})" for c in portfolio.claims)
    return (
        f"You are a grader assessing how well a developer's grounded portfolio matches a job description.\n"
        f"The overall grade has been locked to: {grade}\n"
        f"Your task: pick an integer score in the range [{min_score}, {max_score}] (inclusive) "
        f"for this grade band, and provide grounded reasoning bullets.\n\n"
        f"PORTFOLIO EVIDENCE (cite only these refs):\n{evidence_lines if evidence_lines else '(none)'}\n\n"
        f"GROUNDED CLAIMS:\n{claims_lines if claims_lines else '(none)'}\n\n"
        f"Output STRICT JSON only — an object with keys:\n"
        f'  "score": integer in [{min_score}, {max_score}],\n'
        f'  "reasoning": list of objects with keys "text" (string) and '
        f'"evidence_refs" (list of ref strings from PORTFOLIO EVIDENCE above).\n'
        f"No prose, no code fences, JSON object only."
    )


def bounded_grade(
    portfolio: Portfolio,
    grade: str,
    band: tuple[int, int],
    grader_runner: GraderRunner,
) -> GradeResult:
    """Call the grader_runner exactly once with a fixed prompt; clamp the returned
    score into the locked band; re-grounding-check reasoning bullets.

    - grader_runner is called with temperature=0 as a keyword argument.
    - Malformed JSON / missing / non-integer score → midpoint score, empty reasoning.
    - A reasoning bullet whose evidence_refs ⊄ portfolio.evidence is dropped silently.
    - The grade is never mutated by this function.
    """
    min_score, max_score = band
    midpoint = (min_score + max_score) // 2
    real_refs = {e.ref for e in portfolio.evidence}

    prompt = _build_grader_prompt(portfolio, grade, band)
    # temperature=0 is always passed by keyword (seam contract)
    raw = grader_runner(prompt, temperature=0)

    # Parse defensively — malformed output → midpoint, empty reasoning
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return GradeResult(score=midpoint, reasoning=[])
        raw_score = parsed.get("score")
        if not isinstance(raw_score, int):
            return GradeResult(score=midpoint, reasoning=[])
    except (json.JSONDecodeError, ValueError):
        return GradeResult(score=midpoint, reasoning=[])

    # Clamp score to [min, max]
    clamped = max(min_score, min(max_score, raw_score))

    # Re-grounding-check reasoning bullets
    raw_reasoning = parsed.get("reasoning", [])
    clean_reasoning: list[dict] = []
    if isinstance(raw_reasoning, list):
        for bullet in raw_reasoning:
            if not isinstance(bullet, dict):
                continue
            refs = bullet.get("evidence_refs", [])
            if not isinstance(refs, list):
                refs = []
            # Drop the bullet if any cited ref is not in portfolio evidence
            if refs and set(refs) <= real_refs:
                clean_reasoning.append({"text": str(bullet.get("text", "")), "evidence_refs": refs})

    return GradeResult(score=clamped, reasoning=clean_reasoning)
