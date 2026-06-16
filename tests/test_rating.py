"""Tests for the rating package (python -m rating).

All tests inject fake extractor / runner / fetcher / grader_runner seams —
no live gh / claude / network calls.  Portfolio, Claim, and Evidence objects
are built directly.

Each test traces to a Done-when item in outcome.md via its docstring.
"""

from __future__ import annotations

import builtins
import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.model import Claim, Evidence, Portfolio  # noqa: E402
from rating.cli import run  # noqa: E402
from rating.grade import grade  # noqa: E402
from rating.profile import GRADE_BANDS, profile  # noqa: E402
from rating.render import render_rating  # noqa: E402

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _make_portfolio(subject: str = "alice") -> Portfolio:
    """Standard test portfolio: 3 PRs + 5 distinct file refs (4 languages → Polyglot).

    volume=3 → Low (0 pts)
    breadth=5 → Narrow (0 pts)
    stack_diversity=4 (Python, JavaScript, CSS, SQL) → Polyglot (2 pts)
    total=2 → Grade B → score band 70–84
    """
    evidence = [
        Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="Add feature"),
        Evidence(kind="pr", ref="PR#2", url="https://github.com/o/r/pull/2", detail="Fix bug"),
        Evidence(kind="pr", ref="PR#3", url="https://github.com/o/r/pull/3", detail="Refactor"),
        Evidence(kind="file", ref="app/main.py"),
        Evidence(kind="file", ref="app/utils.py"),
        Evidence(kind="file", ref="web/app.js"),
        Evidence(kind="file", ref="web/style.css"),
        Evidence(kind="file", ref="data/schema.sql"),
    ]
    claims = [
        Claim(text="Built main app feature", evidence_refs=["PR#1"], grounded=True),
        Claim(text="Fixed critical bug", evidence_refs=["PR#2"], grounded=True),
    ]
    return Portfolio(subject=subject, evidence=evidence, claims=claims)


def _fake_extractor(*, repo: str, author: str) -> list[Evidence]:
    """Returns canned Evidence for a github source; no network."""
    return [Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="Add feature")]


def _fake_runner(prompt: str) -> str:
    """Returns one grounded claim citing PR#1."""
    return json.dumps([{"text": "Built the main feature", "evidence_refs": ["PR#1"], "confidence": 0.9}])


def _fake_grader_runner(prompt: str, temperature: int = 0) -> str:
    """Returns a valid grader response within the D band (0–54) for the 1-PR CLI portfolio."""
    return json.dumps({"score": 40, "reasoning": [{"text": "Initial contribution", "evidence_refs": ["PR#1"]}]})


def _make_simple_grader(score: int = 75) -> object:
    """Return a fake grader_runner that returns the given score with a grounded bullet."""

    def grader(prompt: str, temperature: int = 0) -> str:
        return json.dumps({"score": score, "reasoning": [{"text": "Strong work", "evidence_refs": ["PR#1"]}]})

    return grader


# ---------------------------------------------------------------------------
# Done-when: python -m rating exits 0 with all fake seams
# ---------------------------------------------------------------------------


def test_cli_run_exits_zero(capsys):
    """'python -m rating --source-type github --source <url> --author <handle> exits 0
    against fake extractor / runner / fetcher / grader_runner seams (no live calls).'"""
    code = run(
        ["--source-type", "github", "--source", "https://github.com/o/r", "--author", "alice"],
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
    )
    assert code == 0


# ---------------------------------------------------------------------------
# Done-when: profiler is pure (no subprocess/open/network)
# ---------------------------------------------------------------------------


def test_profiler_no_subprocess_or_open(monkeypatch):
    """'rating/profile.py makes no subprocess/open/network call — asserted by a test
    that monkey-patches these to raise.'"""

    def _raise_subprocess(*args, **kwargs):
        raise RuntimeError("subprocess must not be called from profiler")

    def _raise_open(*args, **kwargs):
        raise RuntimeError("open must not be called from profiler")

    monkeypatch.setattr(subprocess, "run", _raise_subprocess)
    monkeypatch.setattr(builtins, "open", _raise_open)

    portfolio = _make_portfolio()
    result = profile(portfolio)
    assert result.grade in GRADE_BANDS


# ---------------------------------------------------------------------------
# Done-when: deterministic grade
# ---------------------------------------------------------------------------


def test_deterministic_grade():
    """'Same Portfolio input → identical metrics, bands, grade, and (min,max) across
    repeated calls (deterministic-grade test).'"""
    portfolio = _make_portfolio()
    r1 = profile(portfolio)
    r2 = profile(portfolio)

    assert r1.grade == r2.grade
    assert r1.score_min == r2.score_min
    assert r1.score_max == r2.score_max
    assert r1.dimensions.keys() == r2.dimensions.keys()
    for k in r1.dimensions:
        d1, d2 = r1.dimensions[k], r2.dimensions[k]
        assert d1.value == d2.value
        assert d1.band == d2.band
        assert d1.points == d2.points
        assert d1.evidence_refs == d2.evidence_refs


# ---------------------------------------------------------------------------
# Done-when: metric correctness
# ---------------------------------------------------------------------------


def test_metric_volume_equals_pr_count():
    """'volume == count of Evidence(kind="pr").'"""
    portfolio = _make_portfolio()
    result = profile(portfolio)
    expected_volume = sum(1 for e in portfolio.evidence if e.kind == "pr")
    assert result.dimensions["volume"].value == expected_volume


def test_metric_breadth_equals_distinct_file_refs():
    """'breadth == count of distinct Evidence(kind="file") refs.'"""
    portfolio = _make_portfolio()
    result = profile(portfolio)
    expected_breadth = len({e.ref for e in portfolio.evidence if e.kind == "file"})
    assert result.dimensions["breadth"].value == expected_breadth


def test_metric_stack_diversity_uses_pinned_table():
    """'stack diversity == count of distinct languages derived from the fixed
    extension→language table pinned in rating/profile.py.'"""
    # Portfolio with known extensions: .py (Python), .js (JavaScript), .go (Go)
    evidence = [
        Evidence(kind="file", ref="main.py"),
        Evidence(kind="file", ref="server.go"),
        Evidence(kind="file", ref="client.js"),
    ]
    portfolio = Portfolio(subject="bob", evidence=evidence, claims=[])
    result = profile(portfolio)
    # Three distinct languages: Python, Go, JavaScript
    assert result.dimensions["stack_diversity"].value == 3


def test_unknown_extension_maps_to_other_never_guessed():
    """'an unknown extension maps to the literal string "other" (never guessed by a model).'"""
    from rating.profile import _EXT_TO_LANG

    # .xyz is not in the table
    assert ".xyz" not in _EXT_TO_LANG
    # A portfolio with only unknown-extension files
    evidence = [
        Evidence(kind="file", ref="archive.xyz"),
        Evidence(kind="file", ref="data.foobar"),
    ]
    portfolio = Portfolio(subject="carol", evidence=evidence, claims=[])
    result = profile(portfolio)
    # Both map to "other" → 1 distinct language ("other")
    assert result.dimensions["stack_diversity"].value == 1


# ---------------------------------------------------------------------------
# Done-when: evidence_refs are a subset of portfolio.evidence refs
# ---------------------------------------------------------------------------


def test_evidence_refs_are_subset_of_portfolio():
    """'Each metric returned by the profiler cites the exact evidence_refs it was
    computed from (test asserts the refs are a subset of portfolio.evidence refs).'"""
    portfolio = _make_portfolio()
    result = profile(portfolio)
    all_evidence_refs = {e.ref for e in portfolio.evidence}
    for dim in result.dimensions.values():
        assert set(dim.evidence_refs).issubset(all_evidence_refs), (
            f"dimension {dim.name!r} has refs not in portfolio.evidence"
        )


# ---------------------------------------------------------------------------
# Done-when: recency dimension absent
# ---------------------------------------------------------------------------


def test_no_recency_dimension_in_profiler():
    """'Recency dimension is absent from the profiler output.'"""
    portfolio = _make_portfolio()
    result = profile(portfolio)
    assert "recency" not in result.dimensions


def test_no_recency_in_rendered_scorecard():
    """'Recency dimension is absent from the rendered scorecard.'"""
    portfolio = _make_portfolio()
    profile_result = profile(portfolio)
    grade_result = grade(portfolio, profile_result, _make_simple_grader())
    markdown = render_rating(portfolio, profile_result, grade_result)
    assert "recency" not in markdown.lower()


# ---------------------------------------------------------------------------
# Done-when: rubric pinned in code and rendered output
# ---------------------------------------------------------------------------


def test_rubric_pinned_in_code():
    """'The grade → score-band rubric is pinned exactly as:
    S 96–100, A 85–95, B 70–84, C 55–69, D 0–54 (test asserts the table values).'"""
    assert GRADE_BANDS["S"] == (96, 100)
    assert GRADE_BANDS["A"] == (85, 95)
    assert GRADE_BANDS["B"] == (70, 84)
    assert GRADE_BANDS["C"] == (55, 69)
    assert GRADE_BANDS["D"] == (0, 54)


def test_rubric_rendered_in_scorecard():
    """'The grade → score-band rubric is rendered in the scorecard.'"""
    portfolio = _make_portfolio()
    profile_result = profile(portfolio)
    grade_result = grade(portfolio, profile_result, _make_simple_grader())
    markdown = render_rating(portfolio, profile_result, grade_result)

    # Each band endpoint must appear in the rendered Markdown rubric table.
    assert "96" in markdown
    assert "100" in markdown
    assert "85" in markdown
    assert "95" in markdown
    assert "70" in markdown
    assert "84" in markdown
    assert "55" in markdown
    assert "69" in markdown
    assert "54" in markdown


# ---------------------------------------------------------------------------
# Done-when: grader temperature=0 and fixed/deterministic prompt
# ---------------------------------------------------------------------------


def test_grader_called_with_temperature_zero():
    """'rating/grade.py calls the injectable grader_runner with temperature=0.'"""
    calls: list[dict] = []

    def recording_grader(prompt: str, temperature: int = 0) -> str:
        calls.append({"prompt": prompt, "temperature": temperature})
        return json.dumps({"score": 75, "reasoning": [{"text": "Good work", "evidence_refs": ["PR#1"]}]})

    portfolio = _make_portfolio()
    profile_result = profile(portfolio)
    grade(portfolio, profile_result, recording_grader)

    assert len(calls) == 1
    assert calls[0]["temperature"] == 0


def test_grader_prompt_is_fixed():
    """'A fixed prompt — same portfolio input → identical prompt across repeated calls.'"""
    calls: list[dict] = []

    def recording_grader(prompt: str, temperature: int = 0) -> str:
        calls.append({"prompt": prompt, "temperature": temperature})
        return json.dumps({"score": 75, "reasoning": [{"text": "Good work", "evidence_refs": ["PR#1"]}]})

    portfolio = _make_portfolio()
    profile_result = profile(portfolio)
    grade(portfolio, profile_result, recording_grader)
    grade(portfolio, profile_result, recording_grader)

    assert len(calls) == 2
    assert calls[0]["prompt"] == calls[1]["prompt"]


# ---------------------------------------------------------------------------
# Done-when: score clamping
# ---------------------------------------------------------------------------


def test_score_clamping_below_min():
    """'a fake grader_runner returning a score below min yields min.'"""
    portfolio = _make_portfolio()
    profile_result = profile(portfolio)
    assert profile_result.grade == "B"  # band 70–84

    def low_grader(prompt: str, temperature: int = 0) -> str:
        return json.dumps({"score": 50, "reasoning": []})  # below min=70

    grade_result = grade(portfolio, profile_result, low_grader)
    assert grade_result.score == profile_result.score_min  # clamped to 70


def test_score_clamping_above_max():
    """'one returning a score above max yields max.'"""
    portfolio = _make_portfolio()
    profile_result = profile(portfolio)
    assert profile_result.grade == "B"  # band 70–84

    def high_grader(prompt: str, temperature: int = 0) -> str:
        return json.dumps({"score": 95, "reasoning": []})  # above max=84

    grade_result = grade(portfolio, profile_result, high_grader)
    assert grade_result.score == profile_result.score_max  # clamped to 84


def test_score_in_band_unchanged():
    """'one returning a score inside the band yields that score unchanged.'"""
    portfolio = _make_portfolio()
    profile_result = profile(portfolio)
    assert profile_result.grade == "B"  # band 70–84

    def mid_grader(prompt: str, temperature: int = 0) -> str:
        return json.dumps({"score": 77, "reasoning": []})  # within band

    grade_result = grade(portfolio, profile_result, mid_grader)
    assert grade_result.score == 77


# ---------------------------------------------------------------------------
# Done-when: model cannot change the grade
# ---------------------------------------------------------------------------


def test_model_cannot_change_grade():
    """'Regardless of what the fake grader_runner returns, the rendered grade equals
    the deterministic grade computed from the portfolio.'"""
    portfolio = _make_portfolio()
    profile_result = profile(portfolio)
    det_grade = profile_result.grade  # "B"

    def wild_grader(prompt: str, temperature: int = 0) -> str:
        # Tries to force a top grade and a top score
        return json.dumps({"score": 99, "reasoning": [], "grade": "S"})

    grade_result = grade(portfolio, profile_result, wild_grader)
    markdown = render_rating(portfolio, profile_result, grade_result)

    assert grade_result.grade == det_grade
    assert f"Grade: {det_grade}" in markdown


# ---------------------------------------------------------------------------
# Done-when: grounding gate on reasoning
# ---------------------------------------------------------------------------


def test_grounding_gate_drops_ungrounded_reasoning():
    """'Reasoning bullets / highlights whose evidence_refs are not a subset of the
    portfolio's evidence refs are dropped before render.'"""
    portfolio = _make_portfolio()  # evidence contains PR#1, PR#2, PR#3
    profile_result = profile(portfolio)

    def grader_with_bad_ref(prompt: str, temperature: int = 0) -> str:
        return json.dumps(
            {
                "score": 75,
                "reasoning": [
                    {"text": "Good work on PR#1", "evidence_refs": ["PR#1"]},  # grounded ✓
                    {"text": "Invented claim", "evidence_refs": ["PR#999"]},  # not grounded ✗
                ],
            }
        )

    grade_result = grade(portfolio, profile_result, grader_with_bad_ref)

    texts = [b["text"] for b in grade_result.reasoning]
    assert "Good work on PR#1" in texts
    assert "Invented claim" not in texts


# ---------------------------------------------------------------------------
# Done-when: defensive parse of malformed grader response
# ---------------------------------------------------------------------------


def test_defensive_parse_invalid_json():
    """'A malformed grader_runner response (invalid JSON) yields a clamped score at
    the band midpoint and a safe non-empty reasoning section without crashing.'"""
    portfolio = _make_portfolio()
    profile_result = profile(portfolio)
    assert profile_result.grade == "B"
    midpoint = (profile_result.score_min + profile_result.score_max) // 2

    def bad_grader(prompt: str, temperature: int = 0) -> str:
        return "this is not json at all"

    grade_result = grade(portfolio, profile_result, bad_grader)
    assert grade_result.score == midpoint
    assert len(grade_result.reasoning) > 0
    # No fabricated refs — all refs in reasoning must be in portfolio evidence
    evidence_refs = {e.ref for e in portfolio.evidence}
    for bullet in grade_result.reasoning:
        for ref in bullet.get("evidence_refs", []):
            assert ref in evidence_refs, f"fabricated ref {ref!r} in reasoning"


def test_defensive_parse_missing_fields():
    """'A malformed grader_runner response (missing fields) yields midpoint + safe reasoning.'"""
    portfolio = _make_portfolio()
    profile_result = profile(portfolio)
    midpoint = (profile_result.score_min + profile_result.score_max) // 2

    def missing_fields_grader(prompt: str, temperature: int = 0) -> str:
        return json.dumps({"unexpected_key": "unexpected_value"})

    grade_result = grade(portfolio, profile_result, missing_fields_grader)
    assert grade_result.score == midpoint
    assert len(grade_result.reasoning) > 0


# ---------------------------------------------------------------------------
# Done-when: no-percentile lexicon in rendered output
# ---------------------------------------------------------------------------


def test_no_percentile_lexicon_in_rendered_output():
    """'The rendered Markdown body contains NONE of: top , %ile, percentile, rank,
    better than, out of all, globally, talent score (case-insensitive).'"""
    portfolio = _make_portfolio()
    profile_result = profile(portfolio)
    grade_result = grade(portfolio, profile_result, _make_simple_grader())
    markdown = render_rating(portfolio, profile_result, grade_result)

    lower = markdown.lower()
    forbidden = [
        "top ",
        "%ile",
        "percentile",
        "rank",
        "better than",
        "out of all",
        "globally",
        "talent score",
    ]
    for phrase in forbidden:
        assert phrase not in lower, f"forbidden phrase {phrase!r} found in rendered output"


# ---------------------------------------------------------------------------
# Done-when: --out writes to file, stdout contains no rendered body
# ---------------------------------------------------------------------------


def test_out_writes_file_not_stdout(tmp_path, capsys):
    """'--out FILE writes the Markdown to FILE and stdout stays empty for the
    rendered body; the grounding summary still goes to stderr only.'"""
    out_path = tmp_path / "rating.md"
    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/o/r",
            "--author",
            "alice",
            "--out",
            str(out_path),
        ],
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
    )
    assert code == 0
    captured = capsys.readouterr()
    written = out_path.read_text(encoding="utf-8")

    assert "# Capability Rating" in written
    assert "# Capability Rating" not in captured.out  # rendered body not in stdout


# ---------------------------------------------------------------------------
# Done-when: without --out, Markdown on stdout, grounding summary on stderr only
# ---------------------------------------------------------------------------


def test_stderr_grounding_summary_not_in_stdout(capsys):
    """'Without --out, the Markdown is written to stdout and the grounding summary
    (grounded: N  rejected: N  needs-confirmation: N) is written to stderr only.'"""
    code = run(
        ["--source-type", "github", "--source", "https://github.com/o/r", "--author", "alice"],
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
    )
    captured = capsys.readouterr()
    assert code == 0

    err = captured.err.lower()
    assert "grounded:" in err
    assert "rejected:" in err
    assert "needs-confirmation:" in err

    # Grounding summary must NOT appear in stdout
    out = captured.out.lower()
    assert "grounded:" not in out
    assert "rejected:" not in out
    assert "needs-confirmation:" not in out


# ---------------------------------------------------------------------------
# Done-when: input validation — invalid source URL exits non-zero, extractor not called
# ---------------------------------------------------------------------------


def test_invalid_source_url_exits_nonzero(capsys):
    """'An invalid --source URL exits non-zero and does NOT invoke the extractor seam.'"""
    calls: list[dict] = []

    def recording_extractor(**kwargs) -> list[Evidence]:
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
        ],
        extractor=recording_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
    )
    captured = capsys.readouterr()
    assert code != 0
    assert captured.err.strip() != ""
    assert calls == []


def test_unsupported_source_type_exits_nonzero():
    """'An unsupported --source-type exits non-zero and does NOT invoke the extractor seam.'"""
    calls: list[dict] = []

    def recording_extractor(**kwargs) -> list[Evidence]:
        calls.append(kwargs)
        return []

    with pytest.raises(SystemExit) as exc_info:
        run(
            [
                "--source-type",
                "unknown_xyz",
                "--source",
                "https://github.com/o/r",
                "--author",
                "alice",
            ],
            extractor=recording_extractor,
            runner=_fake_runner,
            grader_runner=_fake_grader_runner,
        )
    assert exc_info.value.code != 0
    assert calls == []


# ---------------------------------------------------------------------------
# Done-when: render.py reuses portfolio.render._escape (import path asserted)
# ---------------------------------------------------------------------------


def test_render_imports_escape_from_portfolio():
    """'rating/render.py reuses portfolio.render._escape (import path asserted by test).'"""
    import rating.render as render_mod

    src = inspect.getsource(render_mod)
    assert "from portfolio.render import _escape" in src


# ---------------------------------------------------------------------------
# Done-when: .claude/commands/rating.md shape
# ---------------------------------------------------------------------------


def test_rating_slash_command_shape():
    """'.claude/commands/rating.md exists, passes each user value as a separate argv
    token (no shell string assembly / no $ARGUMENTS single-string interpolation), and
    contains explicit "no absolute percentile / global ranking" wording.'"""
    rating_md = _REPO_ROOT / ".claude" / "commands" / "rating.md"
    assert rating_md.exists(), ".claude/commands/rating.md must exist"

    content = rating_md.read_text(encoding="utf-8")

    # Must invoke python -m rating
    assert "python -m rating" in content

    # Must reference key argv tokens as separate values
    assert "--source-type" in content
    assert "--source" in content
    assert "--author" in content

    # No shell string assembly ($() substitution)
    assert "$(" not in content

    # Hard-rule clause forbidding shell string assembly must be present
    lower = content.lower()
    assert "shell string" in lower or "never assemble" in lower

    # Explicit no-absolute-percentile wording must be present
    assert "not" in lower and "percentile" in lower

    # The example python -m rating command line must NOT contain forbidden ranking phrases
    for line in content.splitlines():
        stripped = line.strip()
        if "python -m rating" in stripped and not stripped.startswith("#"):
            line_lower = stripped.lower()
            assert "rank" not in line_lower, f"forbidden 'rank' in command line: {stripped!r}"
            assert "percentile" not in line_lower, f"forbidden 'percentile' in command line: {stripped!r}"
            assert "top " not in line_lower, f"forbidden 'top ' in command line: {stripped!r}"
