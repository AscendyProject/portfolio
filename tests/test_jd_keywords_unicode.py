"""Tests for Unicode-aware jd_keywords / _claim_tokens in resume/select.py.

Covers:
- Korean JD text produces a non-empty keyword set.
- A Korean portfolio claim matches a Korean JD keyword via select_claims.
- Pure-ASCII English input path is byte-identical to prior behaviour (regression guard).
- fit coverage on a Korean JD does NOT degenerate to 100% from an empty keyword set.

All tests are pure/stdlib-only; no live model, gh, or network call.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.model import Claim, Evidence, Portfolio  # noqa: E402
from resume.select import (  # noqa: E402
    STOPWORDS,
    build_resume,
    jd_keywords,
    select_claims,
)
from fit.score import score_fit  # noqa: E402


# ---------------------------------------------------------------------------
# Korean JD tokenization
# ---------------------------------------------------------------------------


def test_korean_jd_produces_nonempty_keywords():
    """A Korean JD fixture must produce a non-empty keyword set."""
    ko_jd = "파이썬 백엔드 개발자 경력 2년 이상 필요합니다. 쿠버네티스 경험 우대."
    result = jd_keywords(ko_jd)
    assert len(result) > 0, "Korean JD should produce at least one keyword token"


def test_korean_jd_contains_hangul_tokens():
    """The keyword set from a Korean JD contains the expected Hangul tokens."""
    ko_jd = "파이썬 백엔드 개발자"
    result = jd_keywords(ko_jd)
    # Each space-delimited word should be a token (no non-letter separators between Hangul chars)
    assert "파이썬" in result
    assert "백엔드" in result
    assert "개발자" in result


def test_korean_jd_drops_stopwords():
    """Korean stopword filtering: only ASCII STOPWORDS are dropped; Korean words pass through."""
    ko_jd = "파이썬 and 백엔드"
    result = jd_keywords(ko_jd)
    assert "파이썬" in result
    assert "백엔드" in result
    assert "and" not in result  # 'and' is an ASCII stopword


def test_korean_claim_matches_korean_jd_via_select_claims():
    """A Korean portfolio claim referencing a Korean JD keyword scores > 0 via select_claims."""
    ev = Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="feat")
    claim = Claim(text="파이썬 백엔드 서비스 개발", evidence_refs=["PR#1"], confidence=0.9, grounded=True)
    portfolio = Portfolio(subject="alice", evidence=[ev], claims=[claim])

    ko_jd = "파이썬 백엔드 개발자 모집"
    kw = jd_keywords(ko_jd)
    assert len(kw) > 0, "Korean JD must produce keywords"

    scored = select_claims(portfolio, kw, top_n=5)
    assert len(scored) > 0, "Korean claim should match Korean JD keywords"
    assert scored[0].score > 0


def test_korean_claim_score_positive_via_build_resume():
    """build_resume on a Korean JD with a matching Korean claim produces selected claims."""
    ev = Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="feat")
    claim = Claim(text="파이썬 백엔드 서비스 개발", evidence_refs=["PR#1"], confidence=0.9, grounded=True)
    portfolio = Portfolio(subject="alice", evidence=[ev], claims=[claim])

    ko_jd = "파이썬 백엔드 개발자"
    draft = build_resume(portfolio, ko_jd, top_n=5)
    assert len(draft.selected) > 0, "Korean claim should be selected for Korean JD"
    assert draft.jd_keywords_total > 0


# ---------------------------------------------------------------------------
# ASCII / English path regression guard
# ---------------------------------------------------------------------------
# Re-assert key behaviours from test_resume_select.py on English input to ensure
# the Unicode-aware tokenizer has not regressed ASCII behaviour.


def test_english_lowercases():
    """English path: lowercases input before tokenizing (regression guard)."""
    result = jd_keywords("Python Go KUBERNETES")
    assert "python" in result
    assert "go" in result
    assert "kubernetes" in result


def test_english_splits_on_non_alphanumerics():
    """English path: splits on non-alphanumerics (regression guard)."""
    result = jd_keywords("aws,gcp.azure:kubernetes-docker")
    assert result == {"aws", "gcp", "azure", "kubernetes", "docker"}


def test_english_removes_stopwords():
    """English path: removes the STOPWORDS constant (regression guard)."""
    stopword_input = " ".join(sorted(STOPWORDS))
    assert jd_keywords(stopword_input) == set()


def test_english_dedup():
    """English path: returns a set (regression guard)."""
    result = jd_keywords("python python python")
    assert result == {"python"}


def test_english_empty_input():
    """English path: empty/whitespace input returns empty set (regression guard)."""
    assert jd_keywords("") == set()
    assert jd_keywords("   ") == set()


def test_english_path_byte_identical_on_ascii_fixture():
    """Unicode tokenizer: ASCII English JD produces the same tokens as the old re.split path.

    Verifies byte-identical behaviour on a representative ASCII fixture.
    The old implementation was: {t for t in re.split(r'[^a-z0-9]+', text.lower()) if t and t not in STOPWORDS}
    """
    import re

    ascii_jd = "Python backend engineer with 3+ years of experience in Django and REST APIs"

    def old_tokenizer(text: str) -> set[str]:
        tokens = re.split(r"[^a-z0-9]+", text.lower())
        return {t for t in tokens if t and t not in STOPWORDS}

    old_result = old_tokenizer(ascii_jd)
    new_result = jd_keywords(ascii_jd)
    assert old_result == new_result, (
        f"Unicode tokenizer differs from old ASCII tokenizer on English input.\n"
        f"Old: {sorted(old_result)}\nNew: {sorted(new_result)}"
    )


# ---------------------------------------------------------------------------
# Korean JD fit coverage: not degenerate (100%) from empty keyword set
# ---------------------------------------------------------------------------


def test_korean_jd_fit_coverage_not_degenerate():
    """fit coverage on a Korean JD must NOT be 100% from an empty keyword set.

    Previously, empty jd_keywords → coverage_pct = 100.0 (division by zero branch).
    With the Unicode-aware tokenizer, a Korean JD produces non-empty keywords,
    so coverage is computed against a real non-empty denominator.
    """
    # A portfolio with no matching claims
    ev = Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="feat")
    claim = Claim(text="completely unrelated work", evidence_refs=["PR#1"], confidence=0.9, grounded=True)
    portfolio = Portfolio(subject="alice", evidence=[ev], claims=[claim])

    ko_jd = "파이썬 백엔드 개발자 쿠버네티스 도커 경험자 우대"

    score_result = score_fit(portfolio, ko_jd)
    kw = jd_keywords(ko_jd)

    # The JD must produce real keywords (non-empty denominator)
    assert len(kw) > 0, "Korean JD should produce non-empty keywords"

    # Coverage must NOT be 100.0 — the claim does not cover Korean keywords
    assert score_result.coverage_pct < 100.0, (
        f"Coverage should not be 100% for a non-matching Korean JD; got {score_result.coverage_pct}"
    )

    # jd_keywords_total in a build_resume call also reflects real Korean tokens
    ev2 = Evidence(kind="pr", ref="PR#2", url="https://github.com/o/r/pull/2", detail="feat")
    claim2 = Claim(text="completely unrelated work", evidence_refs=["PR#2"], confidence=0.9, grounded=True)
    portfolio2 = Portfolio(subject="bob", evidence=[ev2], claims=[claim2])
    draft = build_resume(portfolio2, ko_jd, top_n=5)
    assert draft.jd_keywords_total > 0, "jd_keywords_total must be > 0 for a Korean JD"


def test_korean_mixed_with_english_tokens():
    """Mixed Korean+English JD produces tokens from both scripts."""
    mixed_jd = "파이썬 Python 백엔드 backend 개발자"
    result = jd_keywords(mixed_jd)
    # Korean tokens
    assert "파이썬" in result
    assert "백엔드" in result
    assert "개발자" in result
    # English tokens (lowercased)
    assert "python" in result
    assert "backend" in result
