"""Synthesis layer — a model writes a grounded headline + highlight bullets from
the already-grounded claims in a Portfolio.

Every model-authored sentence must cite ONLY refs already cited by a grounded
claim; anything that references an unclaimed ref is dropped before returning.
No subprocess, open, or network call is made — stdlib only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .model import Portfolio
from .narrative import Runner


@dataclass
class HighlightBullet:
    text: str
    evidence_refs: list[str]


@dataclass
class SynthesisResult:
    headline: str | None
    headline_refs: list[str] = field(default_factory=list)
    highlights: list[HighlightBullet] = field(default_factory=list)


def synthesize(portfolio: Portfolio, runner: Runner) -> SynthesisResult:
    """Run the injected runner once over the portfolio's grounded claims and return
    a grounding-re-checked SynthesisResult.

    The allowed-refs set is the union of every ref cited by a grounded claim —
    STRICTER than the full evidence set; synthesis can only re-state what was
    already grounded upstream.
    """
    # Allowed refs = union of grounded-claim refs (NOT the full evidence set).
    allowed_refs = {ref for claim in portfolio.claims for ref in claim.evidence_refs}

    # Build prompt enumerating ONLY the grounded claims and their refs.
    lines = []
    for claim in portfolio.claims:
        lines.append(f"- {claim.text} (refs: {', '.join(claim.evidence_refs)})")
    claims_text = "\n".join(lines) if lines else "(none)"

    prompt = (
        "You are writing a portfolio synthesis for a developer from their grounded claims.\n\n"
        f"GROUNDED CLAIMS (cite ONLY these refs, using exact ref strings):\n{claims_text}\n\n"
        "You MUST NOT cite any ref not listed above. You MUST NOT reference any evidence "
        "ref not cited by a grounded claim above.\n\n"
        "Output a strict JSON object:\n"
        '{"headline": "<1-3 line summary>", "headline_refs": ["<ref>", ...], '
        '"highlights": [{"text": "<bullet text>", "evidence_refs": ["<ref>", ...]}, ...]}\n\n'
        "No prose, no code fences, JSON object only."
    )

    raw = runner(prompt)

    # Parse defensively — same strategy as parse_claims: slice outermost {...}.
    text = raw.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return SynthesisResult(headline=None, headline_refs=[], highlights=[])
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return SynthesisResult(headline=None, headline_refs=[], highlights=[])

    if not isinstance(data, dict):
        return SynthesisResult(headline=None, headline_refs=[], highlights=[])

    # --- Headline grounding re-check ---
    headline_raw = data.get("headline", "")
    headline_refs_raw = data.get("headline_refs", [])

    headline: str | None = None
    headline_refs: list[str] = []

    if (
        isinstance(headline_raw, str)
        and headline_raw.strip()
        and isinstance(headline_refs_raw, list)
        and len(headline_refs_raw) > 0
        and all(isinstance(r, str) for r in headline_refs_raw)
        and all(r in allowed_refs for r in headline_refs_raw)
    ):
        # Deterministic line enforcement (PR-012): model output is untrusted.
        non_empty_lines = [ln for ln in headline_raw.split("\n") if ln.strip()]
        if len(non_empty_lines) > 3:
            non_empty_lines = non_empty_lines[:3]
        truncated_lines = [ln[:200] if len(ln) > 200 else ln for ln in non_empty_lines]
        headline = "\n".join(truncated_lines)
        headline_refs = [r for r in headline_refs_raw if isinstance(r, str)]

    # --- Highlight grounding re-check ---
    raw_highlights = data.get("highlights", [])
    highlights: list[HighlightBullet] = []
    if isinstance(raw_highlights, list):
        for item in raw_highlights:
            if not isinstance(item, dict):
                continue
            text_val = item.get("text", "")
            refs_val = item.get("evidence_refs", [])
            if not isinstance(text_val, str) or not text_val.strip():
                continue
            if not isinstance(refs_val, list) or len(refs_val) == 0:
                continue
            if not all(isinstance(r, str) for r in refs_val):
                continue
            if not all(r in allowed_refs for r in refs_val):
                continue
            highlights.append(HighlightBullet(text=text_val, evidence_refs=list(refs_val)))

    # Truncate to first 5 in model order (no re-sorting).
    highlights = highlights[:5]

    return SynthesisResult(headline=headline, headline_refs=headline_refs, highlights=highlights)
