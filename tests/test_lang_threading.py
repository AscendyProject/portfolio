"""Tests for --lang flag threading across all five CLIs and renderers.

Covers:
- Each CLI accepts --lang ko/en and threads it to the renderer AND prompt builder.
- fit/grade.py:bounded_grade and rating/grade.py:grade receive lang.
- resume and fit auto-detect "ko" from a Korean JD when --lang is omitted.
- resume and fit auto-detect "en" from an English JD when --lang is omitted.
- portfolio, rating, reference_check default to "en" when --lang is omitted.
- Explicit --lang ko with an English JD wins over detection (resume / fit).
- Rendering the same fixture twice with the same lang is byte-identical.
- Grounding / show_refs / mask behaviour is identical between lang="en" and lang="ko".

All tests inject fake extractor, runner, grader_runner, fetcher — no live services.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.i18n import LANGS, language_name  # noqa: E402
from portfolio.model import Claim, Evidence, Portfolio  # noqa: E402


# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------


def _fake_extractor(*, repo: str, author: str) -> list[Evidence]:
    """Returns canned Evidence; no network."""
    return [Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="Add feature")]


def _fake_runner(prompt: str) -> str:
    """Returns one grounded claim citing PR#1."""
    return json.dumps([{"text": "Built a Python backend service", "evidence_refs": ["PR#1"], "confidence": 0.9}])


def _capturing_runner():
    """Returns a runner that captures every prompt it receives."""
    prompts: list[str] = []

    def runner(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps([{"text": "Built a Python backend service", "evidence_refs": ["PR#1"], "confidence": 0.9}])

    return runner, prompts


def _capturing_grader_runner():
    """Returns a grader_runner that captures every prompt and returns valid JSON."""
    prompts: list[str] = []

    def grader_runner(prompt: str, *, temperature: float = 0) -> str:
        prompts.append(prompt)
        return json.dumps({"score": 75, "reasoning": [{"text": "solid match", "evidence_refs": ["PR#1"]}]})

    return grader_runner, prompts


def _make_jd_file(tmp_path: Path, text: str) -> str:
    p = tmp_path / "jd.txt"
    p.write_text(text, encoding="utf-8")
    return str(p)


_ENGLISH_JD = "Python backend engineer with experience in Django and REST APIs"
_KOREAN_JD = "파이썬 백엔드 개발자 경력 2년 이상 쿠버네티스 경험 우대"


# ---------------------------------------------------------------------------
# Prompt builder language-name tests (pure, no CLI)
# ---------------------------------------------------------------------------


def test_narrative_build_prompt_contains_language_name_ko():
    """narrative.build_prompt with lang='ko' must contain 'Korean' in the prompt."""
    from portfolio.narrative import build_prompt

    evidence = [Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="feat")]
    prompt = build_prompt(evidence, max_claims=3, lang="ko")
    assert language_name("ko") in prompt, "build_prompt should include the language name for lang='ko'"


def test_narrative_build_prompt_contains_language_name_en():
    """narrative.build_prompt with lang='en' must contain 'English' in the prompt."""
    from portfolio.narrative import build_prompt

    evidence = [Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="feat")]
    prompt = build_prompt(evidence, max_claims=3, lang="en")
    assert language_name("en") in prompt


def test_narrative_build_prompt_refs_byte_identical_across_langs():
    """narrative.build_prompt: the ref list is language-neutral — same refs for en and ko."""
    from portfolio.narrative import build_prompt

    evidence = [
        Evidence(kind="pr", ref="owner/repo#42", url="https://github.com/owner/repo/pull/42", detail="feat"),
        Evidence(kind="file", ref="owner/repo:src/main.py", url="", detail="file"),
    ]
    prompt_en = build_prompt(evidence, max_claims=3, lang="en")
    prompt_ko = build_prompt(evidence, max_claims=3, lang="ko")
    # The ref lines must appear identically in both prompts
    assert "owner/repo#42" in prompt_en
    assert "owner/repo#42" in prompt_ko
    assert "owner/repo:src/main.py" in prompt_en
    assert "owner/repo:src/main.py" in prompt_ko


def test_fit_grader_prompt_contains_language_name_ko():
    """fit._build_grader_prompt with lang='ko' must contain 'Korean'."""
    from fit.grade import _build_grader_prompt

    evidence = [Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="feat")]
    claim = Claim(text="Built thing", evidence_refs=["PR#1"], confidence=0.9, grounded=True)
    portfolio = Portfolio(subject="alice", evidence=evidence, claims=[claim])
    prompt = _build_grader_prompt(portfolio, "B", (70, 84), lang="ko")
    assert language_name("ko") in prompt


def test_fit_grader_prompt_contains_language_name_en():
    """fit._build_grader_prompt with lang='en' must contain 'English'."""
    from fit.grade import _build_grader_prompt

    evidence = [Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="feat")]
    claim = Claim(text="Built thing", evidence_refs=["PR#1"], confidence=0.9, grounded=True)
    portfolio = Portfolio(subject="alice", evidence=evidence, claims=[claim])
    prompt = _build_grader_prompt(portfolio, "B", (70, 84), lang="en")
    assert language_name("en") in prompt


def test_rating_grader_prompt_contains_language_name_ko():
    """rating._build_prompt with lang='ko' must contain 'Korean'."""
    from rating.grade import _build_prompt
    from rating.profile import DimensionResult, ProfileResult

    evidence = [Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="feat")]
    claim = Claim(text="Built thing", evidence_refs=["PR#1"], confidence=0.9, grounded=True)
    portfolio = Portfolio(subject="alice", evidence=evidence, claims=[claim])
    profile_result = ProfileResult(
        grade="B",
        score_min=70,
        score_max=84,
        dimensions={"volume": DimensionResult(name="volume", value=3, band="Low", points=0, evidence_refs=["PR#1"])},
    )
    prompt = _build_prompt(portfolio, profile_result, lang="ko")
    assert language_name("ko") in prompt


def test_letter_prompt_contains_language_name_ko():
    """reference_check.build_letter_prompt with lang='ko' must contain 'Korean'."""
    from reference_check.letter import build_letter_prompt

    evidence = [Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="feat")]
    claim = Claim(text="Built thing", evidence_refs=["PR#1"], confidence=0.9, grounded=True)
    portfolio = Portfolio(subject="alice", evidence=evidence, claims=[claim])
    prompt = build_letter_prompt(portfolio, lang="ko")
    assert language_name("ko") in prompt


# ---------------------------------------------------------------------------
# Renderer determinism: same (fixture, lang) → byte-identical output
# ---------------------------------------------------------------------------


def _make_portfolio() -> Portfolio:
    evidence = [Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="feat")]
    claim = Claim(text="Built a Python backend service", evidence_refs=["PR#1"], confidence=0.9, grounded=True)
    return Portfolio(subject="alice", evidence=evidence, claims=[claim])


def test_portfolio_renderer_deterministic_en():
    """render_markdown with lang='en' is byte-identical on two calls."""
    from portfolio.render import render_markdown

    p = _make_portfolio()
    out1 = render_markdown(p, lang="en")
    out2 = render_markdown(p, lang="en")
    assert out1 == out2


def test_portfolio_renderer_deterministic_ko():
    """render_markdown with lang='ko' is byte-identical on two calls."""
    from portfolio.render import render_markdown

    p = _make_portfolio()
    out1 = render_markdown(p, lang="ko")
    out2 = render_markdown(p, lang="ko")
    assert out1 == out2


def test_resume_renderer_deterministic_ko():
    """render_resume with lang='ko' is byte-identical on two calls."""
    from resume.render import render_resume
    from resume.select import ResumeDraft, ScoredClaim

    evidence = [Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="feat")]
    claim = Claim(text="Built thing", evidence_refs=["PR#1"], confidence=0.9, grounded=True)
    sc = ScoredClaim(claim=claim, score=1, matched_keywords={"python"})
    draft = ResumeDraft(
        subject="alice",
        selected=[sc],
        jd_keywords_matched={"python"},
        jd_keywords_total=5,
        evidence_by_ref={"PR#1": evidence[0]},
    )
    out1 = render_resume(draft, lang="ko")
    out2 = render_resume(draft, lang="ko")
    assert out1 == out2


def test_fit_renderer_deterministic_ko():
    """render_fit with lang='ko' is byte-identical on two calls."""
    from fit.grade import GradeResult
    from fit.render import render_fit
    from fit.score import ScoreResult

    score_result = ScoreResult(grade="B", band=(70, 84), coverage_pct=60.0, covered={"python": ["PR#1"]}, gaps=set())
    grade_result = GradeResult(score=77, reasoning=[{"text": "Solid work", "evidence_refs": ["PR#1"]}])
    out1 = render_fit(score_result, grade_result, lang="ko")
    out2 = render_fit(score_result, grade_result, lang="ko")
    assert out1 == out2


def test_rating_renderer_deterministic_ko():
    """render_rating with lang='ko' is byte-identical on two calls."""
    from rating.grade import GradeResult
    from rating.profile import DimensionResult, ProfileResult
    from rating.render import render_rating

    evidence = [Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="feat")]
    claim = Claim(text="Built thing", evidence_refs=["PR#1"], confidence=0.9, grounded=True)
    portfolio = Portfolio(subject="alice", evidence=evidence, claims=[claim])
    profile_result = ProfileResult(
        grade="B",
        score_min=70,
        score_max=84,
        dimensions={"volume": DimensionResult(name="volume", value=3, band="Low", points=0, evidence_refs=["PR#1"])},
    )
    grade_result = GradeResult(
        score=75,
        grade="B",
        reasoning=[{"text": "Good contribution", "evidence_refs": ["PR#1"]}],
    )
    out1 = render_rating(portfolio, profile_result, grade_result, lang="ko")
    out2 = render_rating(portfolio, profile_result, grade_result, lang="ko")
    assert out1 == out2


def test_letter_renderer_deterministic_ko():
    """render_letter with lang='ko' is byte-identical on two calls."""
    from reference_check.letter import LetterDraft
    from reference_check.render import render_letter

    draft = LetterDraft(subject="alice", paragraphs=[], rejected_paragraphs=[])
    out1 = render_letter(draft, lang="ko")
    out2 = render_letter(draft, lang="ko")
    assert out1 == out2


# ---------------------------------------------------------------------------
# portfolio CLI: --lang ko threads to renderer
# ---------------------------------------------------------------------------


def test_portfolio_cli_lang_ko_renderer_uses_korean_title(capsys):
    """portfolio CLI --lang ko: rendered output contains Korean title_portfolio."""
    from portfolio.cli import run

    code = run(
        ["--source-type", "github", "--source", "https://github.com/o/repo", "--author", "alice", "--lang", "ko"],
        extractor=_fake_extractor,
        runner=_fake_runner,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert LANGS["ko"]["title_portfolio"] in out


def test_portfolio_cli_lang_ko_prompt_contains_korean(capsys):
    """portfolio CLI --lang ko: narrative prompt contains 'Korean'."""
    from portfolio.cli import run

    runner, prompts = _capturing_runner()
    code = run(
        ["--source-type", "github", "--source", "https://github.com/o/repo", "--author", "alice", "--lang", "ko"],
        extractor=_fake_extractor,
        runner=runner,
    )
    capsys.readouterr()
    assert code == 0
    assert any(language_name("ko") in p for p in prompts), "narrative prompt should contain 'Korean'"


def test_portfolio_cli_default_lang_en(capsys):
    """portfolio CLI with no --lang uses en by default (English title in output)."""
    from portfolio.cli import run

    code = run(
        ["--source-type", "github", "--source", "https://github.com/o/repo", "--author", "alice"],
        extractor=_fake_extractor,
        runner=_fake_runner,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert LANGS["en"]["title_portfolio"] in out


# ---------------------------------------------------------------------------
# resume CLI: --lang ko, auto-detect, override
# ---------------------------------------------------------------------------


def test_resume_cli_lang_ko_renderer_uses_korean_title(capsys, tmp_path):
    """resume CLI --lang ko: rendered output contains Korean title_resume."""
    from resume.cli import run

    jd_path = _make_jd_file(tmp_path, _ENGLISH_JD)
    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/o/repo",
            "--author",
            "alice",
            "--jd",
            jd_path,
            "--lang",
            "ko",
        ],
        extractor=_fake_extractor,
        runner=_fake_runner,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert LANGS["ko"]["title_resume"] in out


def test_resume_cli_korean_jd_autodetect_ko(capsys, tmp_path):
    """resume CLI with no --lang and a Korean JD auto-detects 'ko'."""
    from resume.cli import run

    jd_path = _make_jd_file(tmp_path, _KOREAN_JD)
    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/o/repo",
            "--author",
            "alice",
            "--jd",
            jd_path,
        ],
        extractor=_fake_extractor,
        runner=_fake_runner,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert LANGS["ko"]["title_resume"] in out


def test_resume_cli_english_jd_autodetect_en(capsys, tmp_path):
    """resume CLI with no --lang and an English JD auto-detects 'en'."""
    from resume.cli import run

    jd_path = _make_jd_file(tmp_path, _ENGLISH_JD)
    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/o/repo",
            "--author",
            "alice",
            "--jd",
            jd_path,
        ],
        extractor=_fake_extractor,
        runner=_fake_runner,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert LANGS["en"]["title_resume"] in out


def test_resume_cli_explicit_lang_wins_over_jd_detection(capsys, tmp_path):
    """resume CLI: explicit --lang ko with an English JD wins over JD detection."""
    from resume.cli import run

    jd_path = _make_jd_file(tmp_path, _ENGLISH_JD)
    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/o/repo",
            "--author",
            "alice",
            "--jd",
            jd_path,
            "--lang",
            "ko",
        ],
        extractor=_fake_extractor,
        runner=_fake_runner,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert LANGS["ko"]["title_resume"] in out


# ---------------------------------------------------------------------------
# fit CLI: --lang ko, auto-detect, grader_runner language, override
# ---------------------------------------------------------------------------


def test_fit_cli_lang_ko_renderer_uses_korean_title(capsys, tmp_path):
    """fit CLI --lang ko: rendered output contains Korean title_fit."""
    from fit.cli import run

    grader_runner, _ = _capturing_grader_runner()
    jd_path = _make_jd_file(tmp_path, _ENGLISH_JD)
    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/o/repo",
            "--author",
            "alice",
            "--jd",
            jd_path,
            "--lang",
            "ko",
        ],
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=grader_runner,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert LANGS["ko"]["title_fit"] in out


def test_fit_cli_lang_ko_grader_prompt_contains_korean(capsys, tmp_path):
    """fit CLI --lang ko: grader_runner receives a prompt containing 'Korean'."""
    from fit.cli import run

    grader_runner, grader_prompts = _capturing_grader_runner()
    jd_path = _make_jd_file(tmp_path, _ENGLISH_JD)
    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/o/repo",
            "--author",
            "alice",
            "--jd",
            jd_path,
            "--lang",
            "ko",
        ],
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=grader_runner,
    )
    capsys.readouterr()
    assert code == 0
    assert any(language_name("ko") in p for p in grader_prompts), (
        "grader_runner prompt should contain 'Korean' when lang='ko'"
    )


def test_fit_cli_korean_jd_autodetect_ko(capsys, tmp_path):
    """fit CLI with no --lang and a Korean JD auto-detects 'ko'."""
    from fit.cli import run

    grader_runner, _ = _capturing_grader_runner()
    jd_path = _make_jd_file(tmp_path, _KOREAN_JD)
    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/o/repo",
            "--author",
            "alice",
            "--jd",
            jd_path,
        ],
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=grader_runner,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert LANGS["ko"]["title_fit"] in out


def test_fit_cli_english_jd_autodetect_en(capsys, tmp_path):
    """fit CLI with no --lang and an English JD auto-detects 'en'."""
    from fit.cli import run

    grader_runner, _ = _capturing_grader_runner()
    jd_path = _make_jd_file(tmp_path, _ENGLISH_JD)
    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/o/repo",
            "--author",
            "alice",
            "--jd",
            jd_path,
        ],
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=grader_runner,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert LANGS["en"]["title_fit"] in out


def test_fit_cli_explicit_lang_wins_over_jd_detection(capsys, tmp_path):
    """fit CLI: explicit --lang ko with an English JD wins over JD detection."""
    from fit.cli import run

    grader_runner, _ = _capturing_grader_runner()
    jd_path = _make_jd_file(tmp_path, _ENGLISH_JD)
    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/o/repo",
            "--author",
            "alice",
            "--jd",
            jd_path,
            "--lang",
            "ko",
        ],
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=grader_runner,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert LANGS["ko"]["title_fit"] in out


# ---------------------------------------------------------------------------
# rating CLI: --lang ko threads to renderer + grader prompt, defaults to en
# ---------------------------------------------------------------------------


def test_rating_cli_lang_ko_renderer_uses_korean_title(capsys):
    """rating CLI --lang ko: rendered output contains Korean title_rating."""
    from rating.cli import run

    grader_runner, _ = _capturing_grader_runner()
    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/o/repo",
            "--author",
            "alice",
            "--lang",
            "ko",
        ],
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=grader_runner,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert LANGS["ko"]["title_rating"] in out


def test_rating_cli_lang_ko_grader_prompt_contains_korean(capsys):
    """rating CLI --lang ko: grader_runner receives a prompt containing 'Korean'."""
    from rating.cli import run

    grader_runner, grader_prompts = _capturing_grader_runner()
    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/o/repo",
            "--author",
            "alice",
            "--lang",
            "ko",
        ],
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=grader_runner,
    )
    capsys.readouterr()
    assert code == 0
    assert any(language_name("ko") in p for p in grader_prompts), (
        "grader_runner prompt should contain 'Korean' when lang='ko'"
    )


def test_rating_cli_default_lang_en(capsys):
    """rating CLI with no --lang uses en by default (English title in output)."""
    from rating.cli import run

    grader_runner, _ = _capturing_grader_runner()
    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/o/repo",
            "--author",
            "alice",
        ],
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=grader_runner,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert LANGS["en"]["title_rating"] in out


# ---------------------------------------------------------------------------
# reference_check CLI: --lang ko threads to renderer + letter prompt
# ---------------------------------------------------------------------------


def test_reference_check_cli_lang_ko_renderer_uses_korean_title(capsys):
    """reference_check CLI --lang ko: rendered output contains Korean title_letter or insufficient notice."""
    from reference_check.cli import run

    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/o/repo",
            "--author",
            "alice",
            "--lang",
            "ko",
        ],
        extractor=_fake_extractor,
        runner=_fake_runner,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert LANGS["ko"]["title_letter"] in out


def test_reference_check_cli_default_lang_en(capsys):
    """reference_check CLI with no --lang uses en by default."""
    from reference_check.cli import run

    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/o/repo",
            "--author",
            "alice",
        ],
        extractor=_fake_extractor,
        runner=_fake_runner,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert LANGS["en"]["title_letter"] in out


# ---------------------------------------------------------------------------
# Grounding / show_refs / mask behaviour unchanged between lang="en" and lang="ko"
# ---------------------------------------------------------------------------


def test_grounding_identical_across_langs():
    """Grounding gate produces identical results for lang='en' and lang='ko' on the same fixture.

    The same number of grounded vs rejected claims must be reported for both langs.
    """
    from portfolio.pipeline import build_from_evidence

    evidence = [
        Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="feat"),
    ]

    def runner_good(prompt: str) -> str:
        return json.dumps(
            [
                {"text": "Built the thing", "evidence_refs": ["PR#1"], "confidence": 0.9},
                {"text": "Invented something", "evidence_refs": ["PR#HALLUCINATED"], "confidence": 0.7},
            ]
        )

    result_en = build_from_evidence("alice", evidence, runner_good, max_claims=12, lang="en")
    result_ko = build_from_evidence("alice", evidence, runner_good, max_claims=12, lang="ko")

    assert len(result_en.grounding.grounded) == len(result_ko.grounding.grounded)
    assert len(result_en.grounding.rejected) == len(result_ko.grounding.rejected)


def test_show_refs_tokens_identical_across_langs():
    """When show_refs=True, ref tokens appear unchanged in both en and ko renders."""
    from portfolio.render import render_markdown

    evidence = [Evidence(kind="pr", ref="owner/repo#42", url="https://github.com/owner/repo/pull/42", detail="feat")]
    claim = Claim(text="Built thing", evidence_refs=["owner/repo#42"], confidence=0.9, grounded=True)
    portfolio = Portfolio(subject="alice", evidence=evidence, claims=[claim])

    out_en = render_markdown(portfolio, show_refs=True, lang="en")
    out_ko = render_markdown(portfolio, show_refs=True, lang="ko")

    # The ref token must appear identically in both renders (escaped but recognisable)
    assert "owner/repo\\#42" in out_en
    assert "owner/repo\\#42" in out_ko


def test_render_en_default_keeps_existing_strings():
    """lang='en' (default) keeps the existing English output byte-for-byte unchanged.

    Specifically: the title must be the English value from LANGS['en'].
    """
    from portfolio.render import render_markdown

    portfolio = Portfolio(subject="alice", evidence=[], claims=[])
    out = render_markdown(portfolio, lang="en")
    assert out.startswith(f"# {LANGS['en']['title_portfolio']} —")


def test_render_ko_uses_korean_strings():
    """lang='ko' must produce Korean UI strings, not English ones."""
    from portfolio.render import render_markdown

    portfolio = Portfolio(subject="alice", evidence=[], claims=[])
    out_ko = render_markdown(portfolio, lang="ko")
    assert LANGS["ko"]["title_portfolio"] in out_ko
    # English title must NOT be in the ko output (since they differ)
    assert LANGS["en"]["title_portfolio"] != LANGS["ko"]["title_portfolio"]
    assert LANGS["en"]["title_portfolio"] not in out_ko
