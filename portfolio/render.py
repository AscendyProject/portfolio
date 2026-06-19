"""Deterministic, stdlib-only Markdown renderer for a grounded Portfolio.

Turns a Portfolio (subject + evidence + already-grounded claims) into a
human-readable Markdown document where every rendered claim shows its grounding:
cited evidence refs, the evidence URL when present, and the claim's confidence.

No model, subprocess, or network call is made — stdlib and portfolio.model only.
"""

from __future__ import annotations

from portfolio.model import Portfolio
from portfolio.synthesis import SynthesisResult
from rating.profile import language_for_ref

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


def _count_repos(evidence: list) -> int:
    """Count distinct repo identities across all evidence refs.

    Rules (deterministic, no model):
    - <owner>/<repo>#<n>  → identity = <owner>/<repo>
    - <owner>/<repo>:<path> → identity = <owner>/<repo>
    - PR#<n> or bare path (no colon, no leading http) → unqualified bucket
    - http(s)://... → contributes nothing
    """
    qualified: set[str] = set()
    has_unqualified = False

    for ev in evidence:
        ref = ev.ref
        if ref.startswith("http://") or ref.startswith("https://"):
            continue
        if "#" in ref and "/" in ref.split("#")[0]:
            # <owner>/<repo>#<n>
            qualified.add(ref.split("#")[0])
        elif ":" in ref and "/" in ref.split(":")[0] and not ref.startswith("PR"):
            # <owner>/<repo>:<path>
            qualified.add(ref.split(":")[0])
        else:
            # bare path or PR#<n> — unqualified bucket
            has_unqualified = True

    return len(qualified) + (1 if has_unqualified else 0)


def _stack_summary(evidence: list) -> str:
    """Build the stack summary string from file evidence refs.

    Collects distinct language names (excluding 'other'), sorts alphabetically,
    and joins with ', '.  Returns 'no stack detected' when the list is empty.
    """
    langs: set[str] = set()
    for ev in evidence:
        if ev.kind == "file":
            lang = language_for_ref(ev.ref)
            if lang != "other":
                langs.add(lang)
    if not langs:
        return "no stack detected"
    return ", ".join(sorted(langs))


def _claim_group(claim, evidence_by_ref: dict) -> str:
    """Determine the ## <Group> section for a single claim.

    Uses the majority language among the claim's file evidence refs.
    Ties broken alphabetically (ascending, ASCII, case-sensitive).
    Returns 'Other' when there are no file refs or all map to 'other'.
    """
    lang_counts: dict[str, int] = {}
    for ref in claim.evidence_refs:
        ev = evidence_by_ref.get(ref)
        if ev is None or ev.kind != "file":
            continue
        lang = language_for_ref(ref)
        lang_counts[lang] = lang_counts.get(lang, 0) + 1

    if not lang_counts:
        return "Other"

    # Remove 'other' bucket — it folds into the 'Other' group
    real_langs = {k: v for k, v in lang_counts.items() if k != "other"}
    if not real_langs:
        return "Other"

    # Primary: highest count; secondary: ascending alphabetical (ASCII, case-sensitive).
    best_count = max(real_langs.values())
    candidates = sorted(k for k, v in real_langs.items() if v == best_count)
    return candidates[0]


def _render_claim_block(claim, evidence_by_ref: dict, *, show_refs: bool = False) -> list[str]:
    """Render the per-claim block: ### heading, confidence, evidence."""
    lines: list[str] = []
    lines.append(f"### {_escape(claim.text)}")
    lines.append("")
    lines.append(f"- Confidence: {claim.confidence:.2f}")
    if show_refs and claim.evidence_refs:
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
    return lines


def render_markdown(portfolio: Portfolio, *, synthesis: SynthesisResult | None = None, show_refs: bool = False) -> str:
    """Render a grounded Portfolio to a Markdown string.

    When synthesis is provided and has a grounded headline, the output is:
      1. # Portfolio — <subject>
      2. (blank)
      3. > <headline blockquote>
      4. (blank)
      5. **<N> merged PRs · <M> repos · <stack>**
      6. (blank)
      7. ## Highlights  (only if synthesis.highlights is non-empty)
      8. ## <Group> sections wrapping per-claim blocks

    When portfolio.claims is empty the document contains a clear
    "no grounded claims" notice and still includes the subject heading.
    The synthesis argument is ignored for empty portfolios.
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

    # --- Stats ---
    n_prs = sum(1 for e in portfolio.evidence if e.kind == "pr")
    n_repos = _count_repos(portfolio.evidence)
    stack = _stack_summary(portfolio.evidence)

    # --- Headline blockquote ---
    headline: str | None = synthesis.headline if synthesis is not None else None
    if headline is not None:
        lines.append(f"> {_escape(headline)}")
    else:
        lines.append(f"> Portfolio for {_escape(portfolio.subject)} — {n_prs} merged PRs across {n_repos} repos.")
    lines.append("")

    # --- Stats line ---
    lines.append(f"**{n_prs} merged PRs · {n_repos} repos · {stack}**")
    lines.append("")

    # --- Highlights (optional) ---
    if synthesis is not None and synthesis.highlights:
        lines.append("## Highlights")
        lines.append("")
        for bullet in synthesis.highlights:
            escaped_text = _escape(bullet.text)
            if show_refs and bullet.evidence_refs:
                escaped_refs = ", ".join(_escape(r) for r in bullet.evidence_refs)
                lines.append(f"- {escaped_text} (refs: {escaped_refs})")
            else:
                lines.append(f"- {escaped_text}")
        lines.append("")

    # --- Grouped claim sections ---
    # Assign each claim to a group.
    groups: dict[str, list] = {}
    for claim in portfolio.claims:
        group = _claim_group(claim, evidence_by_ref)
        groups.setdefault(group, []).append(claim)

    # Group ordering: descending claim count, then ascending name. 'Other' always last.
    other_claims = groups.pop("Other", [])
    sorted_groups = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    if other_claims:
        sorted_groups.append(("Other", other_claims))

    for group_name, claims in sorted_groups:
        lines.append(f"## {group_name}")
        lines.append("")
        for claim in claims:
            lines.extend(_render_claim_block(claim, evidence_by_ref, show_refs=show_refs))

    return "\n".join(lines)
