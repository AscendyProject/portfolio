"""Unit tests for resume.render.render_resume — both show_refs states.

No live model, gh, or network calls.  ResumeDraft is built directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.model import Claim  # noqa: E402
from resume.select import ResumeDraft, ScoredClaim  # noqa: E402
from resume.render import render_resume  # noqa: E402


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
