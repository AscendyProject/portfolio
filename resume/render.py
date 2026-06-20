"""Deterministic, stdlib-only Markdown renderer for a ResumeDraft.

Turns a ResumeDraft (subject + selected scored claims) into a human-readable
Markdown resume where every rendered bullet shows its grounding evidence refs.

No model, subprocess, or network call is made — stdlib and resume.select only.
"""

from __future__ import annotations

from resume.select import ResumeDraft

# Reuse the same escape rules as portfolio.render to keep output identical.
from portfolio.render import _escape

_NO_BULLETS_NOTICE = "_no grounded resume bullets_"


def render_resume(draft: ResumeDraft, *, show_refs: bool = False) -> str:
    """Render a ResumeDraft to a Markdown string.

    For every selected ScoredClaim the output contains:
      - the claim text as a list bullet
      - the evidence refs from the claim (inline, after the claim text)

    When draft.selected is empty the document contains a deterministic
    "no grounded resume bullets" notice.
    """
    lines: list[str] = []

    lines.append(f"# Resume — {_escape(draft.subject)}")
    lines.append("")

    if not draft.selected:
        lines.append(_NO_BULLETS_NOTICE)
        lines.append("")
        return "\n".join(lines)

    for sc in draft.selected:
        if show_refs:
            refs_str = ", ".join(_escape(ref) for ref in sc.claim.evidence_refs)
            lines.append(f"- {_escape(sc.claim.text)} [{refs_str}]")
        else:
            lines.append(f"- {_escape(sc.claim.text)}")

    lines.append("")
    return "\n".join(lines)
