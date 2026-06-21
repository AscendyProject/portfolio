"""Deterministic, stdlib-only Markdown renderer for a grounded Portfolio.

Turns a Portfolio (subject + evidence + already-grounded claims) into a
human-readable Markdown document where every rendered claim shows its grounding:
cited evidence refs, the evidence URL when present, and the claim's confidence.

No model, subprocess, or network call is made — stdlib and portfolio.model only.
"""

from __future__ import annotations

from collections.abc import Iterable

from portfolio.i18n import LANGS
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


def count_repos_from_refs(refs: Iterable[str]) -> int:
    """Count distinct repo identities from an iterable of ref strings.

    Rules (deterministic, no model):
    - <owner>/<repo>#<n>  → identity = <owner>/<repo>
    - <owner>/<repo>:<path> → identity = <owner>/<repo>
    - PR#<n> or bare path (no colon, no leading http) → unqualified bucket
    - http(s)://... → contributes nothing
    """
    qualified: set[str] = set()
    has_unqualified = False
    for ref in refs:
        if ref.startswith("http://") or ref.startswith("https://"):
            continue
        if "#" in ref and "/" in ref.split("#")[0]:
            qualified.add(ref.split("#")[0])
        elif ":" in ref and "/" in ref.split(":")[0] and not ref.startswith("PR"):
            qualified.add(ref.split(":")[0])
        else:
            has_unqualified = True
    return len(qualified) + (1 if has_unqualified else 0)


def stack_languages(evidence: Iterable) -> set[str]:
    """Return the set of distinct non-'other' language names from file evidence.

    Iterates over items with .kind and .ref attributes; only processes items
    where .kind == 'file'.
    """
    langs: set[str] = set()
    for ev in evidence:
        if ev.kind == "file":
            lang = language_for_ref(ev.ref)
            if lang != "other":
                langs.add(lang)
    return langs


def claim_group(claim, evidence_by_ref: dict) -> str:
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

    real_langs = {k: v for k, v in lang_counts.items() if k != "other"}
    if not real_langs:
        return "Other"

    best_count = max(real_langs.values())
    candidates = sorted(k for k, v in real_langs.items() if v == best_count)
    return candidates[0]


def _count_repos(evidence: list) -> int:
    return count_repos_from_refs(e.ref for e in evidence)


def _stack_summary(evidence: list) -> str:
    langs = stack_languages(evidence)
    if not langs:
        return "no stack detected"
    return ", ".join(sorted(langs))


def _render_claim_block(claim, evidence_by_ref: dict, *, show_refs: bool = False, lang: str = "en") -> list[str]:
    """Render the per-claim block: ### heading, confidence, evidence."""
    strings = LANGS[lang]
    lines: list[str] = []
    lines.append(f"### {_escape(claim.text)}")
    lines.append("")
    lines.append(f"- {strings['confidence']}: {claim.confidence:.2f}")
    if show_refs and claim.evidence_refs:
        lines.append(f"- {strings['evidence_section']}:")
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


def render_markdown(
    portfolio: Portfolio,
    *,
    synthesis: SynthesisResult | None = None,
    show_refs: bool = False,
    lang: str = "en",
) -> str:
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
    strings = LANGS[lang]
    evidence_by_ref = {e.ref: e for e in portfolio.evidence}

    lines: list[str] = []

    # Top-level heading — em dash kept as Unicode; ruff/ruff-format handle UTF-8.
    lines.append(f"# {strings['title_portfolio']} — {_escape(portfolio.subject)}")
    lines.append("")

    if not portfolio.claims:
        lines.append(strings["no_grounded_claims"])
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
        # Use the language-specific headline template; subject is pre-escaped
        # (curly braces are not in _ESCAPE_CHARS so the format is safe for GitHub handles)
        headline_tmpl = strings["fallback_headline"]
        lines.append("> " + headline_tmpl.format(subject=_escape(portfolio.subject), n_prs=n_prs, n_repos=n_repos))
    lines.append("")

    # --- Stats line ---
    lines.append(f"**{n_prs} {strings['stat_merged_prs']} · {n_repos} {strings['stat_repos']} · {stack}**")
    lines.append("")

    # --- Highlights (optional) ---
    if synthesis is not None and synthesis.highlights:
        lines.append(f"## {strings['section_highlights']}")
        lines.append("")
        for bullet in synthesis.highlights:
            escaped_text = _escape(bullet.text)
            if show_refs:
                # Pre-change behavior rendered the `(refs: …)` suffix unconditionally
                # (even for empty evidence_refs → `(refs: )`); --show-refs restores it
                # byte-for-byte. Default (show_refs=False) drops the suffix entirely.
                escaped_refs = ", ".join(_escape(r) for r in bullet.evidence_refs)
                lines.append(f"- {escaped_text} (refs: {escaped_refs})")
            else:
                lines.append(f"- {escaped_text}")
        lines.append("")

    # --- Grouped claim sections ---
    # Assign each claim to a group.
    groups: dict[str, list] = {}
    for claim in portfolio.claims:
        group = claim_group(claim, evidence_by_ref)
        groups.setdefault(group, []).append(claim)

    # Group ordering: descending claim count, then ascending name. 'Other' always last.
    other_claims = groups.pop("Other", [])
    sorted_groups = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    if other_claims:
        sorted_groups.append(("Other", other_claims))

    for group_name, claims in sorted_groups:
        # Translate the "Other" sentinel to the current language; tech names are language-neutral.
        display_name = strings["group_other"] if group_name == "Other" else group_name
        lines.append(f"## {display_name}")
        lines.append("")
        for claim in claims:
            lines.extend(_render_claim_block(claim, evidence_by_ref, show_refs=show_refs, lang=lang))

    return "\n".join(lines)
