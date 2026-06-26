"""Tests for deterministic fit-score quality improvements (issue #37, deterministic part).

Covers:
  Part A.1 — JD_META_LINE_PATTERNS and _strip_meta_lines
  Part A.2 — JD_META_STOPWORDS, len<2 filter, pure-digit filter
  Part B   — _stem helper (deterministic ASCII suffix stemmer)
  Part C   — NON_CODE_AXES exclusion in score_fit / ScoreResult
  End-to-end ranking regression (well-matched vs poorly-matched)
  Preamble-robustness regression

Korean no-regression is guarded by tests/test_jd_keywords_unicode.py, which stays
green under verify.sh after this branch's changes.

No live model, gh, or network call. All in-process.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.model import Claim, Evidence, Portfolio  # noqa: E402
from resume.select import (  # noqa: E402
    JD_META_LINE_PATTERNS,
    JD_META_STOPWORDS,
    _claim_tokens,
    _stem,
    _strip_meta_lines,
    jd_keywords,
    select_claims,
)
from fit.score import NON_CODE_AXES, ScoreResult, score_fit  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_evidence(ref: str) -> Evidence:
    return Evidence(kind="pr", ref=ref, url=f"https://example.com/{ref}", detail=ref)


def _make_claim(text: str, refs: list[str]) -> Claim:
    return Claim(text=text, evidence_refs=refs, confidence=0.9, grounded=True)


def _make_portfolio(claim_text: str, refs: list[str] | None = None) -> Portfolio:
    if refs is None:
        refs = ["PR#1"]
    evidence = [_make_evidence(r) for r in refs]
    claim = _make_claim(claim_text, refs)
    return Portfolio(subject="alice", evidence=evidence, claims=[claim])


# ===========================================================================
# Part A.1 — JD_META_LINE_PATTERNS and _strip_meta_lines
# ===========================================================================


def test_jd_meta_line_patterns_is_importable_tuple():
    """JD_META_LINE_PATTERNS must be importable from resume.select and be a tuple."""
    assert isinstance(JD_META_LINE_PATTERNS, tuple)
    assert len(JD_META_LINE_PATTERNS) >= 2, "must include at least 2 patterns"


def test_jd_meta_line_patterns_matches_harness_preamble():
    """JD_META_LINE_PATTERNS must match the exact harness preamble line (case-insensitive)."""
    preamble = "Extracted job description for resume/fit keyword matching"
    matched = any(pat.match(preamble.strip()) for pat in JD_META_LINE_PATTERNS)
    assert matched, f"No pattern matched: {preamble!r}"


def test_jd_meta_line_patterns_matches_preamble_lowercase():
    """JD_META_LINE_PATTERNS must match preamble in all-lowercase (case-insensitive)."""
    preamble = "extracted job description for resume/fit keyword matching"
    matched = any(pat.match(preamble.strip()) for pat in JD_META_LINE_PATTERNS)
    assert matched, f"Pattern must be case-insensitive for: {preamble!r}"


def test_jd_meta_line_patterns_matches_generic_label_headers():
    """JD_META_LINE_PATTERNS must match generic <label>: header lines."""
    headers = [
        "job description:",
        "keywords:",
        "resume:",
        "portfolio:",
        "Job Description:",
        "Keywords:",
    ]
    for header in headers:
        matched = any(pat.match(header.strip()) for pat in JD_META_LINE_PATTERNS)
        assert matched, f"No pattern matched header: {header!r}"


def test_strip_meta_lines_removes_preamble_line():
    """_strip_meta_lines removes the harness preamble line and keeps real content."""
    text = "Extracted job description for resume/fit keyword matching\npython backend kubernetes"
    result = _strip_meta_lines(text)
    assert "python" in result
    assert "backend" in result
    assert "kubernetes" in result
    assert "Extracted job description" not in result


def test_strip_meta_lines_preserves_real_content():
    """_strip_meta_lines keeps all non-preamble lines intact."""
    text = "kubernetes migration\ndeployment automation"
    result = _strip_meta_lines(text)
    assert "kubernetes" in result
    assert "migration" in result
    assert "deployment" in result
    assert "automation" in result


def test_jd_keywords_strips_preamble_before_tokenizing():
    """jd_keywords with the harness preamble line + real requirements produces only real-requirement stems.

    Asserts: result contains python, backend, kubernetes (stemmed) and does NOT
    contain extracted, matching, description, job, keyword, resume, fit, portfolio.
    """
    jd = "Extracted job description for resume/fit keyword matching\npython backend kubernetes"
    result = jd_keywords(jd)
    # Real requirement tokens must survive (possibly stemmed)
    assert "python" in result
    assert "backend" in result
    assert "kubernetes" in result
    # Meta tokens must be absent
    for bad in ("extracted", "matching", "description", "job", "keyword", "resume", "fit", "portfolio"):
        assert bad not in result, f"Meta token {bad!r} must not appear in jd_keywords result"


def test_claim_tokens_strip_meta_lines():
    """_claim_tokens drops the preamble line directly, keeping only real claim stems.

    Asserted on _claim_tokens(claim)'s OWN output — NO intersection against a JD
    keyword set — so a no-op _claim_tokens (pre-change) cannot pass vacuously.
    """
    preamble = "Extracted job description for resume/fit keyword matching"
    claim = _make_claim(f"{preamble}\npython backend kubernetes", ["PR#1"])
    tokens = _claim_tokens(claim)
    # Real requirement stems must survive the preamble strip
    assert "python" in tokens
    assert "backend" in tokens
    assert "kubernetes" in tokens
    # Preamble / meta-line tokens must be absent from the claim's own tokens
    for bad in ("extracted", "matching", "description", "job", "keyword", "resume", "fit", "portfolio"):
        assert bad not in tokens, f"Meta token {bad!r} must not appear in _claim_tokens output"


# ===========================================================================
# Part A.2 — JD_META_STOPWORDS, len<2 filter, pure-digit filter
# ===========================================================================


def test_jd_meta_stopwords_is_importable_frozenset():
    """JD_META_STOPWORDS must be importable from resume.select and be a frozenset."""
    assert isinstance(JD_META_STOPWORDS, frozenset)


def test_jd_meta_stopwords_contains_required_tokens():
    """JD_META_STOPWORDS must contain all the tokens listed in the brief."""
    required = {
        "job",
        "description",
        "keywords",
        "keyword",
        "resume",
        "portfolio",
        "fit",
        "com",
        "extracted",
        "matching",
    }
    for tok in required:
        assert tok in JD_META_STOPWORDS, f"{tok!r} must be in JD_META_STOPWORDS"


def test_jd_keywords_drops_meta_stopwords_mid_sentence():
    """jd_keywords drops JD_META_STOPWORDS tokens even inside a real requirement line."""
    jd = "strong python backend resume preferred"
    result = jd_keywords(jd)
    assert "resume" not in result, "resume must be filtered by JD_META_STOPWORDS"
    assert "python" in result
    assert "backend" in result


def test_jd_keywords_drops_len_less_than_2():
    """jd_keywords drops tokens of length < 2 (single characters)."""
    result = jd_keywords("a b cd e")
    # Only "cd" survives (len 2); single chars dropped
    # (ignoring stemming, 'cd' stays 'cd')
    assert "cd" in result
    for bad in ("a", "b", "e"):
        assert bad not in result, f"Single-char token {bad!r} must be dropped"


def test_jd_keywords_drops_pure_digit_tokens():
    """jd_keywords drops pure-digit tokens."""
    result = jd_keywords("python 3 10 2024 microservices")
    for digit in ("3", "10", "2024"):
        assert digit not in result, f"Pure-digit {digit!r} must be dropped"
    assert "python" in result
    assert "microservice" in result or "microservices" in result  # stemmed or not


def test_claim_tokens_drop_meta_stopwords():
    """_claim_tokens drops meta stopwords, len<2, and pure-digit tokens directly.

    The claim text mixes real tokens (`python migrations`) with a meta stopword
    (`resume`, `job`, `description`), a len<2 token (`s`, `a`), and a pure-digit
    token (`10`, `2024`). Asserted on _claim_tokens(claim)'s OWN output with NO
    intersection against a JD keyword set, so a no-op _claim_tokens cannot pass.
    """
    claim = _make_claim("python migrations resume job description s a 10 2024 backend", ["PR#1"])
    tokens = _claim_tokens(claim)
    # Real stems survive
    assert "python" in tokens
    assert "backend" in tokens
    assert _stem("migrations") in tokens
    # Meta stopwords dropped
    for bad in ("resume", "job", "description"):
        assert bad not in tokens, f"Meta stopword {bad!r} must not appear in _claim_tokens output"
    # len<2 tokens dropped
    for bad in ("s", "a"):
        assert bad not in tokens, f"len<2 token {bad!r} must not appear in _claim_tokens output"
    # pure-digit tokens dropped
    for bad in ("10", "2024"):
        assert bad not in tokens, f"pure-digit token {bad!r} must not appear in _claim_tokens output"


# ===========================================================================
# Part B — _stem helper
# ===========================================================================


def test_stem_is_importable():
    """_stem must be importable from resume.select."""
    assert callable(_stem)


def test_stem_identity_on_non_ascii():
    """_stem must return non-ASCII (Korean) tokens unchanged."""
    assert _stem("파이썬") == "파이썬"
    assert _stem("개발자") == "개발자"
    assert _stem("쿠버네티스") == "쿠버네티스"


def test_stem_migration_migrations():
    """_stem collapses migration ↔ migrations to the same stem."""
    assert _stem("migration") == _stem("migrations")


def test_stem_deploy_variants():
    """_stem collapses deploy ↔ deploys ↔ deployed ↔ deploying to the same stem."""
    base = _stem("deploy")
    assert _stem("deploys") == base
    assert _stem("deployed") == base
    assert _stem("deploying") == base


def test_stem_container_containers():
    """_stem collapses container ↔ containers to the same stem."""
    assert _stem("container") == _stem("containers")


def test_stem_service_services():
    """_stem collapses service ↔ services to the same stem."""
    assert _stem("service") == _stem("services")


def test_stem_orchestrate_variants():
    """_stem collapses orchestrate ↔ orchestrated ↔ orchestrating to the same stem."""
    base = _stem("orchestrate")
    assert _stem("orchestrated") == base
    assert _stem("orchestrating") == base


def test_jd_keywords_produces_stemmed_tokens():
    """jd_keywords stems tokens: 'migrations' and 'migration' produce the same set."""
    result1 = jd_keywords("kubernetes migrations and deploys")
    result2 = jd_keywords("kubernetes migration deployed")
    assert result1 == result2, f"Stemmed sets must be equal:\n  result1={result1}\n  result2={result2}"


def test_claim_tokens_use_same_stems():
    """A Claim with 'ran migrations and deployed containers' matches JD 'migration deploy container'."""
    evidence = [_make_evidence("PR#1")]
    claim = _make_claim("ran migrations and deployed containers", ["PR#1"])
    portfolio = Portfolio(subject="alice", evidence=evidence, claims=[claim])
    jd_kw = jd_keywords("migration deploy container")
    scored = select_claims(portfolio, jd_kw, top_n=5)
    assert len(scored) > 0, "Claim must match JD via stem collapsing"
    # All three stems must be covered
    matched = scored[0].matched_keywords
    assert len(matched) >= 3, f"Expected at least 3 matched stems, got: {matched}"


def test_stem_match_end_to_end_select_claims():
    """select_claims matches 'migration' in JD against 'migrations' in claim via stems."""
    evidence = [_make_evidence("PR#1")]
    claim = _make_claim("database migrations container deployments", ["PR#1"])
    portfolio = Portfolio(subject="alice", evidence=evidence, claims=[claim])
    jd_kw = jd_keywords("migration deploy container")
    scored = select_claims(portfolio, jd_kw, top_n=5)
    assert len(scored) > 0
    assert scored[0].score > 0


def test_stem_match_end_to_end_score_fit():
    """score_fit.covered contains the shared stem when JD has 'migration' and claim has 'migrations'."""
    portfolio = _make_portfolio("database migrations and container deployments")
    result = score_fit(portfolio, "migration deploy container")
    assert result.coverage_pct > 0
    # covered dict must contain a stem that matches "migration" / "migrations"
    migration_stem = _stem("migration")
    assert (
        migration_stem in result.covered
    ), f"Expected {migration_stem!r} in covered; covered={set(result.covered.keys())}"


# ===========================================================================
# Part C — NON_CODE_AXES exclusion
# ===========================================================================


def test_non_code_axes_is_importable_frozenset():
    """NON_CODE_AXES must be importable from fit.score and be a frozenset."""
    assert isinstance(NON_CODE_AXES, frozenset)


def test_non_code_axes_contains_required_tokens():
    """NON_CODE_AXES must contain the stem of each listed non-codeable axis, including 'sales'."""
    required_raw = [
        "japanese",
        "english",
        "korean",
        "year",
        "years",
        "bachelor",
        "bachelors",
        "degree",
        "bs",
        "ms",
        "phd",
        "master",
        "masters",
        "sales",
    ]
    for tok in required_raw:
        stemmed = _stem(tok)
        assert stemmed in NON_CODE_AXES, f"_stem({tok!r})={stemmed!r} must be in NON_CODE_AXES"


def test_score_fit_excludes_non_code_axes_from_numerator_and_denominator():
    """score_fit with JD 'python backend years bachelor japanese' against portfolio
    covering 'python backend' produces coverage_pct == 100.0 (non-code tokens excluded
    from both numerator and denominator).
    """
    portfolio = _make_portfolio("python backend service")
    result = score_fit(portfolio, "python backend years bachelor japanese")
    assert result.coverage_pct == 100.0, (
        f"Expected 100.0 coverage but got {result.coverage_pct}; "
        f"covered={set(result.covered.keys())}, gaps={result.gaps}"
    )


def test_score_fit_non_code_requirements_field():
    """ScoreResult.non_code_requirements contains the non-codeable JD tokens."""
    portfolio = _make_portfolio("python backend service")
    result = score_fit(portfolio, "python backend years bachelor japanese")
    # Stemmed forms of years/bachelor/japanese must appear
    year_stem = _stem("years")
    bachelor_stem = _stem("bachelor")
    japanese_stem = _stem("japanese")
    assert (
        year_stem in result.non_code_requirements
    ), f"{year_stem!r} must be in non_code_requirements; got {result.non_code_requirements}"
    assert bachelor_stem in result.non_code_requirements
    assert japanese_stem in result.non_code_requirements


def test_score_fit_non_code_not_in_covered_or_gaps():
    """Non-codeable tokens must not appear in covered or gaps."""
    portfolio = _make_portfolio("python backend service")
    result = score_fit(portfolio, "python backend years bachelor japanese")
    non_code_stems = {_stem("years"), _stem("bachelor"), _stem("japanese")}
    for tok in non_code_stems:
        assert tok not in result.covered, f"{tok!r} must not be in covered"
        assert tok not in result.gaps, f"{tok!r} must not be in gaps"


def test_score_result_non_code_requirements_has_default():
    """ScoreResult.non_code_requirements must have a default so existing construction sites stay valid."""
    # Construct without non_code_requirements kwarg
    sr = ScoreResult(
        coverage_pct=50.0,
        covered={},
        gaps=set(),
        grade="D",
        band=(0, 54),
    )
    assert sr.non_code_requirements == set()


def test_jd_keywords_does_not_filter_non_code_axes():
    """jd_keywords (resume/select.py) does NOT filter NON_CODE_AXES — that's fit/score.py only."""
    result = jd_keywords("python years bachelor")
    year_stem = _stem("years")
    bachelor_stem = _stem("bachelor")
    # resume/select.jd_keywords must include the stems (NON_CODE_AXES filter is in fit/score.py)
    assert year_stem in result, f"jd_keywords must NOT filter NON_CODE_AXES; {year_stem!r} must be in result"
    assert bachelor_stem in result, f"jd_keywords must NOT filter NON_CODE_AXES; {bachelor_stem!r} must be in result"


# ===========================================================================
# End-to-end ranking regression
# ===========================================================================

# JD-MATCH: heavy in python / backend / kubernetes / microservices / deploy / container
_JD_MATCH = (
    "Senior Python Backend Engineer — Kubernetes microservices platform. "
    "Deploy containerized services on Kubernetes. Build and migrate backend "
    "microservices. Experience with container orchestration, service deployment, "
    "and backend API development. Python and Kubernetes required."
)

# JD-MISMATCH: heavy in java / spring / hibernate / jvm
_JD_MISMATCH = (
    "Senior Java Backend Engineer — Spring Boot microservices platform. "
    "Build Spring applications using Hibernate ORM. Experience with JVM tuning, "
    "Spring Framework, Hibernate entities, and Java backend development. "
    "Java and Spring Boot required. Hibernate persistence layer experience preferred."
)

# Portfolio claims about python / backend / kubernetes / microservices
_PORTFOLIO_CLAIMS = [
    "Built python backend microservices deployed on kubernetes",
    "Containerized applications using docker and deployed to kubernetes cluster",
    "Migrated backend services to kubernetes and automated deployments",
    "Developed python backend APIs and deployed microservices containers",
    "Orchestrated container deployments and migrated legacy services to kubernetes",
]


def _make_tech_portfolio() -> Portfolio:
    evidence = [_make_evidence(f"PR#{i + 1}") for i in range(len(_PORTFOLIO_CLAIMS))]
    claims = [_make_claim(text, [f"PR#{i + 1}"]) for i, text in enumerate(_PORTFOLIO_CLAIMS)]
    return Portfolio(subject="alice", evidence=evidence, claims=claims)


def test_well_matched_vs_poorly_matched_ranking_regression():
    """Well-matched JD coverage% must exceed poorly-matched by at least 30 percentage points."""
    portfolio = _make_tech_portfolio()
    match_result = score_fit(portfolio, _JD_MATCH)
    mismatch_result = score_fit(portfolio, _JD_MISMATCH)
    gap = match_result.coverage_pct - mismatch_result.coverage_pct
    assert gap >= 30.0, (
        f"Expected well-matched to beat poorly-matched by ≥30pp; "
        f"match={match_result.coverage_pct:.1f}%, mismatch={mismatch_result.coverage_pct:.1f}%, "
        f"gap={gap:.1f}pp"
    )


def test_well_matched_coverage_at_least_50_pct():
    """Well-matched JD coverage% must be >= 50.0 (not stuck in the ~26% defect range)."""
    portfolio = _make_tech_portfolio()
    match_result = score_fit(portfolio, _JD_MATCH)
    assert (
        match_result.coverage_pct >= 50.0
    ), f"Well-matched JD should score ≥50% coverage; got {match_result.coverage_pct:.1f}%"


# ===========================================================================
# Preamble-robustness regression
# ===========================================================================


def test_preamble_prepend_does_not_shift_coverage_more_than_2pct():
    """Prepending the harness preamble line to JD-MATCH shifts coverage_pct by ≤ 2.0pp."""
    portfolio = _make_tech_portfolio()
    no_preamble = score_fit(portfolio, _JD_MATCH)
    with_preamble = score_fit(
        portfolio,
        "Extracted job description for resume/fit keyword matching\n\n" + _JD_MATCH,
    )
    delta = abs(with_preamble.coverage_pct - no_preamble.coverage_pct)
    assert delta <= 2.0, (
        f"Preamble should not shift coverage by more than 2pp; "
        f"no_preamble={no_preamble.coverage_pct:.1f}%, "
        f"with_preamble={with_preamble.coverage_pct:.1f}%, delta={delta:.2f}pp"
    )
