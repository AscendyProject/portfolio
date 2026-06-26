"""Tests for the deterministic Markdown renderer.

All tests build Portfolio / Evidence / Claim instances directly — no live gh,
no live model runner.  The renderer must be a pure, stdlib-only function.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.model import Claim, Evidence, Portfolio  # noqa: E402 — after sys.path setup per test-conventions
from portfolio.render import render_markdown  # noqa: E402 — after sys.path setup per test-conventions
from portfolio.synthesis import HighlightBullet, SynthesisResult  # noqa: E402 — after sys.path setup per test-conventions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _portfolio_with_claim(
    subject: str = "alice",
    claim_text: str = "Implemented token rotation",
    refs: list[str] | None = None,
    confidence: float = 0.9,
    evidence: list[Evidence] | None = None,
) -> Portfolio:
    refs = refs or ["PR#128"]
    evidence = evidence or [Evidence(kind="pr", ref="PR#128", url="https://github.com/a/b/pull/128")]
    return Portfolio(
        subject=subject,
        evidence=evidence,
        claims=[Claim(text=claim_text, evidence_refs=refs, confidence=confidence)],
    )


# ---------------------------------------------------------------------------
# Subject heading
# ---------------------------------------------------------------------------


def test_subject_heading_present():
    """The returned string starts with a top-level Markdown heading containing the subject."""
    out = render_markdown(Portfolio(subject="alice", evidence=[], claims=[]))
    assert out.startswith("# Portfolio")
    assert "alice" in out


# ---------------------------------------------------------------------------
# Claim rendering
# ---------------------------------------------------------------------------


def test_claim_text_rendered():
    """Claim text appears in the output."""
    p = _portfolio_with_claim(claim_text="Shipped auth overhaul")
    out = render_markdown(p)
    assert "Shipped auth overhaul" in out


def test_claim_confidence_rendered():
    """Claim confidence appears in the output as a fixed-decimal string."""
    p = _portfolio_with_claim(confidence=0.85)
    out = render_markdown(p)
    assert "0.85" in out


def test_claim_evidence_ref_hidden_by_default():
    """By default (show_refs=False), evidence refs do NOT appear in the output."""
    ev = Evidence(kind="pr", ref="PR#128", url="https://example.com/128")
    p = Portfolio(
        subject="alice",
        evidence=[ev],
        claims=[Claim(text="Did something", evidence_refs=["PR#128"], confidence=0.9)],
    )
    out = render_markdown(p)
    # Ref number must not appear (stats line shows "1 merged PRs" but not "128")
    assert "128" not in out


def test_claim_evidence_ref_rendered_with_show_refs():
    """With show_refs=True, each cited evidence ref appears in the output."""
    ev = Evidence(kind="pr", ref="PR#128", url="https://example.com/128")
    p = Portfolio(
        subject="alice",
        evidence=[ev],
        claims=[Claim(text="Did something", evidence_refs=["PR#128"], confidence=0.9)],
    )
    out = render_markdown(p, show_refs=True)
    # The ref may be escaped (e.g. "PR\#128") — check the unescaped digits are present
    assert "PR" in out and "128" in out


def test_evidence_url_hidden_by_default():
    """By default (show_refs=False), the Evidence url is NOT emitted in the output."""
    ev = Evidence(kind="pr", ref="PR#128", url="https://github.com/alice/repo/pull/128")
    p = Portfolio(
        subject="alice",
        evidence=[ev],
        claims=[Claim(text="Token rotation", evidence_refs=["PR#128"], confidence=0.9)],
    )
    out = render_markdown(p)
    assert "https://github.com/alice/repo/pull/128" not in out


def test_evidence_url_rendered_when_present_with_show_refs():
    """With show_refs=True, a non-empty Evidence url appears in the output."""
    ev = Evidence(kind="pr", ref="PR#128", url="https://github.com/alice/repo/pull/128")
    p = Portfolio(
        subject="alice",
        evidence=[ev],
        claims=[Claim(text="Token rotation", evidence_refs=["PR#128"], confidence=0.9)],
    )
    out = render_markdown(p, show_refs=True)
    assert "https://github.com/alice/repo/pull/128" in out


def test_no_fabricated_url_when_evidence_url_empty():
    """No URL is emitted for a ref whose Evidence.url is empty (even with show_refs=True)."""
    ev = Evidence(kind="pr", ref="PR#128", url="")
    p = Portfolio(
        subject="alice",
        evidence=[ev],
        claims=[Claim(text="Token rotation", evidence_refs=["PR#128"], confidence=0.9)],
    )
    out = render_markdown(p, show_refs=True)
    assert "http" not in out


def test_no_fabricated_url_for_ref_absent_from_evidence():
    """No URL is emitted when the cited ref has no matching Evidence entry at all (even with show_refs=True)."""
    p = Portfolio(
        subject="alice",
        evidence=[],  # empty evidence set
        claims=[Claim(text="Something", evidence_refs=["PR#999"], confidence=0.7)],
    )
    out = render_markdown(p, show_refs=True)
    assert "http" not in out


def test_multiple_claims_all_rendered():
    """All claims in portfolio.claims are present in the output."""
    ev1 = Evidence(kind="pr", ref="PR#1", url="https://example.com/1")
    ev2 = Evidence(kind="pr", ref="PR#2", url="")
    p = Portfolio(
        subject="bob",
        evidence=[ev1, ev2],
        claims=[
            Claim(text="First achievement", evidence_refs=["PR#1"], confidence=0.8),
            Claim(text="Second achievement", evidence_refs=["PR#2"], confidence=0.6),
        ],
    )
    out = render_markdown(p)
    assert "First achievement" in out
    assert "Second achievement" in out
    assert "0.80" in out
    assert "0.60" in out


def test_evidence_detail_hidden_by_default():
    """By default (show_refs=False), evidence detail is NOT emitted in the output."""
    ev = Evidence(kind="pr", ref="PR#1", url="", detail="fixed auth bug in login flow")
    p = Portfolio(
        subject="alice",
        evidence=[ev],
        claims=[Claim(text="Something", evidence_refs=["PR#1"], confidence=0.7)],
    )
    out = render_markdown(p)
    assert "fixed auth bug in login flow" not in out


def test_evidence_detail_rendered_when_present_with_show_refs():
    """With show_refs=True, evidence detail text appears in the output when non-empty."""
    ev = Evidence(kind="pr", ref="PR#1", url="", detail="fixed auth bug in login flow")
    p = Portfolio(
        subject="alice",
        evidence=[ev],
        claims=[Claim(text="Something", evidence_refs=["PR#1"], confidence=0.7)],
    )
    out = render_markdown(p, show_refs=True)
    assert "fixed auth bug in login flow" in out


# ---------------------------------------------------------------------------
# Empty claims
# ---------------------------------------------------------------------------


def test_empty_claims_contains_no_grounded_notice():
    """When portfolio.claims is empty the output contains 'no grounded claims'."""
    p = Portfolio(subject="alice", evidence=[], claims=[])
    out = render_markdown(p)
    assert "no grounded claims" in out


def test_empty_claims_still_has_subject_heading():
    """Subject heading is present even when there are no claims."""
    p = Portfolio(subject="alice", evidence=[], claims=[])
    out = render_markdown(p)
    assert "# Portfolio" in out
    assert "alice" in out


# ---------------------------------------------------------------------------
# Markdown escaping
# ---------------------------------------------------------------------------

_HOSTILE_CHARS = "`[]\\*_#<>"


def test_escape_hostile_subject():
    """Hostile characters in subject do not introduce new Markdown structures."""
    hostile = "# evil `subject` [link](http://x.com) *bold* _em_ <tag>"
    p = Portfolio(subject=hostile, evidence=[], claims=[])
    out = render_markdown(p)
    lines = out.splitlines()
    # The document must have exactly one top-level heading line (the first line).
    h1_lines = [ln for ln in lines if ln.startswith("# ")]
    assert len(h1_lines) == 1, f"Expected 1 top-level heading, got: {h1_lines}"
    # The '#' in the hostile subject must be escaped to '\#' — verify that.
    heading = h1_lines[0]
    assert "\\#" in heading  # the '#' in the subject is backslash-escaped


def test_escape_hostile_claim_text():
    """Hostile characters in claim text do not create additional headings."""
    hostile_text = "# Injected heading\n## Another\n*bold* _em_"
    ev = Evidence(kind="pr", ref="PR#1", url="")
    p = Portfolio(
        subject="alice",
        evidence=[ev],
        claims=[Claim(text=hostile_text, evidence_refs=["PR#1"], confidence=0.5)],
    )
    out = render_markdown(p)
    lines = out.splitlines()
    # Only two structural headings: "# Portfolio ..." and "## <escaped claim>"
    h1_lines = [ln for ln in lines if ln.startswith("# ") and not ln.startswith("## ")]
    assert len(h1_lines) == 1
    # The embedded newline in the claim text must not produce a bare "## Another" line.
    assert "## Another" not in lines


def test_escape_backslash_in_subject():
    """Backslashes in interpolated text are escaped (no double-processing)."""
    p = Portfolio(subject="a\\b\\c", evidence=[], claims=[])
    out = render_markdown(p)
    # The heading must contain escaped backslashes, not literal ones that could
    # be misread as escape sequences by a Markdown renderer.
    assert "a\\\\b\\\\c" in out  # each \ becomes \\


def test_escape_hostile_evidence_ref():
    """Hostile characters in evidence ref are escaped in the output."""
    hostile_ref = "[evil](http://attack.example.com)"
    ev = Evidence(kind="pr", ref=hostile_ref, url="")
    p = Portfolio(
        subject="alice",
        evidence=[ev],
        claims=[Claim(text="Something", evidence_refs=[hostile_ref], confidence=0.7)],
    )
    out = render_markdown(p)
    # The hostile ref must not appear unescaped as a Markdown link.
    assert "[evil](http://attack.example.com)" not in out


def test_escape_hostile_evidence_url():
    """Hostile characters in evidence url are escaped in the output (with show_refs=True)."""
    hostile_url = "https://example.com/path[evil]?x=1"
    ev = Evidence(kind="pr", ref="PR#1", url=hostile_url)
    p = Portfolio(
        subject="alice",
        evidence=[ev],
        claims=[Claim(text="Something", evidence_refs=["PR#1"], confidence=0.7)],
    )
    out = render_markdown(p, show_refs=True)
    # The hostile [evil] brackets must not appear unescaped.
    assert "[evil]" not in out
    assert "\\[evil\\]" in out


def test_escape_hostile_evidence_url_hidden_by_default():
    """By default (show_refs=False), hostile url is not emitted at all."""
    hostile_url = "https://example.com/path[evil]?x=1"
    ev = Evidence(kind="pr", ref="PR#1", url=hostile_url)
    p = Portfolio(
        subject="alice",
        evidence=[ev],
        claims=[Claim(text="Something", evidence_refs=["PR#1"], confidence=0.7)],
    )
    out = render_markdown(p)
    assert "[evil]" not in out
    assert "https://example.com" not in out


def test_escape_hostile_evidence_detail():
    """Hostile characters in evidence detail are escaped in the output."""
    hostile_detail = "# Injected heading [link](http://x.com)"
    ev = Evidence(kind="pr", ref="PR#1", url="", detail=hostile_detail)
    p = Portfolio(
        subject="alice",
        evidence=[ev],
        claims=[Claim(text="Something", evidence_refs=["PR#1"], confidence=0.7)],
    )
    out = render_markdown(p)
    # The hostile detail must not create a new heading.
    lines = out.splitlines()
    h1_lines = [ln for ln in lines if ln.startswith("# ")]
    assert len(h1_lines) == 1
    # The hostile link must be escaped.
    assert "[link](http://x.com)" not in out


def test_escape_newline_in_subject():
    """Embedded newlines in subject are replaced so no extra line is created."""
    p = Portfolio(subject="line1\nline2", evidence=[], claims=[])
    out = render_markdown(p)
    lines = out.splitlines()
    h1_lines = [ln for ln in lines if ln.startswith("# ")]
    assert len(h1_lines) == 1


# ---------------------------------------------------------------------------
# Pure function contract
# ---------------------------------------------------------------------------


def test_idempotent():
    """Calling render_markdown twice on the same Portfolio returns identical strings."""
    p = _portfolio_with_claim()
    assert render_markdown(p) == render_markdown(p)


def test_no_mutation_of_portfolio():
    """render_markdown must not mutate the input Portfolio, Claim, or Evidence objects."""
    ev = Evidence(kind="pr", ref="PR#128", url="https://example.com/128")
    claim = Claim(text="Did something", evidence_refs=["PR#128"], confidence=0.9)
    p = Portfolio(subject="alice", evidence=[ev], claims=[claim])

    subject_before = p.subject
    claims_before = list(p.claims)
    evidence_before = list(p.evidence)
    claim_text_before = claim.text
    claim_refs_before = list(claim.evidence_refs)

    render_markdown(p)

    assert p.subject == subject_before
    assert p.claims == claims_before
    assert p.evidence == evidence_before
    assert claim.text == claim_text_before
    assert claim.evidence_refs == claim_refs_before


# ---------------------------------------------------------------------------
# New layout: render order tests
# ---------------------------------------------------------------------------


def _make_full_portfolio() -> Portfolio:
    """Portfolio with one PR + one file evidence, one claim citing both."""
    return Portfolio(
        subject="alice",
        evidence=[
            Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1"),
            Evidence(kind="file", ref="app/main.py"),
        ],
        claims=[Claim(text="Built main feature", evidence_refs=["PR#1", "app/main.py"], confidence=0.9)],
    )


def _make_synthesis(headline: str = "Great developer", refs: list[str] | None = None) -> SynthesisResult:
    return SynthesisResult(
        headline=headline,
        headline_refs=refs if refs is not None else ["PR#1"],
        highlights=[HighlightBullet(text="Key highlight", evidence_refs=["PR#1"])],
    )


def test_render_order_title_then_headline_then_stats_then_groups():
    """Non-empty portfolio with synthesis emits: title, blank, headline, blank, stats, blank, group.

    Outcome: 'render test that asserts presence, order, and absence of each block
    via line-index assertions on the output.'
    """
    p = _make_full_portfolio()
    syn = _make_synthesis()
    out = render_markdown(p, synthesis=syn)
    lines = out.splitlines()

    title_idx = next(i for i, ln in enumerate(lines) if ln.startswith("# Portfolio"))
    headline_idx = next(i for i, ln in enumerate(lines) if ln.startswith("> "))
    stats_idx = next(i for i, ln in enumerate(lines) if ln.startswith("**"))
    highlights_idx = next(i for i, ln in enumerate(lines) if ln == "## Highlights")
    group_idx = next(i for i, ln in enumerate(lines) if ln.startswith("## ") and ln != "## Highlights")

    assert title_idx < headline_idx < stats_idx < highlights_idx < group_idx


def test_render_order_without_synthesis_uses_fallback_headline():
    """Without synthesis, the fallback headline blockquote still precedes stats.

    Outcome: 'deterministic fallback headline test.'
    """
    p = _make_full_portfolio()
    out = render_markdown(p, synthesis=None)
    lines = out.splitlines()

    title_idx = next(i for i, ln in enumerate(lines) if ln.startswith("# Portfolio"))
    headline_idx = next(i for i, ln in enumerate(lines) if ln.startswith("> "))
    stats_idx = next(i for i, ln in enumerate(lines) if ln.startswith("**"))

    assert title_idx < headline_idx < stats_idx


# ---------------------------------------------------------------------------
# New layout: highlight bullet format
# ---------------------------------------------------------------------------


def test_highlight_bullet_refs_hidden_by_default():
    """By default (show_refs=False), highlight bullets do NOT include '(refs: …)'.

    Outcome: 'the literal substring (refs: appears on every rendered highlight line.'
    """
    p = _make_full_portfolio()
    syn = SynthesisResult(
        headline="Summary",
        headline_refs=["PR#1"],
        highlights=[HighlightBullet(text="Did something", evidence_refs=["PR#1"])],
    )
    out = render_markdown(p, synthesis=syn)
    assert "(refs: " not in out
    assert "- Did something" in out


def test_highlight_bullet_single_ref_format_with_show_refs():
    """With show_refs=True, highlight with one ref renders as '- <text> (refs: <ref>)'.

    Outcome: 'the literal substring (refs: appears on every rendered highlight line.'
    """
    p = _make_full_portfolio()
    syn = SynthesisResult(
        headline="Summary",
        headline_refs=["PR#1"],
        highlights=[HighlightBullet(text="Did something", evidence_refs=["PR#1"])],
    )
    out = render_markdown(p, synthesis=syn, show_refs=True)
    assert "- Did something (refs: PR" in out
    assert "(refs: " in out


def test_highlight_bullet_multi_ref_format():
    """With show_refs=True, highlight with two refs renders with comma-space separator.

    Outcome: 'one citing two refs ... comma-space separator.'
    """
    p = Portfolio(
        subject="alice",
        evidence=[
            Evidence(kind="pr", ref="PR#1"),
            Evidence(kind="file", ref="app/main.py"),
        ],
        claims=[Claim(text="Built thing", evidence_refs=["PR#1", "app/main.py"], confidence=0.9)],
    )
    syn = SynthesisResult(
        headline="Summary",
        headline_refs=["PR#1"],
        highlights=[HighlightBullet(text="Multi ref bullet", evidence_refs=["PR#1", "app/main.py"])],
    )
    out = render_markdown(p, synthesis=syn, show_refs=True)
    # Both refs must appear in the bullet line separated by ", "
    bullet_lines = [ln for ln in out.splitlines() if "(refs: " in ln]
    assert len(bullet_lines) == 1
    assert "PR" in bullet_lines[0] and "app" in bullet_lines[0]
    assert ", " in bullet_lines[0]


def test_highlights_section_omitted_when_no_highlights():
    """## Highlights section is absent when synthesis.highlights is empty.

    Outcome: 'otherwise the ## Highlights section is omitted entirely.'
    """
    p = _make_full_portfolio()
    syn = SynthesisResult(headline="Summary", headline_refs=["PR#1"], highlights=[])
    out = render_markdown(p, synthesis=syn)
    assert "## Highlights" not in out


# ---------------------------------------------------------------------------
# New layout: deterministic fallback headline
# ---------------------------------------------------------------------------


def test_fallback_headline_synthesis_none():
    """synthesis=None → deterministic fallback '> Portfolio for <subject> — N merged PRs across M repos.'

    Outcome: 'render_markdown(portfolio, synthesis=None) and checks the literal blockquote line.'
    """
    p = Portfolio(
        subject="alice",
        evidence=[
            Evidence(kind="pr", ref="PR#1"),
            Evidence(kind="pr", ref="PR#2"),
        ],
        claims=[Claim(text="Did stuff", evidence_refs=["PR#1"], confidence=0.9)],
    )
    out = render_markdown(p, synthesis=None)
    lines = out.splitlines()
    blockquote_lines = [ln for ln in lines if ln.startswith("> ")]
    assert len(blockquote_lines) == 1
    bq = blockquote_lines[0]
    assert "Portfolio for alice" in bq
    assert "2 merged PRs across" in bq
    assert "repos." in bq


def test_fallback_headline_synthesis_headline_none():
    """synthesis.headline is None → same deterministic fallback.

    Outcome: 'When the renderer receives synthesis=None, or synthesis.headline is None ...'
    """
    p = _make_full_portfolio()
    syn = SynthesisResult(headline=None, headline_refs=[], highlights=[])
    out = render_markdown(p, synthesis=syn)
    lines = out.splitlines()
    blockquote_lines = [ln for ln in lines if ln.startswith("> ")]
    assert len(blockquote_lines) == 1
    assert "Portfolio for alice" in blockquote_lines[0]


# ---------------------------------------------------------------------------
# New layout: stats line — PR count
# ---------------------------------------------------------------------------


def test_stats_pr_count():
    """<N> in stats line = count of Evidence(kind='pr').

    Outcome: 'asserted by a render test that constructs a Portfolio with a mix of
    pr / file / article evidence and checks the rendered integer.'
    """
    p = Portfolio(
        subject="alice",
        evidence=[
            Evidence(kind="pr", ref="PR#1"),
            Evidence(kind="pr", ref="PR#2"),
            Evidence(kind="pr", ref="PR#3"),
            Evidence(kind="file", ref="app/main.py"),
            Evidence(kind="article", ref="https://blog.example.com/post"),
        ],
        claims=[Claim(text="Did stuff", evidence_refs=["PR#1"], confidence=0.9)],
    )
    out = render_markdown(p)
    stats_line = next(ln for ln in out.splitlines() if ln.startswith("**"))
    assert "3 merged PRs" in stats_line


# ---------------------------------------------------------------------------
# New layout: stats line — repo count
# ---------------------------------------------------------------------------


def test_stats_repos_all_unqualified():
    """All bare PR#<n> refs → M=1 (single unqualified bucket).

    Outcome: '(all-unqualified) ... checks the integer.'
    """
    p = Portfolio(
        subject="alice",
        evidence=[
            Evidence(kind="pr", ref="PR#1"),
            Evidence(kind="pr", ref="PR#2"),
        ],
        claims=[Claim(text="Did stuff", evidence_refs=["PR#1"], confidence=0.9)],
    )
    out = render_markdown(p)
    stats_line = next(ln for ln in out.splitlines() if ln.startswith("**"))
    assert "· 1 repos ·" in stats_line


def test_stats_repos_qualified_across_two_repos():
    """owner/repo#n and owner/repo:path refs → M=2 distinct repos.

    Outcome: '(all-qualified across two repos) ... checks the integer.'
    """
    p = Portfolio(
        subject="alice",
        evidence=[
            Evidence(kind="pr", ref="org/repoA#1"),
            Evidence(kind="pr", ref="org/repoA#2"),
            Evidence(kind="file", ref="org/repoB:src/main.py"),
        ],
        claims=[Claim(text="Did stuff", evidence_refs=["org/repoA#1"], confidence=0.9)],
    )
    out = render_markdown(p)
    stats_line = next(ln for ln in out.splitlines() if ln.startswith("**"))
    assert "· 2 repos ·" in stats_line


def test_stats_repos_mixed():
    """Mix of qualified and unqualified refs → M = distinct qualified + 1 unqualified.

    Outcome: '(mixed) ... checks the integer.'
    """
    p = Portfolio(
        subject="alice",
        evidence=[
            Evidence(kind="pr", ref="org/repoA#1"),
            Evidence(kind="pr", ref="PR#2"),  # unqualified
        ],
        claims=[Claim(text="Did stuff", evidence_refs=["org/repoA#1"], confidence=0.9)],
    )
    out = render_markdown(p)
    stats_line = next(ln for ln in out.splitlines() if ln.startswith("**"))
    assert "· 2 repos ·" in stats_line


# ---------------------------------------------------------------------------
# New layout: stats line — stack summary
# ---------------------------------------------------------------------------


def test_stack_summary_py_and_ts():
    """File evidence with .py and .ts → 'Python, TypeScript'.

    Outcome: 'a portfolio with .py + .ts files.'
    """
    p = Portfolio(
        subject="alice",
        evidence=[
            Evidence(kind="file", ref="app/main.py"),
            Evidence(kind="file", ref="web/app.ts"),
        ],
        claims=[Claim(text="Did stuff", evidence_refs=["app/main.py"], confidence=0.9)],
    )
    out = render_markdown(p)
    stats_line = next(ln for ln in out.splitlines() if ln.startswith("**"))
    assert "Python, TypeScript" in stats_line


def test_stack_summary_unknown_extension():
    """File evidence with .unknownext only → 'no stack detected'.

    Outcome: 'a portfolio with .unknownext only.'
    """
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="file", ref="data.unknownext")],
        claims=[Claim(text="Did stuff", evidence_refs=["data.unknownext"], confidence=0.9)],
    )
    out = render_markdown(p)
    stats_line = next(ln for ln in out.splitlines() if ln.startswith("**"))
    assert "no stack detected" in stats_line


def test_stack_summary_no_file_evidence():
    """No file evidence at all → 'no stack detected'.

    Outcome: 'a portfolio with no file evidence at all.'
    """
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="PR#1")],
        claims=[Claim(text="Did stuff", evidence_refs=["PR#1"], confidence=0.9)],
    )
    out = render_markdown(p)
    stats_line = next(ln for ln in out.splitlines() if ln.startswith("**"))
    assert "no stack detected" in stats_line


# ---------------------------------------------------------------------------
# New layout: grouping rule
# ---------------------------------------------------------------------------


def test_grouping_majority_language():
    """Claim with two .py and three .ts refs groups under TypeScript (majority).

    Outcome: 'one citing two .py and three .ts (group = TypeScript by majority).'
    """
    p = Portfolio(
        subject="alice",
        evidence=[
            Evidence(kind="file", ref="a.py"),
            Evidence(kind="file", ref="b.py"),
            Evidence(kind="file", ref="c.ts"),
            Evidence(kind="file", ref="d.ts"),
            Evidence(kind="file", ref="e.ts"),
        ],
        claims=[
            Claim(
                text="TypeScript majority claim",
                evidence_refs=["a.py", "b.py", "c.ts", "d.ts", "e.ts"],
                confidence=0.9,
            )
        ],
    )
    out = render_markdown(p)
    lines = out.splitlines()
    group_lines = [ln for ln in lines if ln.startswith("## ")]
    assert any("TypeScript" in ln for ln in group_lines)


def test_grouping_alphabetical_tie_break():
    """Claim with one .py and one .ts refs groups under Python (tie → alphabetical).

    Outcome: 'one citing one .py and one .ts (group = Python by alphabetical tie-break).'
    """
    p = Portfolio(
        subject="alice",
        evidence=[
            Evidence(kind="file", ref="a.py"),
            Evidence(kind="file", ref="b.ts"),
        ],
        claims=[
            Claim(text="Tied claim", evidence_refs=["a.py", "b.ts"], confidence=0.9),
        ],
    )
    out = render_markdown(p)
    lines = out.splitlines()
    group_lines = [ln for ln in lines if ln.startswith("## ")]
    assert any("Python" in ln for ln in group_lines)


def test_grouping_no_file_refs_is_other():
    """Claim with no file refs → Other group.

    Outcome: 'one citing no file refs (group = Other).'
    """
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="PR#1")],
        claims=[Claim(text="PR only claim", evidence_refs=["PR#1"], confidence=0.9)],
    )
    out = render_markdown(p)
    assert "## Other" in out


# ---------------------------------------------------------------------------
# New layout: group ordering
# ---------------------------------------------------------------------------


def test_group_ordering_other_always_last():
    """Python=2, TypeScript=2, Other=3 → order is Python, TypeScript, Other.

    Outcome: 'test that constructs three groups with counts Python=2, TypeScript=2,
    Other=3 and checks the rendered order is ## Python, ## TypeScript, ## Other.'
    """
    p = Portfolio(
        subject="alice",
        evidence=[
            Evidence(kind="file", ref="a.py"),
            Evidence(kind="file", ref="b.py"),
            Evidence(kind="file", ref="c.ts"),
            Evidence(kind="file", ref="d.ts"),
            Evidence(kind="pr", ref="PR#1"),
            Evidence(kind="pr", ref="PR#2"),
            Evidence(kind="pr", ref="PR#3"),
        ],
        claims=[
            Claim(text="Python claim 1", evidence_refs=["a.py"], confidence=0.9),
            Claim(text="Python claim 2", evidence_refs=["b.py"], confidence=0.9),
            Claim(text="TypeScript claim 1", evidence_refs=["c.ts"], confidence=0.9),
            Claim(text="TypeScript claim 2", evidence_refs=["d.ts"], confidence=0.9),
            Claim(text="Other claim 1", evidence_refs=["PR#1"], confidence=0.9),
            Claim(text="Other claim 2", evidence_refs=["PR#2"], confidence=0.9),
            Claim(text="Other claim 3", evidence_refs=["PR#3"], confidence=0.9),
        ],
    )
    out = render_markdown(p)
    lines = out.splitlines()
    group_lines = [(i, ln) for i, ln in enumerate(lines) if ln.startswith("## ") and ln != "## Highlights"]
    group_names = [ln for _, ln in group_lines]
    group_indices = [i for i, _ in group_lines]

    assert "## Python" in group_names
    assert "## TypeScript" in group_names
    assert "## Other" in group_names

    py_idx = group_indices[group_names.index("## Python")]
    ts_idx = group_indices[group_names.index("## TypeScript")]
    other_idx = group_indices[group_names.index("## Other")]

    assert py_idx < other_idx
    assert ts_idx < other_idx


# ---------------------------------------------------------------------------
# New layout: determinism
# ---------------------------------------------------------------------------


def test_determinism_same_portfolio_renders_identically():
    """Rendering the same Portfolio + SynthesisResult twice yields byte-identical strings.

    Outcome: 'determinism test.'
    """
    p = _make_full_portfolio()
    syn = _make_synthesis()
    assert render_markdown(p, synthesis=syn) == render_markdown(p, synthesis=syn)


# ---------------------------------------------------------------------------
# New layout: empty portfolio short-circuit
# ---------------------------------------------------------------------------


def test_empty_portfolio_no_headline_or_stats():
    """Empty portfolio: only title + 'no grounded claims'; no headline, stats, or groups.

    Outcome: 'no headline blockquote, no stats line, no highlights, no group headings.'
    """
    p = Portfolio(subject="alice", evidence=[], claims=[])
    out = render_markdown(p, synthesis=_make_synthesis())
    assert "no grounded claims" in out
    assert "> " not in out
    assert "**" not in out
    assert "## " not in out


# ---------------------------------------------------------------------------
# New layout: per-claim detail preserved under new layout
# ---------------------------------------------------------------------------


def test_per_claim_detail_preserved_with_url():
    """With show_refs=True, claim block emits ref, url, and detail under the grouped layout.

    Outcome: 'render test that re-uses today's per-claim assertions on the new grouped layout.'
    """
    ev = Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="Fixed the bug")
    p = Portfolio(
        subject="alice",
        evidence=[ev],
        claims=[Claim(text="Fixed bug in auth", evidence_refs=["PR#1"], confidence=0.85)],
    )
    out = render_markdown(p, show_refs=True)
    assert "Fixed bug in auth" in out
    assert "0.85" in out
    assert "PR" in out and "1" in out
    assert "https://github.com/o/r/pull/1" in out
    assert "Fixed the bug" in out
    assert "---" in out


def test_per_claim_ref_and_url_hidden_by_default():
    """By default (show_refs=False), claim block does NOT emit the Evidence block (ref/url/detail)."""
    ev = Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="Fixed the bug")
    p = Portfolio(
        subject="alice",
        evidence=[ev],
        claims=[Claim(text="Fixed bug in auth", evidence_refs=["PR#1"], confidence=0.85)],
    )
    out = render_markdown(p)
    # claim text and confidence still present
    assert "Fixed bug in auth" in out
    assert "0.85" in out
    # Evidence block absent
    assert "https://github.com/o/r/pull/1" not in out
    assert "Fixed the bug" not in out
    assert "Evidence:" not in out


def test_highlight_empty_refs_byte_identical_under_show_refs():
    """IR-002: a synthesis highlight with EMPTY evidence_refs renders the
    `(refs: )` suffix under show_refs=True (pre-change byte-identity — the old
    renderer emitted the suffix unconditionally), and no suffix by default."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="PR#1")],
        claims=[Claim(text="c", evidence_refs=["PR#1"], confidence=0.9, grounded=True)],
    )
    synth = SynthesisResult(
        headline=None,
        headline_refs=[],
        highlights=[HighlightBullet(text="did a thing", evidence_refs=[])],
    )
    out_show = render_markdown(p, synthesis=synth, show_refs=True)
    assert "- did a thing (refs: )" in out_show  # empty-refs suffix preserved

    out_hide = render_markdown(p, synthesis=synth, show_refs=False)
    assert "- did a thing" in out_hide
    assert "(refs:" not in out_hide  # suffix dropped by default


# ---------------------------------------------------------------------------
# Public-helper extraction regression
# ---------------------------------------------------------------------------


def test_render_markdown_regression_multi_group_behavior_preserving():
    """Regression: render_markdown output is byte-identical after public-helper extraction.

    Done-when: 'render_markdown(portfolio, ...) returns byte-identical output before
    and after the public-helper extraction.'

    Pins the complete rendered string so any behaviour change in claim_group,
    count_repos_from_refs, or stack_languages is immediately caught.

    Discriminating assertion: also verifies that the three public helpers introduced
    by task-019 exist in portfolio.render and are callable. The pre-task-019 module
    only had private underscore-prefixed versions (_claim_group, _count_repos,
    _stack_summary), so this assertion fails against pre-change code.
    """
    import portfolio.render as _pr

    # Discriminating: public helpers must exist as callables in portfolio.render.
    assert callable(getattr(_pr, "claim_group", None)), "portfolio.render.claim_group must be a public callable"
    assert callable(
        getattr(_pr, "count_repos_from_refs", None)
    ), "portfolio.render.count_repos_from_refs must be a public callable"
    assert callable(getattr(_pr, "stack_languages", None)), "portfolio.render.stack_languages must be a public callable"

    p = Portfolio(
        subject="carol",
        evidence=[
            Evidence(kind="pr", ref="PR#1"),
            Evidence(kind="file", ref="lib/auth.py"),
        ],
        claims=[
            Claim(text="Python auth module", evidence_refs=["lib/auth.py"], confidence=0.9),
            Claim(text="PR review", evidence_refs=["PR#1"], confidence=0.7),
        ],
    )
    out = render_markdown(p)
    # Exact byte-for-byte pin — any extraction-induced behaviour change will fail here.
    _EXPECTED = (
        "# Portfolio — carol\n"
        "\n"
        "> Portfolio for carol — 1 merged PRs across 1 repos.\n"
        "\n"
        "**1 merged PRs · 1 repos · Python**\n"
        "\n"
        "## Python\n"
        "\n"
        "### Python auth module\n"
        "\n"
        "- Confidence: 0.90\n"
        "\n"
        "---\n"
        "\n"
        "## Other\n"
        "\n"
        "### PR review\n"
        "\n"
        "- Confidence: 0.70\n"
        "\n"
        "---\n"
    )
    assert out == _EXPECTED
