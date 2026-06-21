"""Deterministic, stdlib-only Markdown renderer for a LetterDraft.

Turns a LetterDraft into a human-readable recommendation letter in Markdown.
No model, subprocess, network, or file I/O is performed here.
"""

from __future__ import annotations

from portfolio.i18n import LANGS
from portfolio.render import _escape
from reference_check.letter import LetterDraft


def render_letter(draft: LetterDraft, *, show_refs: bool = False, lang: str = "en") -> str:
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
    strings = LANGS[lang]
    lines: list[str] = []

    lines.append(f"# {strings['title_letter']} — {_escape(draft.subject)}")
    lines.append("")

    if not draft.paragraphs:
        lines.append(strings["insufficient_evidence"])
        lines.append("")
        return "\n".join(lines)

    lines.append(strings["letter_greeting"])
    lines.append("")

    for para in draft.paragraphs:
        lines.append(_escape(para.text))
        if show_refs and para.evidence_refs:
            refs_str = ", ".join(_escape(ref) for ref in para.evidence_refs)
            lines.append(f"*[{refs_str}]*")
        lines.append("")

    lines.append(strings["letter_closing"])
    lines.append("")

    return "\n".join(lines)
