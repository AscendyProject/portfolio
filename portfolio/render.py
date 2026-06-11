"""Deterministic, stdlib-only Markdown renderer for a grounded Portfolio.

Turns a Portfolio (subject + evidence + already-grounded claims) into a
human-readable Markdown document where every rendered claim shows its grounding:
cited evidence refs, the evidence URL when present, and the claim's confidence.

No model, subprocess, or network call is made — stdlib and portfolio.model only.
"""

from __future__ import annotations

from portfolio.model import Portfolio

# Characters that carry structural meaning in Markdown and must be escaped when
# interpolated into headings, list items, or body text.  Backslash must come first
# so it is not double-escaped when other characters are processed.
_ESCAPE_CHARS = frozenset("`[]\\*_#<>")


def _escape(text: str) -> str:
    """Backslash-escape Markdown-significant characters; replace newlines with spaces."""
    result: list[str] = []
    for ch in text:
        if ch == "\n":
            result.append(" ")
        elif ch in _ESCAPE_CHARS:
            result.append("\\" + ch)
        else:
            result.append(ch)
    return "".join(result)


def render_markdown(portfolio: Portfolio) -> str:
    """Render a grounded Portfolio to a Markdown string.

    For every claim in portfolio.claims the output contains:
      - the claim text (as a heading)
      - each cited evidence ref from claim.evidence_refs
      - the corresponding Evidence.url when the looked-up Evidence has a
        non-empty url (no URL is fabricated for absent or empty-url Evidence)
      - the Evidence.detail when non-empty
      - the claim's confidence value

    When portfolio.claims is empty the document contains a clear
    "no grounded claims" notice and still includes the subject heading.
    """
    evidence_by_ref = {e.ref: e for e in portfolio.evidence}

    lines: list[str] = []

    # Top-level heading — em dash kept as Unicode; ruff/ruff-format handle UTF-8.
    lines.append(f"# Portfolio — {_escape(portfolio.subject)}")
    lines.append("")

    if not portfolio.claims:
        lines.append("_no grounded claims_")
        lines.append("")
        return "\n".join(lines)

    for claim in portfolio.claims:
        lines.append(f"## {_escape(claim.text)}")
        lines.append("")
        lines.append(f"- Confidence: {claim.confidence:.2f}")
        if claim.evidence_refs:
            lines.append("- Evidence:")
            for ref in claim.evidence_refs:
                ev = evidence_by_ref.get(ref)
                escaped_ref = _escape(ref)
                if ev is not None and ev.url:
                    if ev.detail:
                        lines.append(f"  - {escaped_ref}: {_escape(ev.url)} — {_escape(ev.detail)}")
                    else:
                        lines.append(f"  - {escaped_ref}: {_escape(ev.url)}")
                elif ev is not None and ev.detail:
                    lines.append(f"  - {escaped_ref} — {_escape(ev.detail)}")
                else:
                    lines.append(f"  - {escaped_ref}")
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)
