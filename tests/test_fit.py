"""Tests for the /fit command: grounded JD match with deterministic grade + bounded score.

Each test traces to a Done-when item in outcome.md via its docstring.
All tests inject fake extractor, runner, fetcher, grader_runner — no live gh/claude/network.
"""

from __future__ import annotations

import inspect
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.model import Claim, Evidence, Portfolio  # noqa: E402
from fit.score import (  # noqa: E402
    COVERAGE_CUTOFFS,
    GRADE_BANDS,
    score_fit,
)
from fit.grade import bounded_grade  # noqa: E402
from fit.cli import run  # noqa: E402


# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------


def _make_portfolio(
    refs: list[str] | None = None,
    claim_text: str = "Built a python backend service",
    subject: str = "alice",
) -> Portfolio:
    """Minimal portfolio with one Evidence and one grounded Claim."""
    if refs is None:
        refs = ["PR#1"]
    evidence = [Evidence(kind="pr", ref=r, url=f"https://example.com/{r}", detail=r) for r in refs]
    claim = Claim(text=claim_text, evidence_refs=refs, confidence=0.9, grounded=True)
    return Portfolio(subject=subject, evidence=evidence, claims=[claim])


def _make_jd(tmp_path: Path, text: str = "python backend engineer") -> str:
    """Write a JD file and return its path as a string."""
    p = tmp_path / "jd.txt"
    p.write_text(text, encoding="utf-8")
    return str(p)


def _fake_extractor(*, repo: str, author: str) -> list[Evidence]:
    """Returns canned Evidence for a github source; no network."""
    return [Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="Add feature")]


def _fake_runner(prompt: str) -> str:
    """Returns one grounded claim citing PR#1."""
    return json.dumps([{"text": "Built a python backend service", "evidence_refs": ["PR#1"], "confidence": 0.9}])


def _make_grader_runner(score: int = 80, reasoning: list | None = None) -> object:
    """Returns a fake grader_runner that returns valid JSON with the given score."""
    if reasoning is None:
        reasoning = [{"text": "solid match", "evidence_refs": ["PR#1"]}]

    def grader(prompt: str, *, temperature: float = 0) -> str:
        return json.dumps({"score": score, "reasoning": reasoning})

    return grader


def _base_argv(jd_path: str, out: str | None = None) -> list[str]:
    argv = [
        "--source-type",
        "github",
        "--source",
        "https://github.com/owner/repo",
        "--author",
        "alice",
        "--jd",
        jd_path,
    ]
    if out is not None:
        argv += ["--out", out]
    return argv


# ---------------------------------------------------------------------------
# Done-when: importable COVERAGE_CUTOFFS and GRADE_BANDS constants
# ---------------------------------------------------------------------------


def test_coverage_cutoffs_match_rubric():
    """'fit/score.py pins the coverage%→grade cutoffs exactly as: ≥90→S, ≥75→A,
    ≥55→B, ≥35→C, else D. Both tables are importable constants so tests can
    assert them directly.'"""
    assert COVERAGE_CUTOFFS["S"] == 90
    assert COVERAGE_CUTOFFS["A"] == 75
    assert COVERAGE_CUTOFFS["B"] == 55
    assert COVERAGE_CUTOFFS["C"] == 35


def test_grade_bands_match_rubric():
    """'The grade→band table is pinned exactly as: S=96..100, A=85..95, B=70..84,
    C=55..69, D=0..54.'"""
    assert GRADE_BANDS["S"] == (96, 100)
    assert GRADE_BANDS["A"] == (85, 95)
    assert GRADE_BANDS["B"] == (70, 84)
    assert GRADE_BANDS["C"] == (55, 69)
    assert GRADE_BANDS["D"] == (0, 54)


# ---------------------------------------------------------------------------
# Done-when: score_fit is a pure deterministic function
# ---------------------------------------------------------------------------


def test_score_fit_deterministic():
    """'Same grounded Portfolio + same JD text → identical grade and identical
    [min,max] band across repeated calls (deterministic; pinned in tests).'"""
    portfolio = _make_portfolio()
    jd_text = "python backend engineer"
    r1 = score_fit(portfolio, jd_text)
    r2 = score_fit(portfolio, jd_text)
    assert r1.grade == r2.grade
    assert r1.band == r2.band
    assert r1.coverage_pct == r2.coverage_pct


def test_score_fit_returns_grade_and_band():
    """'score_fit returns a result object containing at minimum: coverage%,
    covered keywords, gaps, and a grade in {"S","A","B","C","D"} with its
    [min,max] band.'"""
    portfolio = _make_portfolio()
    jd_text = "python backend engineer"
    result = score_fit(portfolio, jd_text)
    assert result.grade in {"S", "A", "B", "C", "D"}
    assert isinstance(result.band, tuple) and len(result.band) == 2
    assert isinstance(result.coverage_pct, (int, float))
    assert isinstance(result.covered, dict)
    assert isinstance(result.gaps, set)


# ---------------------------------------------------------------------------
# Done-when: hallucinated evidence_refs ignored in coverage
# ---------------------------------------------------------------------------


def test_hallucinated_ref_ignored_in_coverage():
    """'A claim whose evidence_refs ⊄ portfolio evidence (hallucinated ref) is
    ignored by the coverage computation — its tokens do not count as covered.'"""
    # Portfolio has PR#1 in evidence, but the claim cites PR#999 (not in evidence)
    evidence = [Evidence(kind="pr", ref="PR#1", url="", detail="real")]
    hallucinated_claim = Claim(
        text="python backend",
        evidence_refs=["PR#999"],  # not in evidence
        confidence=0.9,
        grounded=True,
    )
    portfolio = Portfolio(subject="alice", evidence=evidence, claims=[hallucinated_claim])
    result = score_fit(portfolio, "python backend engineer")
    # The hallucinated claim should not contribute to coverage
    # (no valid grounded claim covers these keywords)
    assert result.coverage_pct == 0 or len(result.covered) == 0


def test_valid_ref_covers_jd_keywords():
    """'A claim with non-empty real refs does cover overlapping JD keywords, and
    the covered-keyword record cites the real evidence ref(s).'"""
    portfolio = _make_portfolio(refs=["PR#1"], claim_text="python backend service")
    result = score_fit(portfolio, "python backend engineer")
    # "python" and "backend" should be covered
    assert "python" in result.covered or "backend" in result.covered
    # Each covered keyword must cite a ref that is in the portfolio's evidence
    real_refs = {e.ref for e in portfolio.evidence}
    for kw, refs in result.covered.items():
        for ref in refs:
            assert ref in real_refs


def test_empty_evidence_refs_ignored():
    """'A claim contributes to coverage only if its evidence_refs are non-empty
    AND ⊆ the portfolio's evidence ref set.'"""
    evidence = [Evidence(kind="pr", ref="PR#1", url="", detail="")]
    empty_refs_claim = Claim(text="python backend", evidence_refs=[], confidence=0.9)
    portfolio = Portfolio(subject="alice", evidence=evidence, claims=[empty_refs_claim])
    result = score_fit(portfolio, "python backend")
    assert result.coverage_pct == 0


# ---------------------------------------------------------------------------
# Done-when: grade cutoff thresholds
# ---------------------------------------------------------------------------


def test_grade_s_at_90_pct():
    """Coverage ≥90% → grade S."""
    # Build a portfolio that covers most of the JD tokens
    # JD: "python" → 1 keyword. Portfolio claim covers "python" → 100% → S
    evidence = [Evidence(kind="pr", ref="PR#1", url="", detail="")]
    claim = Claim(text="python", evidence_refs=["PR#1"], confidence=0.9)
    portfolio = Portfolio(subject="alice", evidence=evidence, claims=[claim])
    result = score_fit(portfolio, "python")
    assert result.grade == "S"


def test_grade_d_at_zero_coverage():
    """0% coverage → grade D."""
    evidence = [Evidence(kind="pr", ref="PR#1", url="", detail="")]
    claim = Claim(text="python backend", evidence_refs=["PR#1"], confidence=0.9)
    portfolio = Portfolio(subject="alice", evidence=evidence, claims=[claim])
    # JD has no overlap with claim tokens
    result = score_fit(portfolio, "java spring hibernate")
    assert result.grade == "D"


# ---------------------------------------------------------------------------
# Done-when: bounded_grade clamps score to band
# ---------------------------------------------------------------------------


def test_bounded_grade_clamps_above():
    """'A grader_runner returning a score above the band yields a final score
    equal to the band's max.'"""
    portfolio = _make_portfolio()
    grade = "B"
    band = GRADE_BANDS[grade]  # (70, 84)
    # Runner returns 99 (above band max 84)
    runner = _make_grader_runner(score=99)
    result = bounded_grade(portfolio, grade, band, runner)
    assert result.score == band[1]


def test_bounded_grade_clamps_below():
    """'A grader_runner returning a score below the band yields a final score
    equal to the band's min.'"""
    portfolio = _make_portfolio()
    grade = "A"
    band = GRADE_BANDS[grade]  # (85, 95)
    runner = _make_grader_runner(score=10)
    result = bounded_grade(portfolio, grade, band, runner)
    assert result.score == band[0]


def test_bounded_grade_within_band_passes_through():
    """Score inside the band is returned as-is."""
    portfolio = _make_portfolio()
    grade = "B"
    band = GRADE_BANDS[grade]  # (70, 84)
    runner = _make_grader_runner(score=77)
    result = bounded_grade(portfolio, grade, band, runner)
    assert result.score == 77


def test_bounded_grade_malformed_json_yields_midpoint():
    """'A grader_runner returning malformed JSON / non-JSON / a missing or
    non-integer score yields a clamped score (the band's midpoint, computed as
    (min + max) // 2) and an empty reasoning list — no crash, no fabricated
    reasoning bullet, no fabricated ref.'"""
    portfolio = _make_portfolio()
    grade = "C"
    band = GRADE_BANDS[grade]  # (55, 69)

    def bad_runner(prompt: str, *, temperature: float = 0) -> str:
        return "this is not json at all"

    result = bounded_grade(portfolio, grade, band, bad_runner)
    assert result.score == (band[0] + band[1]) // 2
    assert result.reasoning == []


def test_bounded_grade_missing_score_yields_midpoint():
    """Missing score field in otherwise valid JSON → midpoint + empty reasoning."""
    portfolio = _make_portfolio()
    grade = "B"
    band = GRADE_BANDS[grade]

    def runner_no_score(prompt: str, *, temperature: float = 0) -> str:
        return json.dumps({"reasoning": [{"text": "ok", "evidence_refs": ["PR#1"]}]})

    result = bounded_grade(portfolio, grade, band, runner_no_score)
    assert result.score == (band[0] + band[1]) // 2
    assert result.reasoning == []


# ---------------------------------------------------------------------------
# Done-when: grader_runner always called with temperature=0
# ---------------------------------------------------------------------------


def test_bounded_grade_calls_grader_runner_with_temperature_zero():
    """'The bounded grader always calls the grader_runner with temperature=0 passed
    as a keyword argument (asserted by a fake runner that records the temperature
    value it received).'"""
    portfolio = _make_portfolio()
    grade = "B"
    band = GRADE_BANDS[grade]

    received: list[dict] = []

    def recording_runner(prompt: str, *, temperature: float = 0) -> str:
        received.append({"prompt": prompt, "temperature": temperature})
        return json.dumps({"score": 77, "reasoning": [{"text": "ok", "evidence_refs": ["PR#1"]}]})

    bounded_grade(portfolio, grade, band, recording_runner)
    assert len(received) == 1
    assert received[0]["temperature"] == 0


# ---------------------------------------------------------------------------
# Done-when: grader_runner called exactly once with byte-identical prompt
# ---------------------------------------------------------------------------


def test_bounded_grade_fixed_prompt_identical_across_calls():
    """'For the same (portfolio, jd_text) input, the grader_runner is called
    exactly once and with byte-identical prompt text across repeated calls.'"""
    portfolio = _make_portfolio()
    grade = "B"
    band = GRADE_BANDS[grade]

    prompts: list[str] = []

    def recording_runner(prompt: str, *, temperature: float = 0) -> str:
        prompts.append(prompt)
        return json.dumps({"score": 77, "reasoning": [{"text": "ok", "evidence_refs": ["PR#1"]}]})

    bounded_grade(portfolio, grade, band, recording_runner)
    bounded_grade(portfolio, grade, band, recording_runner)
    assert len(prompts) == 2
    assert prompts[0] == prompts[1], "prompt must be byte-identical across repeated calls"


# ---------------------------------------------------------------------------
# Done-when: reasoning bullet with non-evidence ref dropped
# ---------------------------------------------------------------------------


def test_bounded_grade_drops_bullet_with_hallucinated_ref():
    """'A reasoning bullet citing a ref not present in portfolio.evidence is
    dropped before render and never appears in the reasoning list.'"""
    portfolio = _make_portfolio(refs=["PR#1"])

    def runner_with_bad_ref(prompt: str, *, temperature: float = 0) -> str:
        return json.dumps(
            {
                "score": 77,
                "reasoning": [
                    {"text": "real bullet", "evidence_refs": ["PR#1"]},
                    {"text": "hallucinated bullet", "evidence_refs": ["PR#999"]},
                ],
            }
        )

    result = bounded_grade(portfolio, "B", GRADE_BANDS["B"], runner_with_bad_ref)
    texts = [b["text"] for b in result.reasoning]
    assert "real bullet" in texts
    assert "hallucinated bullet" not in texts


# ---------------------------------------------------------------------------
# Done-when: end-to-end run — grounding summary on stderr, not stdout
# ---------------------------------------------------------------------------


def test_grounding_summary_on_stderr_not_stdout(tmp_path, capsys):
    """'An end-to-end run(…) with fake extractor, runner, and grader_runner writes
    Markdown to stdout (no --out) and writes the one-line grounding summary only
    to stderr — stderr text never appears in stdout.'"""
    jd_path = _make_jd(tmp_path, "python backend engineer")
    grader = _make_grader_runner(score=77)

    code = run(
        _base_argv(jd_path),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=grader,
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "grounded:" in captured.err
    assert "grounded:" not in captured.out


def test_stdout_contains_markdown_not_grounding_summary(tmp_path, capsys):
    """'stdout contains Markdown output; the grounding-summary line is absent from stdout.'"""
    jd_path = _make_jd(tmp_path, "python backend engineer")
    grader = _make_grader_runner(score=77)

    code = run(
        _base_argv(jd_path),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=grader,
    )
    captured = capsys.readouterr()
    assert code == 0
    # Markdown output present
    assert "#" in captured.out
    # Grounding summary absent from stdout
    assert "needs-confirmation:" not in captured.out


# ---------------------------------------------------------------------------
# Done-when: --out writes to file, stdout is empty
# ---------------------------------------------------------------------------


def test_out_writes_file_stdout_empty(tmp_path, capsys):
    """'With --out <path>, the Markdown is written to <path> and stdout is empty;
    stderr still carries the grounding-summary line.'"""
    jd_path = _make_jd(tmp_path, "python backend engineer")
    out_path = tmp_path / "fit.md"
    grader = _make_grader_runner(score=77)

    code = run(
        _base_argv(jd_path, out=str(out_path)),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=grader,
    )
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.strip() == ""
    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    assert "#" in content
    assert "grounded:" in captured.err


# ---------------------------------------------------------------------------
# Done-when: unknown --source-type exits non-zero, extractor never called
# ---------------------------------------------------------------------------


def test_unknown_source_type_exits_nonzero(tmp_path, capsys):
    """'An unsupported / unknown --source-type exits non-zero and the injected
    extractor is never called.'"""
    jd_path = _make_jd(tmp_path, "python backend")
    calls: list = []

    def counting_extractor(**kwargs) -> list[Evidence]:
        calls.append(kwargs)
        return []

    code = run(
        ["--source-type", "unknown_type", "--source", "https://github.com/o/r", "--author", "alice", "--jd", jd_path],
        extractor=counting_extractor,
        runner=_fake_runner,
        grader_runner=_make_grader_runner(),
    )
    assert code != 0
    assert calls == []


# ---------------------------------------------------------------------------
# Done-when: bad source URL exits non-zero, extractor never called
# ---------------------------------------------------------------------------


def test_bad_source_url_exits_nonzero(tmp_path, capsys):
    """'A bad / unparseable --source URL for a recognized --source-type exits
    non-zero and the injected extractor is never called.'"""
    jd_path = _make_jd(tmp_path, "python backend")
    calls: list = []

    def counting_extractor(**kwargs) -> list[Evidence]:
        calls.append(kwargs)
        return []

    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://gitlab.com/owner/repo",
            "--author",
            "alice",
            "--jd",
            jd_path,
        ],
        extractor=counting_extractor,
        runner=_fake_runner,
        grader_runner=_make_grader_runner(),
    )
    assert code != 0
    assert calls == []


# ---------------------------------------------------------------------------
# Done-when: missing --jd exits non-zero with stderr message, extractor not called
# ---------------------------------------------------------------------------


def test_missing_jd_exits_nonzero(tmp_path, capsys):
    """'A missing --jd file path exits non-zero with a clear stderr message and
    the injected extractor is never called.'"""
    calls: list = []

    def counting_extractor(**kwargs) -> list[Evidence]:
        calls.append(kwargs)
        return []

    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/owner/repo",
            "--author",
            "alice",
            "--jd",
            "/nonexistent/path/jd.txt",
        ],
        extractor=counting_extractor,
        runner=_fake_runner,
        grader_runner=_make_grader_runner(),
    )
    captured = capsys.readouterr()
    assert code != 0
    assert captured.err.strip() != ""
    assert calls == []


# ---------------------------------------------------------------------------
# Done-when: run() has keyword-only injectable seams with defaults
# ---------------------------------------------------------------------------


def test_run_has_injectable_seams():
    """'fit/cli.py run has keyword-only injectable seams extractor, runner,
    fetcher, grader_runner with defaults (signature inspection).'"""
    sig = inspect.signature(run)
    params = sig.parameters
    for name in ("extractor", "runner", "fetcher", "grader_runner"):
        assert name in params, f"run() missing keyword-only param: {name}"
        assert params[name].kind == inspect.Parameter.KEYWORD_ONLY, f"{name} must be keyword-only"
        assert params[name].default is not inspect.Parameter.empty, f"{name} must have a default"


# ---------------------------------------------------------------------------
# Done-when: fit/__main__.py calls fit.cli.main()
# ---------------------------------------------------------------------------


def test_main_module_calls_cli_main():
    """'fit/__main__.py calls fit.cli.main() under if __name__ == "__main__".'"""
    main_path = Path(__file__).resolve().parents[1] / "fit" / "__main__.py"
    assert main_path.exists(), "fit/__main__.py must exist"
    content = main_path.read_text(encoding="utf-8")
    assert "fit.cli" in content or "from fit.cli import" in content or "from .cli import" in content
    assert "main()" in content
    assert '__name__ == "__main__"' in content or "__name__ == '__main__'" in content


# ---------------------------------------------------------------------------
# Done-when: .claude/commands/fit.md exists with hard-rule clause
# ---------------------------------------------------------------------------


def test_fit_slash_command_content():
    """'.claude/commands/fit.md exists, references python -m fit as the only
    invocation, and contains the hard-rule clause forbidding shell string
    assembly / command substitution / $ARGUMENTS single-string interpolation.'"""
    commands_dir = Path(__file__).resolve().parents[1] / ".claude" / "commands"
    fit_md = commands_dir / "fit.md"
    assert fit_md.exists(), ".claude/commands/fit.md must exist"

    content = fit_md.read_text(encoding="utf-8")

    # Must invoke python -m fit
    assert "python -m fit" in content

    # Must reference the key argv tokens
    assert "--source-type" in content
    assert "--source" in content
    assert "--author" in content
    assert "--jd" in content

    # Must not use $() shell substitution
    assert "$(" not in content

    # Must have hard-rule clause forbidding shell string assembly
    lower = content.lower()
    assert "shell string" in lower or "never assemble" in lower


# ---------------------------------------------------------------------------
# Done-when: python -m fit --help exits 0 and lists required flags
# ---------------------------------------------------------------------------


def test_help_exits_zero(capsys):
    """'python -m fit --help exits 0 and lists --source-type, --source, --author,
    --jd, and --out.'"""
    try:
        run(["--help"], extractor=_fake_extractor, runner=_fake_runner, grader_runner=_make_grader_runner())
    except SystemExit as exc:
        assert exc.code == 0
    captured = capsys.readouterr()
    help_text = captured.out + captured.err
    for flag in ("--source-type", "--source", "--author", "--jd", "--out"):
        assert flag in help_text, f"--help output missing {flag}"


# ---------------------------------------------------------------------------
# Done-when: --jd URL path — article text becomes JD, exit 0
# ---------------------------------------------------------------------------


def test_jd_url_fetches_and_uses_article_text_as_jd(tmp_path, capsys, monkeypatch):
    """'--jd https://example.com/job with a fake fetcher returning canned HTML
    exits 0; the article body becomes the JD text used downstream.'"""
    _JD_KEYWORD = "UNIQUEKEYWORD_FIT"

    def jd_fetcher(url: str) -> str:
        return f"<html><head><title>Fit Job</title></head><body>{_JD_KEYWORD} backend engineer.</body></html>"

    def keyword_runner(prompt: str) -> str:
        text = f"Built {_JD_KEYWORD} system" if _JD_KEYWORD in prompt else "Built generic system"
        return json.dumps([{"text": text, "evidence_refs": ["PR#1"], "confidence": 0.9}])

    grader = _make_grader_runner(score=77)

    # IR-002: JD drives scoring via score_fit(portfolio, jd_text), NOT the narrate
    # prompt. Spy that call to prove the FETCHED article text actually became the
    # JD scored downstream (if load_jd were ignored, jd_text would not contain the
    # keyword from the fetched page).
    captured: dict[str, str] = {}
    import fit.cli as _fit_cli

    _real_score = _fit_cli.score_fit

    def _spy_score(portfolio, jd_text):
        captured["jd_text"] = jd_text
        return _real_score(portfolio, jd_text)

    monkeypatch.setattr(_fit_cli, "score_fit", _spy_score)

    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/owner/repo",
            "--author",
            "alice",
            "--jd",
            "https://jobs.example.com/fit-eng",
        ],
        extractor=_fake_extractor,
        runner=keyword_runner,
        fetcher=jd_fetcher,
        grader_runner=grader,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "#" in out
    assert _JD_KEYWORD in captured["jd_text"], "fetched JD must reach score_fit downstream"


# ---------------------------------------------------------------------------
# Done-when: --jd with SSRF-rejected URL exits 2, stderr has "invalid --jd URL"
# ---------------------------------------------------------------------------


def test_jd_ssrf_url_exits_2_with_clear_message(tmp_path, capsys):
    """'--jd http://localhost/jd → exit 2; stderr contains a clear "invalid --jd
    URL" message; no traceback; no fit body on stdout; extractor is not invoked.'"""
    extractor_calls: list = []

    def counting_extractor(**kwargs):
        extractor_calls.append(kwargs)
        return []

    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/owner/repo",
            "--author",
            "alice",
            "--jd",
            "http://localhost/jd",
        ],
        extractor=counting_extractor,
        runner=_fake_runner,
        grader_runner=_make_grader_runner(),
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "invalid --jd url" in captured.err.lower()
    assert "Traceback" not in captured.err
    assert extractor_calls == []


# ---------------------------------------------------------------------------
# Done-when: --jd URL with failing fetcher exits 2, stderr has failure message
# ---------------------------------------------------------------------------


def test_jd_url_fetcher_failure_exits_2_with_message(tmp_path, capsys):
    """'--jd <url> with a fetcher that raises RuntimeError → exit 2; stderr
    contains a clear failure message identifying the URL; no traceback; no
    fit body on stdout.'"""

    def failing_fetcher(url: str) -> str:
        raise RuntimeError("timeout")

    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/owner/repo",
            "--author",
            "alice",
            "--jd",
            "https://jobs.example.com/fit-eng",
        ],
        extractor=_fake_extractor,
        runner=_fake_runner,
        fetcher=failing_fetcher,
        grader_runner=_make_grader_runner(),
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "failed to fetch --jd url" in captured.err.lower()
    assert "Traceback" not in captured.err


# ---------------------------------------------------------------------------
# Done-when: .claude/commands/fit.md documents --jd accepts URL or path
# ---------------------------------------------------------------------------


def test_fit_slash_command_documents_jd_url():
    """'.claude/commands/fit.md describes --jd as accepting a filesystem path
    OR an http(s) URL, and any prior "filesystem path only" wording is gone.'"""
    commands_dir = Path(__file__).resolve().parents[1] / ".claude" / "commands"
    fit_md = commands_dir / "fit.md"
    assert fit_md.exists()
    content = fit_md.read_text(encoding="utf-8")
    lower = content.lower()
    assert "url" in lower and "--jd" in lower
    assert "filesystem path only" not in lower


# ---------------------------------------------------------------------------
# Done-when: README.md documents --jd accepts URL or path for both commands
# ---------------------------------------------------------------------------


def test_readme_documents_jd_url_for_resume_and_fit():
    """'README.md documents that --jd accepts a filesystem path or an http(s) URL
    for both python -m resume and python -m fit.'"""
    readme = Path(__file__).resolve().parents[1] / "README.md"
    assert readme.exists()
    content = readme.read_text(encoding="utf-8")
    # IR-003: "url" alone is too weak (the pre-change README already had
    # "--source <url>"), and counting global occurrences could pass with the
    # http(s) wording present in only one command's section. Split into the
    # per-command "###" sections and require EACH of resume and fit to document
    # --jd accepting an http(s) URL independently.
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in content.splitlines():
        m = re.match(r"^###\s+`?/?([\w-]+)", line)
        if m:
            current = m.group(1).lower()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)

    for cmd in ("resume", "fit"):
        assert cmd in sections, f"README must have a /{cmd} section"
        body = "\n".join(sections[cmd]).lower()
        assert "--jd" in body, f"/{cmd} section must mention --jd"
        assert ("http(s)" in body) or ("https url" in body) or ("url to a job" in body), (
            f"/{cmd} section must document --jd accepting an http(s) URL"
        )
