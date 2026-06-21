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
        if not isinstance(en_val, str):
            continue  # nested sub-mappings (e.g. dimension_names) handled by structural test
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
        if not isinstance(en_val, str):
            continue  # nested sub-mappings (e.g. dimension_names) handled by structural test
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
        if not isinstance(en_val, str):
            continue  # nested sub-mappings (e.g. dimension_names) handled by structural test
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
        if not isinstance(en_val, str):
            continue  # nested sub-mappings (e.g. dimension_names) handled by structural test
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
        if not isinstance(en_val, str):
            continue  # nested sub-mappings (e.g. dimension_names) handled by structural test
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
    from portfolio.synthesis import synthesize
    from reference_check.letter import build_letter_prompt
    from fit.grade import _build_grader_prompt
    from rating.grade import _build_prompt as rating_build_prompt

    # narrative build_prompt
    prompt = build_prompt(_EVIDENCE, max_claims=3, lang="xx")
    assert "Xhosa" in prompt, "narrative build_prompt does not contain language name for lang='xx'"

    # synthesis synthesize — invoke with a capturing runner to extract the built prompt
    synth_prompts: list[str] = []

    def _capturing_synth_runner(prompt: str) -> str:
        synth_prompts.append(prompt)
        return "{}"  # empty object → empty SynthesisResult, no parse error

    synthesize(_PORTFOLIO, _capturing_synth_runner, lang="xx")
    assert synth_prompts, "synthesize did not invoke the runner"
    assert "Xhosa" in synth_prompts[0], "synthesize prompt does not contain language name for lang='xx'"

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


# ---------------------------------------------------------------------------
# Structural English-leak test (IR-003 #5)
#
# Unlike the LANGS-value scan above, this renders the ko fixtures for all five
# renderers and asserts no *hardcoded* English UI word survives — so it FAILS if
# someone reintroduces a literal like "Volume", "Low", or "no stack detected"
# even after deleting the corresponding LANGS key.
# ---------------------------------------------------------------------------

import re  # noqa: E402

# Language-neutral tokens that legitimately contain ASCII letters and must be
# stripped before the leak scan to avoid false positives.
_REF_TOKEN_RE = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._/-]+(?:#\d+)?")  # owner/repo#n, owner/repo:path
_CODE_SPAN_RE = re.compile(r"`[^`]*`")  # `code` identifiers (e.g. JD keywords)
_URL_RE = re.compile(r"https?://\S+")
_MASK_RE = re.compile(r"private-repo-\d+")
_TABLE_RULE_RE = re.compile(r"^[|\s:-]+$", re.MULTILINE)  # markdown table separator rows

# Known English UI words emitted by the five renderers. A hardcoded leak of any
# of these into ko output must trip this test. Lowercased; matched whole-word.
_ENGLISH_UI_WORDS = {
    # portfolio/render.py
    "portfolio",
    "highlights",
    "confidence",
    "evidence",
    "other",
    "merged",
    "prs",
    "repos",
    "no",
    "stack",
    "detected",
    # resume/render.py
    "resume",
    "experience",
    "skills",
    "contact",
    "education",
    "contributions",
    # fit/render.py
    "fit",
    "assessment",
    "score",
    "band",
    "coverage",
    "covered",
    "requirements",
    "gaps",
    "grounded",
    "reasoning",
    "grade",
    "rubric",
    "none",
    "add",
    "your",
    "details",
    # rating/render.py
    "capability",
    "rating",
    "dimensions",
    "value",
    "points",
    "refs",
    # rating dimension / band labels
    "volume",
    "breadth",
    "diversity",
    "high",
    "steady",
    "low",
    "wide",
    "moderate",
    "narrow",
    "polyglot",
    "versatile",
    "focused",
    # reference_check/render.py
    "recommendation",
    "letter",
    "dear",
    "hiring",
    "manager",
    "sincerely",
    "insufficient",
}


def _strip_language_neutral(text: str) -> str:
    """Remove ref tokens, code-spans, URLs, masked placeholders, and table rules.

    What remains is the rendered UI prose; any ASCII word left here that matches a
    known English UI word is a hardcoded English-leak.
    """
    text = _URL_RE.sub(" ", text)
    text = _CODE_SPAN_RE.sub(" ", text)
    text = _MASK_RE.sub(" ", text)
    text = _REF_TOKEN_RE.sub(" ", text)
    text = _TABLE_RULE_RE.sub(" ", text)
    return text


def _ascii_words(text: str) -> set[str]:
    """Return the set of lowercased ASCII alphabetic words (len >= 2).

    Single letters (grade letters S/A/B/C/D, markdown bullets) are excluded.
    """
    return {w.lower() for w in re.findall(r"[A-Za-z]{2,}", text)}


def _assert_no_english_ui_leak(out: str, renderer: str) -> None:
    stripped = _strip_language_neutral(out)
    leaked = _ascii_words(stripped) & _ENGLISH_UI_WORDS
    assert not leaked, f"hardcoded English UI word(s) leaked into ko {renderer} render: {sorted(leaked)}"


# Korean-only content fixtures — no English in claim/JD/reasoning text, so any
# English ASCII word that survives the strip is a UI-string leak, not content.
_KO_EVIDENCE = [Evidence(kind="pr", ref="owner/repo#1", url="https://github.com/owner/repo/pull/1", detail="기능 추가")]
_KO_CLAIM = Claim(text="파이썬 백엔드 서비스 구축", evidence_refs=["owner/repo#1"], confidence=0.9, grounded=True)
_KO_PORTFOLIO = Portfolio(subject="홍길동", evidence=_KO_EVIDENCE, claims=[_KO_CLAIM])


def test_structural_no_english_leak_portfolio():
    """Structural: ko portfolio render contains no hardcoded English UI word."""
    from portfolio.render import render_markdown

    out = render_markdown(_KO_PORTFOLIO, lang="ko")
    _assert_no_english_ui_leak(out, "portfolio")


def test_structural_no_english_leak_portfolio_no_stack():
    """Structural: ko portfolio render with no detectable stack must not leak 'no stack detected'."""
    from portfolio.render import render_markdown

    # PR-only evidence → stack_summary falls into the 'none' branch (IR-001a).
    out = render_markdown(_KO_PORTFOLIO, lang="ko")
    _assert_no_english_ui_leak(out, "portfolio (no stack)")


def test_structural_no_english_leak_resume():
    """Structural: ko resume render contains no hardcoded English UI word."""
    from resume.render import render_resume
    from resume.select import ResumeDraft, ScoredClaim

    sc = ScoredClaim(claim=_KO_CLAIM, score=1, matched_keywords={"파이썬"})
    draft = ResumeDraft(
        subject="홍길동",
        selected=[sc],
        jd_keywords_matched={"파이썬"},
        jd_keywords_total=5,
        evidence_by_ref={"owner/repo#1": _KO_EVIDENCE[0]},
    )
    out = render_resume(draft, lang="ko")
    _assert_no_english_ui_leak(out, "resume")


def test_structural_no_english_leak_fit():
    """Structural: ko fit render contains no hardcoded English UI word."""
    from fit.grade import GradeResult
    from fit.render import render_fit
    from fit.score import ScoreResult

    score_result = ScoreResult(grade="B", band=(70, 84), coverage_pct=60.0, covered={}, gaps=set())
    grade_result = GradeResult(score=77, reasoning=[{"text": "탄탄한 작업", "evidence_refs": ["owner/repo#1"]}])
    out = render_fit(score_result, grade_result, lang="ko")
    _assert_no_english_ui_leak(out, "fit")


def test_structural_no_english_leak_rating():
    """Structural: ko rating render contains no hardcoded English UI word.

    Exercises every dimension key and a band value so a hardcoded 'Volume'/'Low'
    (IR-001b) would be caught.
    """
    from rating.grade import GradeResult
    from rating.profile import DimensionResult, ProfileResult
    from rating.render import render_rating

    profile_result = ProfileResult(
        grade="B",
        score_min=70,
        score_max=84,
        dimensions={
            "volume": DimensionResult(name="volume", value=3, band="Low", points=0, evidence_refs=["owner/repo#1"]),
            "breadth": DimensionResult(name="breadth", value=12, band="Moderate", points=1, evidence_refs=[]),
            "stack_diversity": DimensionResult(
                name="stack_diversity", value=5, band="Polyglot", points=2, evidence_refs=[]
            ),
        },
    )
    grade_result = GradeResult(
        score=75, grade="B", reasoning=[{"text": "좋은 기여", "evidence_refs": ["owner/repo#1"]}]
    )
    out = render_rating(_KO_PORTFOLIO, profile_result, grade_result, lang="ko")
    _assert_no_english_ui_leak(out, "rating")


def test_structural_no_english_leak_letter():
    """Structural: ko letter render contains no hardcoded English UI word."""
    from reference_check.letter import LetterDraft, LetterParagraph
    from reference_check.render import render_letter

    draft = LetterDraft(
        subject="홍길동",
        paragraphs=[LetterParagraph(text="훌륭한 개발자입니다", evidence_refs=["owner/repo#1"], grounded=True)],
        rejected_paragraphs=[],
    )
    out = render_letter(draft, lang="ko")
    _assert_no_english_ui_leak(out, "letter")


def test_dimension_band_tables_complete():
    """Every rating dimension key and band value is mapped in en AND ko (IR-004).

    The rating renderer falls back to the raw identifier for an unmapped
    dimension/band. This test proves that fallback is unreachable for real data:
    every dimension key and every band value that rating.profile can emit has a
    non-empty entry in each language's dimension_names / band_labels table, so no
    untranslated English heading or band label can leak into a localized render.
    """
    from rating.profile import _BREADTH_BANDS, _DIVERSITY_BANDS, _VOLUME_BANDS

    expected_dims = {"volume", "breadth", "stack_diversity"}
    expected_bands = {b[0] for b in (*_VOLUME_BANDS, *_BREADTH_BANDS, *_DIVERSITY_BANDS)}
    for lang in ("en", "ko"):
        dimension_names = LANGS[lang]["dimension_names"]
        band_labels = LANGS[lang]["band_labels"]
        for dim_key in expected_dims:
            assert dim_key in dimension_names and dimension_names[dim_key], (
                f"{lang} dimension_names missing {dim_key!r}"
            )
        for band in expected_bands:
            assert band in band_labels and band_labels[band], f"{lang} band_labels missing {band!r}"
