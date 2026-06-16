"""Deterministic, stdlib-only Markdown renderer for a LetterDraft.

Turns a LetterDraft into a human-readable recommendation letter in Markdown.
No model, subprocess, network, or file I/O is performed here.
"""

from __future__ import annotations

from portfolio.render import _escape
from reference_check.letter import LetterDraft

_INSUFFICIENT_NOTICE = "_insufficient grounded evidence — letter not generated_"


def render_letter(draft: LetterDraft) -> str:
    """Render a LetterDraft to a Markdown string.

    Output structure:
      # Recommendation Letter — {subject}

      Dear Hiring Manager,

      {paragraph text}
      *[{escaped refs}]*

      ...

      Sincerely,

    When draft.paragraphs is empty (zero grounded evidence or fully hallucinated
    output), emits the deterministic insufficient-evidence notice instead of
    letter body — never fabricates content.
    """
    lines: list[str] = []

    lines.append(f"# Recommendation Letter — {_escape(draft.subject)}")
    lines.append("")

    if not draft.paragraphs:
        lines.append(_INSUFFICIENT_NOTICE)
        lines.append("")
        return "\n".join(lines)

    lines.append("Dear Hiring Manager,")
    lines.append("")

    for para in draft.paragraphs:
        lines.append(_escape(para.text))
        if para.evidence_refs:
            refs_str = ", ".join(_escape(ref) for ref in para.evidence_refs)
            lines.append(f"*[{refs_str}]*")
        lines.append("")

    lines.append("Sincerely,")
    lines.append("")

    return "\n".join(lines)
