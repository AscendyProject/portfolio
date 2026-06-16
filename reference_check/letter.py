"""Letter composition layer — builds a grounded recommendation letter.

The model receives ONLY the grounded portfolio claims and may cite refs from
that grounded set only. Each drafted paragraph is re-grounded: a paragraph that
cites any ref not in the Portfolio's evidence set is dropped (fail-closed).

No subprocess, urllib, socket, or file I/O performed here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from portfolio.model import Portfolio
from portfolio.narrative import Runner


@dataclass
class LetterParagraph:
    text: str
    evidence_refs: list[str] = field(default_factory=list)
    grounded: bool | None = None  # set by ground_paragraphs; None = unchecked


@dataclass
class LetterDraft:
    subject: str
    paragraphs: list[LetterParagraph] = field(default_factory=list)
    rejected_paragraphs: list[LetterParagraph] = field(default_factory=list)


def build_letter_prompt(portfolio: Portfolio) -> str:
    """Build the recommendation-letter prompt from grounded portfolio claims.

    Gives the model ONLY the grounded claims and the exact ref strings it may
    cite. Pure / no I/O.
    """
    claim_lines: list[str] = []
    allowed_refs: list[str] = []
    for claim in portfolio.claims:
        refs_str = ", ".join(claim.evidence_refs)
        claim_lines.append(f"- {claim.text}  [refs: {refs_str}]")
        allowed_refs.extend(claim.evidence_refs)

    unique_refs = sorted(set(allowed_refs))
    claims_block = "\n".join(claim_lines) if claim_lines else "(none)"
    refs_block = "\n".join(f"- {r}" for r in unique_refs) if unique_refs else "(none)"

    return (
        f"You are writing a professional recommendation letter about a developer named "
        f"{portfolio.subject!r} based ONLY on grounded evidence from their real work. "
        f"Every paragraph MUST cite one or more refs from the ALLOWED REFS list below, "
        f"using the exact ref string. Do NOT invent refs, projects, metrics, employers, "
        f"titles, or dates. Do NOT assert anything not supported by the grounded claims.\n\n"
        f"GROUNDED CLAIMS:\n{claims_block}\n\n"
        f"ALLOWED REFS (cite by exact ref string):\n{refs_block}\n\n"
        f"Write 2-4 body paragraphs for a recommendation letter. Each paragraph MUST cite "
        f"at least one ref from the ALLOWED REFS list. Output STRICT JSON only — a list of "
        f"objects with keys: text (string, the paragraph body), evidence_refs (list of exact "
        f"ref strings from ALLOWED REFS). No prose, no code fences, JSON array only."
    )


def parse_paragraphs(model_text: str) -> list[LetterParagraph]:
    """Tolerantly extract a JSON paragraph list from a model response.

    Handles code fences / surrounding prose by slicing the outermost [...].
    Malformed output yields [] rather than raising — the grounding gate is the
    real guard; we never fabricate paragraphs from a bad parse.
    """
    text = model_text.strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        raw = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    paragraphs: list[LetterParagraph] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text_val = str(item.get("text", "")).strip()
        refs = item.get("evidence_refs")
        refs = [r for r in refs if isinstance(r, str)] if isinstance(refs, list) else []
        if text_val:
            paragraphs.append(LetterParagraph(text=text_val, evidence_refs=refs))
    return paragraphs


def ground_paragraphs(
    paragraphs: list[LetterParagraph],
    portfolio: Portfolio,
) -> tuple[list[LetterParagraph], list[LetterParagraph]]:
    """Re-enforce grounding on letter paragraphs.

    A paragraph passes iff it cites at least one ref AND every ref it cites
    exists in portfolio.evidence. One bad ref poisons the paragraph.
    Returns (grounded, rejected).
    """
    real_refs = {e.ref for e in portfolio.evidence}
    grounded: list[LetterParagraph] = []
    rejected: list[LetterParagraph] = []
    for para in paragraphs:
        if not para.evidence_refs or any(r not in real_refs for r in para.evidence_refs):
            para.grounded = False
            rejected.append(para)
        else:
            para.grounded = True
            grounded.append(para)
    return grounded, rejected


def build_letter(portfolio: Portfolio, runner: Runner) -> LetterDraft:
    """Build a grounded recommendation letter from a grounded Portfolio.

    If portfolio.claims is empty (zero grounded evidence), returns a LetterDraft
    with no paragraphs — the renderer will emit an insufficient-evidence notice.
    No I/O performed here.
    """
    if not portfolio.claims:
        return LetterDraft(subject=portfolio.subject)

    prompt = build_letter_prompt(portfolio)
    raw_output = runner(prompt)
    paragraphs = parse_paragraphs(raw_output)
    grounded, rejected = ground_paragraphs(paragraphs, portfolio)
    return LetterDraft(
        subject=portfolio.subject,
        paragraphs=grounded,
        rejected_paragraphs=rejected,
    )
