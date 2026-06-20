"""Unit tests for resume.render.render_resume — both show_refs states.

No live model, gh, or network calls.  ResumeDraft is built directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.model import Claim, Evidence, Portfolio  # noqa: E402
from resume.select import ResumeDraft, ScoredClaim, build_resume  # noqa: E402
from resume.render import render_resume  # noqa: E402
import portfolio.render as _portfolio_render  # noqa: E402
import resume.render as _resume_render  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_draft(
    subject: str = "alice",
    claim_text: str = "Built the feature",
    refs: list[str] | None = None,
) -> ResumeDraft:
    if refs is None:
        refs = ["PR#1"]
    claim = Claim(text=claim_text, evidence_refs=refs, confidence=0.9, grounded=True)
    scored = ScoredClaim(claim=claim, score=1)
    return ResumeDraft(subject=subject, selected=[scored])


# ---------------------------------------------------------------------------
# show_refs=False (default) — refs hidden
# ---------------------------------------------------------------------------


def test_render_resume_hides_refs_by_default():
    """By default (show_refs=False), no inline refs appear in the output."""
    draft = _make_draft(refs=["PR#1"])
    out = render_resume(draft)
    # claim text present
    assert "Built the feature" in out
    # ref NOT present
    assert "PR" not in out
    # no brackets
    assert "[" not in out


def test_render_resume_bullet_format_default():
    """Default render: bullet is '- <claim text>' with no trailing refs."""
    draft = _make_draft(claim_text="Shipped auth overhaul", refs=["PR#1"])
    out = render_resume(draft)
    bullets = [ln for ln in out.splitlines() if ln.startswith("- ")]
    assert len(bullets) == 1
    assert bullets[0] == "- Shipped auth overhaul"


# ---------------------------------------------------------------------------
# show_refs=True — refs shown
# ---------------------------------------------------------------------------


def test_render_resume_shows_refs_with_show_refs():
    """With show_refs=True, inline refs appear after the claim text."""
    draft = _make_draft(refs=["PR#1"])
    out = render_resume(draft, show_refs=True)
    assert "PR" in out
    assert "[" in out


def test_render_resume_bullet_format_with_show_refs():
    """With show_refs=True, bullet is '- <claim text> [<refs>]'."""
    draft = _make_draft(claim_text="Shipped auth overhaul", refs=["PR#1"])
    out = render_resume(draft, show_refs=True)
    bullets = [ln for ln in out.splitlines() if ln.startswith("- ")]
    assert len(bullets) == 1
    assert "Shipped auth overhaul" in bullets[0]
    assert "PR" in bullets[0]
    assert "[" in bullets[0]


def test_render_resume_multi_ref_format_with_show_refs():
    """Multiple refs are comma-separated inside brackets."""
    draft = _make_draft(refs=["PR#1", "PR#2"])
    out = render_resume(draft, show_refs=True)
    assert "PR" in out
    assert "," in out


# ---------------------------------------------------------------------------
# Shared structure: heading always present
# ---------------------------------------------------------------------------


def test_render_resume_heading_always_present():
    """# Resume heading is present regardless of show_refs."""
    draft = _make_draft()
    assert "# Resume" in render_resume(draft)
    assert "# Resume" in render_resume(draft, show_refs=True)


def test_render_resume_subject_in_heading():
    """Subject appears in the heading for both modes."""
    draft = _make_draft(subject="bob")
    assert "bob" in render_resume(draft)
    assert "bob" in render_resume(draft, show_refs=True)


def test_render_resume_empty_draft_notice():
    """Empty draft emits 'no grounded resume bullets' for both modes."""
    draft = ResumeDraft(subject="alice", selected=[])
    assert "no grounded resume bullets" in render_resume(draft)
    assert "no grounded resume bullets" in render_resume(draft, show_refs=True)


# ---------------------------------------------------------------------------
# New layout: summary stat line
# ---------------------------------------------------------------------------


def test_summary_stat_line_contains_all_three_numbers():
    """Done-when: summary stat line contains n_selected, n_repos, and m/t."""
    portfolio = Portfolio(
        subject="alice",
        evidence=[
            Evidence(kind="file", ref="src/main.py"),
            Evidence(kind="file", ref="cmd/server.go"),
            Evidence(kind="pr", ref="PR#1"),
        ],
        claims=[
            Claim(text="Python API", evidence_refs=["src/main.py", "PR#1"], confidence=0.9, grounded=True),
            Claim(text="Go microservice", evidence_refs=["cmd/server.go", "PR#1"], confidence=0.8, grounded=True),
        ],
    )
    draft = build_resume(portfolio, "python go api microservice", top_n=10)
    out = render_resume(draft)
    lines = out.splitlines()
    stat_line = lines[2]  # heading, blank, stat line

    n_selected = len(draft.selected)
    assert str(n_selected) in stat_line

    from portfolio.render import count_repos_from_refs

    n_repos = count_repos_from_refs(ref for sc in draft.selected for ref in sc.claim.evidence_refs)
    assert str(n_repos) in stat_line

    m = len(draft.jd_keywords_matched)
    t = draft.jd_keywords_total
    assert f"{m}/{t}" in stat_line


# ---------------------------------------------------------------------------
# New layout: ## Experience heading
# ---------------------------------------------------------------------------


def test_experience_heading_present():
    """Done-when: ## Experience heading is present after the stat line for a non-empty draft."""
    draft = _make_draft()
    out = render_resume(draft)
    assert "## Experience" in out
    lines = out.splitlines()
    stat_idx = 2
    exp_idx = next(i for i, ln in enumerate(lines) if ln == "## Experience")
    assert exp_idx > stat_idx


# ---------------------------------------------------------------------------
# New layout: within-group order
# ---------------------------------------------------------------------------


def test_within_group_order_matches_selected_order():
    """Done-when: within each group, bullets appear in the same order as draft.selected."""
    ev_py1 = Evidence(kind="file", ref="a.py")
    ev_py2 = Evidence(kind="file", ref="b.py")
    claim1 = Claim(text="First Python claim", evidence_refs=["a.py"], confidence=0.9, grounded=True)
    claim2 = Claim(text="Second Python claim", evidence_refs=["b.py"], confidence=0.7, grounded=True)
    sc1 = ScoredClaim(claim=claim1, score=2)
    sc2 = ScoredClaim(claim=claim2, score=1)
    evidence_by_ref = {"a.py": ev_py1, "b.py": ev_py2}
    draft = ResumeDraft(subject="alice", selected=[sc1, sc2], evidence_by_ref=evidence_by_ref)
    out = render_resume(draft)
    idx1 = out.index("First Python claim")
    idx2 = out.index("Second Python claim")
    assert idx1 < idx2


# ---------------------------------------------------------------------------
# New layout: ## Other placement and group ordering
# ---------------------------------------------------------------------------


def test_other_group_exists_when_no_file_refs():
    """Done-when: ## Other group is emitted for claims with no file evidence."""
    draft = _make_draft(refs=["PR#1"])  # PR ref → no file evidence → Other group
    out = render_resume(draft)
    assert "## Other" in out


def test_group_ordering_count_desc_alpha_tiebreak_other_last():
    """Done-when: named groups in descending count, alpha tiebreak; ## Other last."""
    ev_py = Evidence(kind="file", ref="x.py")
    ev_ts = Evidence(kind="file", ref="y.ts")
    ev_pr = Evidence(kind="pr", ref="PR#1")
    py1 = Claim(text="Python A", evidence_refs=["x.py"], confidence=0.9, grounded=True)
    py2 = Claim(text="Python B", evidence_refs=["x.py"], confidence=0.8, grounded=True)
    ts1 = Claim(text="TypeScript C", evidence_refs=["y.ts"], confidence=0.7, grounded=True)
    ts2 = Claim(text="TypeScript D", evidence_refs=["y.ts"], confidence=0.6, grounded=True)
    other1 = Claim(text="PR only E", evidence_refs=["PR#1"], confidence=0.5, grounded=True)
    evidence_by_ref = {"x.py": ev_py, "y.ts": ev_ts, "PR#1": ev_pr}
    draft = ResumeDraft(
        subject="alice",
        selected=[
            ScoredClaim(claim=py1, score=5),
            ScoredClaim(claim=py2, score=4),
            ScoredClaim(claim=ts1, score=3),
            ScoredClaim(claim=ts2, score=2),
            ScoredClaim(claim=other1, score=1),
        ],
        evidence_by_ref=evidence_by_ref,
    )
    out = render_resume(draft)
    lines = out.splitlines()
    # Collect group headings (exclude fixed sections)
    skip = {"## Experience", "## Skills", "## Contact", "## Education"}
    group_lines = [ln for ln in lines if ln.startswith("## ") and ln not in skip]
    group_names = [ln[3:] for ln in group_lines]

    assert "Python" in group_names
    assert "TypeScript" in group_names
    assert "Other" in group_names
    assert group_names[-1] == "Other"
    py_pos = group_names.index("Python")
    ts_pos = group_names.index("TypeScript")
    # Python and TypeScript tie at 2 claims each → alphabetical: Python before TypeScript
    assert py_pos < ts_pos


# ---------------------------------------------------------------------------
# New layout: ## Skills section
# ---------------------------------------------------------------------------


def test_skills_section_populated_with_file_evidence():
    """Done-when: ## Skills lists languages from selected file evidence (sorted, comma-joined)."""
    ev_py = Evidence(kind="file", ref="main.py")
    ev_ts = Evidence(kind="file", ref="app.ts")
    ev_pr = Evidence(kind="pr", ref="PR#1")
    claim = Claim(
        text="Full stack feature",
        evidence_refs=["main.py", "app.ts", "PR#1"],
        confidence=0.9,
        grounded=True,
    )
    evidence_by_ref = {"main.py": ev_py, "app.ts": ev_ts, "PR#1": ev_pr}
    draft = ResumeDraft(
        subject="alice",
        selected=[ScoredClaim(claim=claim, score=1)],
        evidence_by_ref=evidence_by_ref,
    )
    out = render_resume(draft)
    lines = out.splitlines()
    skills_idx = next(i for i, ln in enumerate(lines) if ln == "## Skills")
    skills_body = lines[skills_idx + 2]
    assert "Python" in skills_body
    assert "TypeScript" in skills_body
    assert "_no stack detected_" not in skills_body


def test_skills_section_no_stack_when_only_pr_refs():
    """Done-when: ## Skills body is '_no stack detected_' when selected claims cite only PR refs."""
    draft = _make_draft(refs=["PR#1"])  # PR ref only, no file evidence
    out = render_resume(draft)
    assert "_no stack detected_" in out


# ---------------------------------------------------------------------------
# New layout: placeholder sections
# ---------------------------------------------------------------------------


def test_contact_placeholder_exact_text():
    """Done-when: ## Contact is followed by exactly '_Add your contact details._'."""
    draft = _make_draft()
    out = render_resume(draft)
    lines = out.splitlines()
    contact_idx = next(i for i, ln in enumerate(lines) if ln == "## Contact")
    assert lines[contact_idx + 1] == ""
    assert lines[contact_idx + 2] == "_Add your contact details._"


def test_education_placeholder_exact_text():
    """Done-when: ## Education is followed by exactly '_Add your education._'."""
    draft = _make_draft()
    out = render_resume(draft)
    lines = out.splitlines()
    edu_idx = next(i for i, ln in enumerate(lines) if ln == "## Education")
    assert lines[edu_idx + 1] == ""
    assert lines[edu_idx + 2] == "_Add your education._"


def test_placeholders_contain_no_personal_data():
    """Done-when: placeholder bodies contain no tokens from subject, claim text, or refs."""
    portfolio = Portfolio(
        subject="alice_unique_xyz",
        evidence=[Evidence(kind="pr", ref="PR#9999")],
        claims=[
            Claim(
                text="Implemented uniquefeature_abc",
                evidence_refs=["PR#9999"],
                confidence=0.9,
                grounded=True,
            )
        ],
    )
    draft = build_resume(portfolio, "uniquefeature", top_n=5)
    out = render_resume(draft)
    lines = out.splitlines()
    contact_idx = next(i for i, ln in enumerate(lines) if ln == "## Contact")
    edu_idx = next(i for i, ln in enumerate(lines) if ln == "## Education")
    contact_body = lines[contact_idx + 2]
    edu_body = lines[edu_idx + 2]
    for body in (contact_body, edu_body):
        assert "alice" not in body
        assert "uniquefeature" not in body
        assert "PR" not in body


# ---------------------------------------------------------------------------
# New layout: show_refs gating
# ---------------------------------------------------------------------------


def test_show_refs_false_zero_brackets_anywhere():
    """Done-when: show_refs=False produces zero '[' and ']' characters in the entire document."""
    portfolio = Portfolio(
        subject="alice",
        evidence=[
            Evidence(kind="file", ref="main.py"),
            Evidence(kind="pr", ref="PR#1"),
        ],
        claims=[
            Claim(
                text="Built feature",
                evidence_refs=["main.py", "PR#1"],
                confidence=0.9,
                grounded=True,
            )
        ],
    )
    draft = build_resume(portfolio, "built feature", top_n=5)
    out = render_resume(draft, show_refs=False)
    assert "[" not in out
    assert "]" not in out


def test_show_refs_true_adds_inline_refs_to_bullets():
    """Done-when: show_refs=True emits '- <claim text> [ref1, ref2]' format on per-claim bullets."""
    portfolio = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="PR#1"), Evidence(kind="pr", ref="PR#2")],
        claims=[
            Claim(
                text="Built stuff",
                evidence_refs=["PR#1", "PR#2"],
                confidence=0.9,
                grounded=True,
            )
        ],
    )
    draft = build_resume(portfolio, "built", top_n=5)
    out = render_resume(draft, show_refs=True)
    bullets = [ln for ln in out.splitlines() if ln.startswith("- ")]
    assert len(bullets) == 1
    assert "[" in bullets[0]
    assert "Built stuff" in bullets[0]


# ---------------------------------------------------------------------------
# New layout: empty-draft exact string contract
# ---------------------------------------------------------------------------


def test_empty_draft_exact_string_contract():
    """Done-when: empty draft emits exactly the committed line sequence."""
    draft = ResumeDraft(subject="alice", selected=[])
    expected = "\n".join(
        [
            "# Resume — alice",
            "",
            "_no grounded resume bullets_",
            "",
            "## Contact",
            "",
            "_Add your contact details._",
            "",
            "## Education",
            "",
            "_Add your education._",
            "",
        ]
    )
    assert render_resume(draft) == expected


def test_empty_draft_no_experience_or_skills_or_summary():
    """Done-when: empty draft output contains no ## Summary, ## Experience, or ## Skills."""
    draft = ResumeDraft(subject="alice", selected=[])
    out = render_resume(draft)
    assert "## Summary" not in out
    assert "## Experience" not in out
    assert "## Skills" not in out


# ---------------------------------------------------------------------------
# New layout: determinism
# ---------------------------------------------------------------------------


def test_determinism_non_empty_draft():
    """Done-when: two successive render_resume calls on non-empty draft return byte-identical strings."""
    portfolio = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="file", ref="main.py"), Evidence(kind="pr", ref="PR#1")],
        claims=[
            Claim(
                text="Built feature",
                evidence_refs=["main.py", "PR#1"],
                confidence=0.9,
                grounded=True,
            )
        ],
    )
    draft = build_resume(portfolio, "built feature", top_n=5)
    assert render_resume(draft) == render_resume(draft)
    assert render_resume(draft, show_refs=True) == render_resume(draft, show_refs=True)


def test_determinism_empty_draft():
    """Done-when: two successive render_resume calls on empty draft return byte-identical strings."""
    draft = ResumeDraft(subject="alice", selected=[])
    assert render_resume(draft) == render_resume(draft)


# ---------------------------------------------------------------------------
# New layout: shared helper identity
# ---------------------------------------------------------------------------


def test_shared_helpers_are_same_objects():
    """Done-when: claim_group, count_repos_from_refs, stack_languages from resume.render
    are the same objects as those from portfolio.render (no forking)."""
    assert _resume_render.claim_group is _portfolio_render.claim_group
    assert _resume_render.count_repos_from_refs is _portfolio_render.count_repos_from_refs
    assert _resume_render.stack_languages is _portfolio_render.stack_languages
