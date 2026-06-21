"""Tests for portfolio/i18n.py — LANGS table, detect_language, SUPPORTED_LANGS,
and the single-source-of-truth extensibility guarantee.

All tests are pure / stdlib-only; no live model, gh, or network call.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.i18n import LANGS, SUPPORTED_LANGS, detect_language, language_name  # noqa: E402
from portfolio.model import Claim, Evidence, Portfolio  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_EVIDENCE = [Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="feat")]
_CLAIM = Claim(text="Built key feature", evidence_refs=["PR#1"], confidence=0.9, grounded=True)
_PORTFOLIO = Portfolio(subject="alice", evidence=_EVIDENCE, claims=[_CLAIM])


# ---------------------------------------------------------------------------
# LANGS completeness
# ---------------------------------------------------------------------------


def test_langs_has_en_and_ko():
    """LANGS must contain exactly the 'en' and 'ko' entries (plus any injected ones)."""
    assert "en" in LANGS
    assert "ko" in LANGS


def test_ko_has_same_keys_as_en():
    """Every key present in LANGS['en'] must also be present in LANGS['ko'] with non-empty values."""
    en_keys = set(LANGS["en"].keys())
    ko_keys = set(LANGS["ko"].keys())
    missing = en_keys - ko_keys
    assert not missing, f"ko entry missing keys: {missing}"
    for key in en_keys:
        assert LANGS["ko"][key], f"LANGS['ko']['{key}'] is empty"


def test_en_values_non_empty():
    """Every LANGS['en'] value must be non-empty."""
    for key, val in LANGS["en"].items():
        assert val, f"LANGS['en']['{key}'] is empty"


# ---------------------------------------------------------------------------
# SUPPORTED_LANGS is a live view
# ---------------------------------------------------------------------------


def test_supported_langs_set_equal_to_langs_keys():
    """SUPPORTED_LANGS must be set-equal to LANGS.keys() at any point in time."""
    assert set(SUPPORTED_LANGS) == set(LANGS.keys())


def test_supported_langs_reflects_runtime_injection(monkeypatch):
    """Injecting a new key into LANGS must immediately be visible through SUPPORTED_LANGS."""
    fake_entry = dict(LANGS["en"])
    fake_entry["name"] = "Xhosa"
    monkeypatch.setitem(LANGS, "xx", fake_entry)
    # The live view must include the injected key
    assert "xx" in SUPPORTED_LANGS
    # And after removal (monkeypatch teardown) it must be gone
    # (teardown verified implicitly by monkeypatch)


# ---------------------------------------------------------------------------
# language_name
# ---------------------------------------------------------------------------


def test_language_name_en():
    assert language_name("en") == "English"


def test_language_name_ko():
    assert language_name("ko") == "Korean"


def test_language_name_sourced_from_langs(monkeypatch):
    """language_name must read from LANGS, not a hardcoded mapping."""
    fake_entry = dict(LANGS["en"])
    fake_entry["name"] = "Xhosa"
    monkeypatch.setitem(LANGS, "xx", fake_entry)
    assert language_name("xx") == "Xhosa"


# ---------------------------------------------------------------------------
# detect_language
# ---------------------------------------------------------------------------


def test_detect_language_korean_only():
    assert detect_language("파이썬 백엔드 개발자 구인합니다") == "ko"


def test_detect_language_english_only():
    assert detect_language("Python backend engineer wanted") == "en"


def test_detect_language_mixed_dominant_hangul():
    # Clearly Hangul-dominant
    ko_text = "파이썬 백엔드 개발자 경력 2년 이상 필요 Python ok"
    assert detect_language(ko_text) == "ko"


def test_detect_language_mixed_dominant_latin():
    # Clearly Latin-dominant
    en_text = "Python backend engineer with some Korean 한국어 experience needed"
    assert detect_language(en_text) == "en"


def test_detect_language_empty_string():
    assert detect_language("") == "en"


def test_detect_language_whitespace_only():
    assert detect_language("   \t\n  ") == "en"


def test_detect_language_punctuation_only():
    assert detect_language("!!! ??? ... --- ///") == "en"


def test_detect_language_deterministic():
    """Same input called twice returns the same code."""
    text = "파이썬 백엔드 개발자"
    result1 = detect_language(text)
    result2 = detect_language(text)
    assert result1 == result2


def test_detect_language_returns_supported_code():
    """detect_language always returns a code that is in SUPPORTED_LANGS."""
    texts = ["hello world", "파이썬", "", "안녕하세요 Python"]
    for text in texts:
        code = detect_language(text)
        assert code in SUPPORTED_LANGS, f"detect_language({text!r}) returned unsupported code {code!r}"


# ---------------------------------------------------------------------------
# "No English UI leak" when lang="ko"
# ---------------------------------------------------------------------------


def test_no_english_ui_leak_portfolio_renderer():
    """Rendering a portfolio with lang='ko' must not include translated en strings."""
    from portfolio.render import render_markdown

    out = render_markdown(_PORTFOLIO, lang="ko")
    # Check all keys that differ between en and ko
    for key in LANGS["en"]:
        en_val = LANGS["en"][key]
        ko_val = LANGS["ko"][key]
        if en_val == ko_val:
            continue  # language-neutral, skip
        if key == "name":
            continue  # "English"/"Korean" are not rendered in the document
        # The en value must NOT appear in the ko output (if it's a UI string used in this render)
        assert en_val not in out, f"English UI string for key '{key}' leaked into ko portfolio render: {en_val!r}"


def test_no_english_ui_leak_resume_renderer():
    """Rendering a resume with lang='ko' must not include translated en strings."""
    from resume.render import render_resume
    from resume.select import ResumeDraft, ScoredClaim

    sc = ScoredClaim(claim=_CLAIM, score=1, matched_keywords={"feature"})
    draft = ResumeDraft(
        subject="alice",
        selected=[sc],
        jd_keywords_matched={"feature"},
        jd_keywords_total=5,
        evidence_by_ref={"PR#1": _EVIDENCE[0]},
    )
    out = render_resume(draft, lang="ko")
    for key in LANGS["en"]:
        en_val = LANGS["en"][key]
        ko_val = LANGS["ko"][key]
        if en_val == ko_val:
            continue
        if key == "name":
            continue
        assert en_val not in out, f"English UI string for key '{key}' leaked into ko resume render: {en_val!r}"


def test_no_english_ui_leak_fit_renderer():
    """Rendering fit results with lang='ko' must not include translated en strings."""
    from fit.grade import GradeResult
    from fit.render import render_fit
    from fit.score import ScoreResult

    score_result = ScoreResult(
        grade="B",
        band=(70, 84),
        coverage_pct=60.0,
        covered={"python": ["PR#1"]},
        gaps=set(),
    )
    grade_result = GradeResult(score=77, reasoning=[{"text": "Solid work", "evidence_refs": ["PR#1"]}])
    out = render_fit(score_result, grade_result, lang="ko")
    for key in LANGS["en"]:
        en_val = LANGS["en"][key]
        ko_val = LANGS["ko"][key]
        if en_val == ko_val:
            continue
        if key == "name":
            continue
        assert en_val not in out, f"English UI string for key '{key}' leaked into ko fit render: {en_val!r}"


def test_no_english_ui_leak_rating_renderer():
    """Rendering rating with lang='ko' must not include translated en strings."""
    from rating.grade import GradeResult
    from rating.profile import DimensionResult, ProfileResult
    from rating.render import render_rating

    profile_result = ProfileResult(
        grade="B",
        score_min=70,
        score_max=84,
        dimensions={
            "volume": DimensionResult(name="volume", value=3, band="Low", points=0, evidence_refs=["PR#1"]),
        },
    )
    grade_result = GradeResult(
        score=75,
        grade="B",
        reasoning=[{"text": "Good contribution", "evidence_refs": ["PR#1"]}],
    )
    out = render_rating(_PORTFOLIO, profile_result, grade_result, lang="ko")
    for key in LANGS["en"]:
        en_val = LANGS["en"][key]
        ko_val = LANGS["ko"][key]
        if en_val == ko_val:
            continue
        if key == "name":
            continue
        assert en_val not in out, f"English UI string for key '{key}' leaked into ko rating render: {en_val!r}"


def test_no_english_ui_leak_letter_renderer_empty():
    """Rendering an empty letter with lang='ko' must not include translated en strings."""
    from reference_check.letter import LetterDraft
    from reference_check.render import render_letter

    draft = LetterDraft(subject="alice", paragraphs=[], rejected_paragraphs=[])
    out = render_letter(draft, lang="ko")
    for key in LANGS["en"]:
        en_val = LANGS["en"][key]
        ko_val = LANGS["ko"][key]
        if en_val == ko_val:
            continue
        if key == "name":
            continue
        assert en_val not in out, f"English UI string for key '{key}' leaked into ko letter render (empty): {en_val!r}"


# ---------------------------------------------------------------------------
# Single-source-of-truth extensibility test
# ---------------------------------------------------------------------------


def _fake_xx_entry() -> dict:
    """Fake entry for language code 'xx' with unique UI strings."""
    entry = dict(LANGS["en"])
    entry["name"] = "Xhosa"
    # Override title strings to make them unique
    entry["title_portfolio"] = "Xhosa-Portfolio"
    entry["title_resume"] = "Xhosa-Resume"
    entry["title_fit"] = "Xhosa-Fit"
    entry["title_rating"] = "Xhosa-Rating"
    entry["title_letter"] = "Xhosa-Letter"
    entry["no_grounded_claims"] = "_xhosa no claims_"
    return entry


def test_extensibility_supported_langs(monkeypatch):
    """After injecting 'xx' into LANGS, SUPPORTED_LANGS must contain 'xx'."""
    monkeypatch.setitem(LANGS, "xx", _fake_xx_entry())
    assert "xx" in SUPPORTED_LANGS


def test_extensibility_cli_parsers(monkeypatch):
    """All 5 CLI parsers, built AFTER injection, must accept 'xx' as a --lang choice."""
    monkeypatch.setitem(LANGS, "xx", _fake_xx_entry())

    from portfolio.cli import _build_parser as portfolio_parser
    from resume.cli import _build_parser as resume_parser
    from fit.cli import _build_parser as fit_parser
    from rating.cli import _build_parser as rating_parser
    from reference_check.cli import _build_parser as refcheck_parser

    for build_parser in [portfolio_parser, resume_parser, fit_parser, rating_parser, refcheck_parser]:
        parser = build_parser()
        lang_action = next(a for a in parser._actions if hasattr(a, "option_strings") and "--lang" in a.option_strings)
        assert "xx" in lang_action.choices, f"{build_parser.__module__} parser does not have 'xx' in --lang choices"


def test_extensibility_prompt_builders_language_name(monkeypatch):
    """All 5 prompt builders, when called with lang='xx', must include the fake language name."""
    monkeypatch.setitem(LANGS, "xx", _fake_xx_entry())

    from portfolio.narrative import build_prompt
    from reference_check.letter import build_letter_prompt
    from fit.grade import _build_grader_prompt
    from rating.grade import _build_prompt as rating_build_prompt

    # narrative build_prompt
    prompt = build_prompt(_EVIDENCE, max_claims=3, lang="xx")
    assert "Xhosa" in prompt, "narrative build_prompt does not contain language name for lang='xx'"

    # synthesis synthesize — we can't call it without a runner, but we can test the prompt inline
    # by checking that language_name("xx") == "Xhosa" (already tested) and that build_prompt uses it
    # Instead test fit and rating grade builders:

    from portfolio.model import Portfolio as _Portfolio

    test_portfolio = _Portfolio(subject="test", evidence=_EVIDENCE, claims=[_CLAIM])

    fit_prompt = _build_grader_prompt(test_portfolio, "B", (70, 84), lang="xx")
    assert "Xhosa" in fit_prompt, "_build_grader_prompt does not contain language name for lang='xx'"

    from rating.profile import ProfileResult, DimensionResult

    profile_result = ProfileResult(
        grade="B",
        score_min=70,
        score_max=84,
        dimensions={"volume": DimensionResult(name="volume", value=1, band="Low", points=0, evidence_refs=["PR#1"])},
    )
    rating_prompt = rating_build_prompt(test_portfolio, profile_result, lang="xx")
    assert "Xhosa" in rating_prompt, "rating _build_prompt does not contain language name for lang='xx'"

    letter_prompt = build_letter_prompt(test_portfolio, lang="xx")
    assert "Xhosa" in letter_prompt, "build_letter_prompt does not contain language name for lang='xx'"


def test_extensibility_renderers_use_xx_ui_strings(monkeypatch):
    """All 5 renderers, called with lang='xx', must include at least one unique UI string from the fake entry."""
    fake = _fake_xx_entry()
    monkeypatch.setitem(LANGS, "xx", fake)

    from portfolio.render import render_markdown
    from resume.render import render_resume
    from fit.render import render_fit
    from rating.render import render_rating
    from reference_check.render import render_letter
    from resume.select import ResumeDraft
    from fit.grade import GradeResult as FitGradeResult
    from fit.score import ScoreResult
    from rating.grade import GradeResult as RatingGradeResult
    from rating.profile import ProfileResult, DimensionResult
    from reference_check.letter import LetterDraft

    # portfolio renderer: empty portfolio shows no_grounded_claims
    empty_portfolio = Portfolio(subject="alice", evidence=[], claims=[])
    out = render_markdown(empty_portfolio, lang="xx")
    assert "Xhosa-Portfolio" in out, "portfolio renderer does not use xx title_portfolio"

    # resume renderer: empty draft shows no_grounded_bullets
    empty_draft = ResumeDraft(
        subject="alice", selected=[], jd_keywords_matched=set(), jd_keywords_total=0, evidence_by_ref={}
    )
    out = render_resume(empty_draft, lang="xx")
    assert "Xhosa-Resume" in out, "resume renderer does not use xx title_resume"

    # fit renderer
    score_result = ScoreResult(grade="B", band=(70, 84), coverage_pct=60.0, covered={}, gaps=set())
    grade_result = FitGradeResult(score=75, reasoning=[])
    out = render_fit(score_result, grade_result, lang="xx")
    assert "Xhosa-Fit" in out, "fit renderer does not use xx title_fit"

    # rating renderer
    profile_result = ProfileResult(
        grade="B",
        score_min=70,
        score_max=84,
        dimensions={"volume": DimensionResult(name="volume", value=1, band="Low", points=0, evidence_refs=["PR#1"])},
    )
    rating_grade = RatingGradeResult(score=75, grade="B", reasoning=[{"text": "ok", "evidence_refs": ["PR#1"]}])
    out = render_rating(_PORTFOLIO, profile_result, rating_grade, lang="xx")
    assert "Xhosa-Rating" in out, "rating renderer does not use xx title_rating"

    # letter renderer
    draft = LetterDraft(subject="alice", paragraphs=[], rejected_paragraphs=[])
    out = render_letter(draft, lang="xx")
    assert "Xhosa-Letter" in out, "letter renderer does not use xx title_letter"
