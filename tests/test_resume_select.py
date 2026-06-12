"""Tests for resume.select — one test per Done-when item (outcome.md §Done-when).

All fixtures build Portfolio / Claim / Evidence in-process; no live services,
no network, no subprocess invocation.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.model import Claim, Evidence, Portfolio  # noqa: E402 — after sys.path setup per test-conventions
from resume.select import (  # noqa: E402 — after sys.path setup per test-conventions
    STOPWORDS,
    ResumeDraft,
    ScoredClaim,
    build_resume,
    enforce_grounding,
    jd_keywords,
    select_claims,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _portfolio(claims: list[Claim] | None = None, evidence: list[Evidence] | None = None) -> Portfolio:
    return Portfolio(subject="alice", evidence=evidence or [], claims=claims or [])


def _evidence(ref: str) -> Evidence:
    return Evidence(kind="pr", ref=ref)


def _claim(text: str, refs: list[str] | None = None) -> Claim:
    return Claim(text=text, evidence_refs=refs or [])


# ── jd_keywords: Done-when "jd_keywords tokenization" ───────────────────────


def test_jd_keywords_lowercases():
    """jd_keywords: lowercases input before tokenizing."""
    result = jd_keywords("Python Go KUBERNETES")
    assert "python" in result
    assert "go" in result
    assert "kubernetes" in result


def test_jd_keywords_splits_on_non_alphanumerics():
    """jd_keywords: splits on non-alphanumerics (commas, dots, colons, hyphens)."""
    result = jd_keywords("aws,gcp.azure:kubernetes-docker")
    assert result == {"aws", "gcp", "azure", "kubernetes", "docker"}


def test_jd_keywords_removes_stopwords():
    """jd_keywords: removes the pinned module-level STOPWORDS constant."""
    stopword_input = " ".join(sorted(STOPWORDS))
    assert jd_keywords(stopword_input) == set()


def test_jd_keywords_and_is_stopword():
    """jd_keywords: 'and' is in STOPWORDS and is removed from tokens."""
    result = jd_keywords("Python AND Go")
    assert "and" not in result
    assert "python" in result
    assert "go" in result


def test_jd_keywords_dedup():
    """jd_keywords: returns a set (deduplication of repeated tokens)."""
    result = jd_keywords("python python python")
    assert result == {"python"}


def test_jd_keywords_empty_input():
    """jd_keywords: empty/whitespace input returns an empty set."""
    assert jd_keywords("") == set()
    assert jd_keywords("   ") == set()
    assert jd_keywords("\t\n") == set()


# ── select_claims: Done-when "select_claims ranks by JD-overlap" ─────────────


def test_select_claims_ranks_highest_first():
    """select_claims: a claim with more matching JD keywords outranks one with fewer."""
    ev1 = _evidence("PR#1")
    ev2 = _evidence("PR#2")
    low = _claim("python scripting", ["PR#1"])
    high = _claim("python kubernetes docker container", ["PR#2"])
    portfolio = _portfolio(claims=[low, high], evidence=[ev1, ev2])
    result = select_claims(portfolio, {"python", "kubernetes", "docker", "container"}, top_n=10)
    assert result[0].claim is high
    assert result[1].claim is low


# ── select_claims: Done-when "ties broken stably by original order" ──────────


def test_select_claims_stable_tie_break():
    """select_claims: ties broken stably by the original order in portfolio.claims."""
    ev = _evidence("PR#1")
    a = _claim("python scripting tool", ["PR#1"])
    b = _claim("python developer fast", ["PR#1"])
    portfolio = _portfolio(claims=[a, b], evidence=[ev])
    result = select_claims(portfolio, {"python"}, top_n=10)
    assert result[0].claim is a
    assert result[1].claim is b


# ── select_claims: Done-when "caps at top_n and excludes score-0" ────────────


def test_select_claims_top_n_cap():
    """select_claims: caps the result at top_n."""
    ev = _evidence("PR#1")
    claims = [_claim(f"python developer job{i}", ["PR#1"]) for i in range(10)]
    portfolio = _portfolio(claims=claims, evidence=[ev])
    result = select_claims(portfolio, {"python"}, top_n=3)
    assert len(result) == 3


def test_select_claims_excludes_score_zero():
    """select_claims: excludes claims with score 0 (no JD keyword overlap)."""
    ev = _evidence("PR#1")
    irrelevant = _claim("unrelated content here", ["PR#1"])
    relevant = _claim("python developer role", ["PR#1"])
    portfolio = _portfolio(claims=[irrelevant, relevant], evidence=[ev])
    result = select_claims(portfolio, {"python"}, top_n=10)
    assert len(result) == 1
    assert result[0].claim is relevant


# ── select_claims: Done-when "preserves evidence_refs" ───────────────────────


def test_select_claims_preserves_evidence_refs():
    """select_claims: preserves each selected claim's original evidence_refs (no mutation)."""
    ev1 = _evidence("PR#1")
    ev2 = _evidence("PR#2")
    claim = _claim("python microservices", ["PR#1", "PR#2"])
    portfolio = _portfolio(claims=[claim], evidence=[ev1, ev2])
    result = select_claims(portfolio, {"python"}, top_n=5)
    assert len(result) == 1
    assert result[0].claim.evidence_refs == ["PR#1", "PR#2"]


# ── enforce_grounding: Done-when "foreign claim is dropped" ──────────────────


def test_enforce_grounding_drops_foreign_claim():
    """Honesty re-check: ScoredClaim wrapping a Claim not in portfolio.claims is dropped."""
    ev = _evidence("PR#1")
    real_claim = _claim("python developer", ["PR#1"])
    # Different object identity — looks the same but is a separate Claim instance
    foreign_claim = _claim("python developer", ["PR#1"])
    portfolio = _portfolio(claims=[real_claim], evidence=[ev])
    scored = [ScoredClaim(claim=foreign_claim, score=5, matched_keywords={"python"})]
    result = enforce_grounding(scored, portfolio)
    assert result == []


# ── enforce_grounding: Done-when "invalid evidence_refs drops claim" ─────────


def test_enforce_grounding_drops_claim_with_hallucinated_ref():
    """Honesty re-check: claim whose evidence_refs are not a subset of portfolio evidence is dropped."""
    ev = _evidence("PR#1")
    claim = _claim("python developer", ["PR#1", "PR#INVENTED"])
    portfolio = _portfolio(claims=[claim], evidence=[ev])
    scored = [ScoredClaim(claim=claim, score=3, matched_keywords={"python"})]
    result = enforce_grounding(scored, portfolio)
    assert result == []


def test_enforce_grounding_passes_valid_claim():
    """Honesty re-check: valid claim in portfolio.claims with subset evidence_refs passes through."""
    ev1 = _evidence("PR#1")
    ev2 = _evidence("PR#2")
    claim = _claim("python kubernetes", ["PR#1", "PR#2"])
    portfolio = _portfolio(claims=[claim], evidence=[ev1, ev2])
    scored = [ScoredClaim(claim=claim, score=2, matched_keywords={"python", "kubernetes"})]
    result = enforce_grounding(scored, portfolio)
    assert len(result) == 1
    assert result[0].claim is claim


def test_enforce_grounding_drops_empty_evidence_refs():
    """Honesty re-check: claim with empty evidence_refs is dropped (ungrounded — cites no evidence)."""
    claim = _claim("python developer", refs=[])  # no refs — violates grounding contract
    portfolio = _portfolio(claims=[claim], evidence=[])
    scored = [ScoredClaim(claim=claim, score=3, matched_keywords={"python"})]
    result = enforce_grounding(scored, portfolio)
    assert result == []


def test_build_resume_drops_empty_evidence_refs():
    """build_resume: claim with empty evidence_refs is dropped by the honesty re-check (regression)."""
    ev = _evidence("PR#1")
    empty_ref_claim = _claim("python cloud deployment", refs=[])  # no evidence cited
    real_claim = _claim("kubernetes orchestration", ["PR#1"])
    portfolio = Portfolio(subject="dave", evidence=[ev], claims=[empty_ref_claim, real_claim])
    result = build_resume(portfolio, "python cloud deployment kubernetes orchestration", top_n=5)
    # empty_ref_claim must be dropped; real_claim passes
    assert all(sc.claim is not empty_ref_claim for sc in result.selected)
    assert any(sc.claim is real_claim for sc in result.selected)


# ── build_resume: Done-when "deterministic, subject propagated, keywords union" ─


def test_build_resume_deterministic():
    """build_resume: same inputs always produce identical ResumeDraft output."""
    ev = _evidence("PR#1")
    claim = _claim("python microservices", ["PR#1"])
    portfolio = _portfolio(claims=[claim], evidence=[ev])
    result1 = build_resume(portfolio, "python microservices cloud", top_n=5)
    result2 = build_resume(portfolio, "python microservices cloud", top_n=5)
    assert result1.subject == result2.subject
    assert len(result1.selected) == len(result2.selected)
    assert result1.jd_keywords_matched == result2.jd_keywords_matched


def test_build_resume_propagates_subject():
    """build_resume: subject is propagated from portfolio to ResumeDraft."""
    ev = _evidence("PR#1")
    claim = _claim("python developer", ["PR#1"])
    portfolio = _portfolio(claims=[claim], evidence=[ev])
    portfolio.subject = "bob"
    result = build_resume(portfolio, "python developer", top_n=5)
    assert result.subject == "bob"


def test_build_resume_jd_keywords_matched_is_union():
    """build_resume: jd_keywords_matched is the union of matched keywords across selected claims."""
    ev1 = _evidence("PR#1")
    ev2 = _evidence("PR#2")
    claim1 = _claim("python scripting", ["PR#1"])
    claim2 = _claim("kubernetes docker", ["PR#2"])
    portfolio = _portfolio(claims=[claim1, claim2], evidence=[ev1, ev2])
    result = build_resume(portfolio, "python kubernetes docker scripting", top_n=5)
    assert "python" in result.jd_keywords_matched
    assert "kubernetes" in result.jd_keywords_matched
    assert "docker" in result.jd_keywords_matched


def test_build_resume_drops_grounding_violations():
    """build_resume: claims with hallucinated evidence_refs are dropped by the honesty re-check."""
    ev = _evidence("PR#1")
    # Claim cites a ref not in the portfolio's evidence
    bad_claim = _claim("python cloud deployment", ["PR#1", "PR#HALLUCINATED"])
    portfolio = Portfolio(subject="carol", evidence=[ev], claims=[bad_claim])
    result = build_resume(portfolio, "python cloud deployment", top_n=5)
    assert len(result.selected) == 0


# ── No subprocess / network / model call ─────────────────────────────────────


def test_select_module_has_no_forbidden_imports():
    """No network/subprocess/model call: resume.select does not directly import subprocess, urllib, http, or socket."""
    import resume.select as sel_mod

    for forbidden in ("subprocess", "urllib", "http", "socket"):
        assert forbidden not in vars(sel_mod), f"resume.select must not directly import {forbidden!r}"


def test_select_functions_do_not_call_subprocess(monkeypatch):
    """No subprocess call: patching subprocess.run to raise confirms resume functions never call it."""
    import subprocess

    def _fail(*args, **kwargs):
        raise AssertionError("subprocess.run was called from resume.select")

    monkeypatch.setattr(subprocess, "run", _fail)
    ev = _evidence("PR#1")
    claim = _claim("python developer", ["PR#1"])
    portfolio = _portfolio(claims=[claim], evidence=[ev])
    # All three public functions must run without triggering subprocess
    jd_keywords("python developer backend")
    select_claims(portfolio, {"python"}, top_n=5)
    build_resume(portfolio, "python developer", top_n=5)


# ── ScoredClaim and ResumeDraft dataclass structure ─────────────────────────


def test_scored_claim_carries_original_claim_reference():
    """ScoredClaim carries the original Claim by reference (not a copy)."""
    claim = _claim("python developer", ["PR#1"])
    sc = ScoredClaim(claim=claim, score=1, matched_keywords={"python"})
    assert sc.claim is claim
    assert sc.score == 1
    assert sc.matched_keywords == {"python"}


def test_resume_draft_structure():
    """ResumeDraft has subject, selected, and jd_keywords_matched fields."""
    draft = ResumeDraft(subject="alice", selected=[], jd_keywords_matched={"python"})
    assert draft.subject == "alice"
    assert draft.selected == []
    assert draft.jd_keywords_matched == {"python"}
