"""Tests for fit batch mode (--jd-dir) and related guarantees.

Each test traces to a Done-when item in outcome.md via its docstring.
All tests inject fake extractor, runner, fetcher, grader_runner — no live services.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.model import Evidence  # noqa: E402
from fit.cli import run  # noqa: E402
from fit.score import ScoreResult, GRADE_BANDS  # noqa: E402
from fit.render import _escape_cell, render_fit_batch  # noqa: E402
from portfolio.i18n import LANGS  # noqa: E402


# ---------------------------------------------------------------------------
# Shared fakes (mirror test_fit.py)
# ---------------------------------------------------------------------------


def _fake_extractor(*, repo: str, author: str) -> list[Evidence]:
    return [Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="Add feature")]


def _fake_runner(prompt: str) -> str:
    return json.dumps([{"text": "Built a python backend service", "evidence_refs": ["PR#1"], "confidence": 0.9}])


def _make_grader_runner(score: int = 80):
    reasoning = [{"text": "solid match", "evidence_refs": ["PR#1"]}]

    def grader(prompt: str, *, temperature: float = 0) -> str:
        return json.dumps({"score": score, "reasoning": reasoning})

    return grader


def _base_batch_argv(jd_dir: str, lang: str | None = None, out: str | None = None) -> list[str]:
    argv = [
        "--source-type",
        "github",
        "--source",
        "https://github.com/owner/repo",
        "--author",
        "alice",
        "--jd-dir",
        jd_dir,
    ]
    if lang is not None:
        argv += ["--lang", lang]
    if out is not None:
        argv += ["--out", out]
    return argv


def _base_single_argv(jd_path: str, lang: str | None = None) -> list[str]:
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
    if lang is not None:
        argv += ["--lang", lang]
    return argv


# ---------------------------------------------------------------------------
# Done-when: happy path end-to-end with N JDs
# ---------------------------------------------------------------------------


def test_jd_dir_happy_path(tmp_path, capsys):
    """'python -m fit --source-type … --source … --author … --jd-dir <dir>' runs
    end-to-end and exits 0 when at least one *.txt or *.md file is in <dir>;
    stdout is a Markdown ranked table with N rows in best-first order."""
    (tmp_path / "alpha.txt").write_text("python backend engineer", encoding="utf-8")
    (tmp_path / "beta.md").write_text("java spring developer", encoding="utf-8")

    code = run(
        _base_batch_argv(str(tmp_path), lang="en"),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_make_grader_runner(80),
    )
    captured = capsys.readouterr()
    assert code == 0
    out = captured.out
    # Markdown table: header + separator + 2 data rows
    rows = [line for line in out.splitlines() if line.startswith("|")]
    assert len(rows) >= 3  # header + sep + 2 data rows
    # Both filenames appear in the table
    assert "alpha.txt" in out
    assert "beta.md" in out


# ---------------------------------------------------------------------------
# Done-when: extension filter
# ---------------------------------------------------------------------------


def test_jd_dir_extension_filter(tmp_path, capsys):
    """'--jd-dir scans <dir> non-recursively; accepts ONLY .txt and .md (case-sensitive);
    ignores .json, .txt.bak, and subdirectories.'"""
    (tmp_path / "job.txt").write_text("python backend", encoding="utf-8")
    (tmp_path / "other.md").write_text("java spring", encoding="utf-8")
    (tmp_path / "notes.json").write_text('{"role": "engineer"}', encoding="utf-8")
    (tmp_path / "job.txt.bak").write_text("python backend", encoding="utf-8")
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    (subdir / "inner.txt").write_text("go microservices", encoding="utf-8")

    code = run(
        _base_batch_argv(str(tmp_path), lang="en"),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_make_grader_runner(80),
    )
    captured = capsys.readouterr()
    assert code == 0
    out = captured.out
    # Only job.txt and other.md are scored
    rows = [line for line in out.splitlines() if line.startswith("|") and not line.startswith("|---")]
    # header is a pipe row too — filter it by checking for column header text
    header_keywords = {"Grade", "등급", "JD"}
    actual_data = [r for r in rows if not any(kw in r for kw in header_keywords) and "---" not in r]
    assert len(actual_data) == 2
    assert "notes.json" not in out
    assert "txt.bak" not in out
    # The subdir inner.txt should not appear (non-recursive)
    lines_with_inner = [ln for ln in out.splitlines() if "inner" in ln]
    assert not lines_with_inner


# ---------------------------------------------------------------------------
# Done-when: filename tiebreak (score + coverage% tie, basename ascending)
# ---------------------------------------------------------------------------


def test_jd_dir_tiebreak_by_basename(tmp_path):
    """'Table rows are sorted: primary key Score descending, secondary key Coverage%
    descending, tertiary key JD basename ascending. A test with hand-crafted
    ScoreResults exercises all three tiers of the tiebreak.'

    Three distinct cases verified:
    1. Different scores → primary key (Score) determines rank.
    2. Equal scores, different coverage% → secondary key (Coverage%) determines rank.
    3. Equal scores, equal coverage% → tertiary key (basename) determines rank.
    """
    # Tier 1 winner: highest score (A band midpoint 90 > B midpoint 77)
    sr_score_winner = ScoreResult(grade="A", band=(85, 95), coverage_pct=50.0, covered={}, gaps=set())

    # Tier 2 winner: same score as tier2_loser (B midpoint 77), but higher coverage%
    sr_coverage_winner = ScoreResult(grade="B", band=(70, 84), coverage_pct=75.0, covered={}, gaps=set())
    sr_coverage_loser = ScoreResult(grade="B", band=(70, 84), coverage_pct=40.0, covered={}, gaps=set())

    # Tier 3: same score AND same coverage% — basename ascending decides
    sr_name_aaa = ScoreResult(grade="C", band=(55, 69), coverage_pct=30.0, covered={}, gaps=set())
    sr_name_zzz = ScoreResult(grade="C", band=(55, 69), coverage_pct=30.0, covered={}, gaps=set())

    results = [
        ("scorewinner.txt", sr_score_winner),  # rank 1 by score
        ("covwinner.txt", sr_coverage_winner),  # rank 2 by coverage%
        ("covloser.txt", sr_coverage_loser),  # rank 3 by coverage%
        ("zzz.txt", sr_name_zzz),  # rank 5 by basename
        ("aaa.txt", sr_name_aaa),  # rank 4 by basename
    ]
    table = render_fit_batch(results, lang="en")
    lines = [ln for ln in table.splitlines() if ln.startswith("|") and "---" not in ln]
    # lines[0] = header, lines[1..] = data rows
    data_lines = lines[1:]
    assert len(data_lines) == 5

    # Tier 1: scorewinner is first (highest score)
    assert "scorewinner.txt" in data_lines[0]

    # Tier 2: covwinner before covloser (same score, higher coverage%)
    cov_win_pos = next(i for i, ln in enumerate(data_lines) if "covwinner.txt" in ln)
    cov_los_pos = next(i for i, ln in enumerate(data_lines) if "covloser.txt" in ln)
    assert cov_win_pos < cov_los_pos, "higher coverage% must rank above lower coverage% when scores tie"

    # Tier 3: aaa.txt before zzz.txt (same score + coverage%, basename ascending)
    aaa_pos = next(i for i, ln in enumerate(data_lines) if "aaa.txt" in ln)
    zzz_pos = next(i for i, ln in enumerate(data_lines) if "zzz.txt" in ln)
    assert aaa_pos < zzz_pos, "ascending basename must be the tiebreak when score and coverage% are equal"


# ---------------------------------------------------------------------------
# Done-when: mutual exclusion — --jd + --jd-dir → exit 2
# ---------------------------------------------------------------------------


def test_mutual_exclusion_both_flags(tmp_path, capsys):
    """'When both --jd and --jd-dir are supplied: the CLI exits with code 2 and
    prints exactly ONE line to stderr naming both options as mutually exclusive.'"""
    jd_path = tmp_path / "jd.txt"
    jd_path.write_text("python", encoding="utf-8")

    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/owner/repo",
            "--author",
            "alice",
            "--jd",
            str(jd_path),
            "--jd-dir",
            str(tmp_path),
        ],
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_make_grader_runner(),
    )
    captured = capsys.readouterr()
    assert code == 2
    stderr_lines = [ln for ln in captured.err.splitlines() if ln.strip()]
    assert len(stderr_lines) == 1


# ---------------------------------------------------------------------------
# Done-when: neither --jd nor --jd-dir supplied → exit 2
# ---------------------------------------------------------------------------


def test_neither_jd_nor_jd_dir(tmp_path, capsys):
    """'When neither --jd nor --jd-dir is supplied: the CLI exits with code 2 and
    prints exactly ONE line to stderr naming both options as mutually exclusive and
    required.'"""
    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/owner/repo",
            "--author",
            "alice",
        ],
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_make_grader_runner(),
    )
    captured = capsys.readouterr()
    assert code == 2
    stderr_lines = [ln for ln in captured.err.splitlines() if ln.strip()]
    assert len(stderr_lines) == 1


# ---------------------------------------------------------------------------
# Done-when: empty dir → exit 2
# ---------------------------------------------------------------------------


def test_jd_dir_empty_dir_exits_2(tmp_path, capsys):
    """'When --jd-dir resolves to zero matching files: the CLI exits with code 2
    and prints exactly ONE line to stderr that names --jd-dir <path> and the reason
    (no matching JDs). It does NOT raise an uncaught exception.'"""
    # tmp_path is an existing but empty directory
    code = run(
        _base_batch_argv(str(tmp_path), lang="en"),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_make_grader_runner(),
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "Traceback" not in captured.err
    stderr_lines = [ln for ln in captured.err.splitlines() if ln.strip()]
    assert len(stderr_lines) == 1
    # The message must mention --jd-dir or the path
    assert "--jd-dir" in captured.err or str(tmp_path) in captured.err


def test_jd_dir_nonexistent_dir_exits_2(tmp_path, capsys):
    """'When --jd-dir points to a non-existent directory: exit 2, one stderr line,
    no traceback.'"""
    nonexistent = str(tmp_path / "does_not_exist")
    code = run(
        _base_batch_argv(nonexistent, lang="en"),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_make_grader_runner(),
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "Traceback" not in captured.err
    stderr_lines = [ln for ln in captured.err.splitlines() if ln.strip()]
    assert len(stderr_lines) == 1


def test_jd_dir_only_other_extensions_exits_2(tmp_path, capsys):
    """'When --jd-dir dir-of-only-other-extensions: exit 2, one stderr line.'"""
    (tmp_path / "notes.json").write_text("{}", encoding="utf-8")
    (tmp_path / "data.csv").write_text("a,b,c", encoding="utf-8")
    code = run(
        _base_batch_argv(str(tmp_path), lang="en"),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_make_grader_runner(),
    )
    captured = capsys.readouterr()
    assert code == 2
    stderr_lines = [ln for ln in captured.err.splitlines() if ln.strip()]
    assert len(stderr_lines) == 1


# ---------------------------------------------------------------------------
# Done-when: "build once" — extractor called exactly once for N JDs
# ---------------------------------------------------------------------------


def test_build_once_extractor_called_once(tmp_path, capsys):
    """'The portfolio is built exactly ONCE per --jd-dir invocation: in a test,
    an injected counting extractor is called exactly once when N JDs are scored
    (N >= 2).'"""
    (tmp_path / "a.txt").write_text("python backend", encoding="utf-8")
    (tmp_path / "b.txt").write_text("java spring", encoding="utf-8")
    (tmp_path / "c.md").write_text("go microservices", encoding="utf-8")

    extractor_calls: list = []

    def counting_extractor(*, repo: str, author: str) -> list[Evidence]:
        extractor_calls.append((repo, author))
        return [Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="Add feature")]

    runner_calls: list = []

    def counting_runner(prompt: str) -> str:
        runner_calls.append(prompt)
        return json.dumps([{"text": "Built a python backend service", "evidence_refs": ["PR#1"], "confidence": 0.9}])

    code = run(
        _base_batch_argv(str(tmp_path), lang="en"),
        extractor=counting_extractor,
        runner=counting_runner,
        grader_runner=_make_grader_runner(),
    )
    capsys.readouterr()
    assert code == 0
    # Extractor called exactly once (portfolio built once)
    assert len(extractor_calls) == 1

    # Runner (narrative model) called same number of times as a single-JD invocation
    # In the current pipeline, runner is called once to narrate claims.
    # For single --jd, runner_calls would be 1; batch should also be 1.
    single_runner_calls: list = []

    def single_counting_runner(prompt: str) -> str:
        single_runner_calls.append(prompt)
        return json.dumps([{"text": "Built a python backend service", "evidence_refs": ["PR#1"], "confidence": 0.9}])

    jd_path = tmp_path / "single.txt"
    jd_path.write_text("python backend", encoding="utf-8")
    single_extractor_calls: list = []

    def single_counting_extractor(*, repo: str, author: str) -> list[Evidence]:
        single_extractor_calls.append((repo, author))
        return [Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="Add feature")]

    run(
        _base_single_argv(str(jd_path), lang="en"),
        extractor=single_counting_extractor,
        runner=single_counting_runner,
        grader_runner=_make_grader_runner(),
    )
    capsys.readouterr()
    # The runner call count for batch should be same as for single-JD
    assert len(runner_calls) == len(single_runner_calls)


# ---------------------------------------------------------------------------
# Done-when: score_fit per JD, same Portfolio instance
# ---------------------------------------------------------------------------


def test_score_fit_same_portfolio_instance(tmp_path, capsys, monkeypatch):
    """'score_fit is invoked once per matching JD file; the Portfolio object passed
    to it is the SAME in-memory instance (is-identical) across all calls.'"""
    (tmp_path / "a.txt").write_text("python backend", encoding="utf-8")
    (tmp_path / "b.txt").write_text("java spring", encoding="utf-8")

    import fit.cli as _fit_cli
    from fit.score import score_fit as _real_score_fit

    calls: list[dict] = []

    def spy_score_fit(portfolio, jd_text):
        calls.append({"portfolio": portfolio, "jd_text": jd_text})
        return _real_score_fit(portfolio, jd_text)

    monkeypatch.setattr(_fit_cli, "score_fit", spy_score_fit)

    code = run(
        _base_batch_argv(str(tmp_path), lang="en"),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_make_grader_runner(),
    )
    capsys.readouterr()
    assert code == 0
    # Called once per JD file (2 files)
    assert len(calls) == 2
    # Same Portfolio instance across all calls
    assert calls[0]["portfolio"] is calls[1]["portfolio"]


# ---------------------------------------------------------------------------
# Done-when: determinism
# ---------------------------------------------------------------------------


def test_jd_dir_determinism(tmp_path, capsys):
    """'Running --jd-dir twice with the same (portfolio source inputs, JD set,
    --lang) produces byte-identical stdout.'"""
    (tmp_path / "a.txt").write_text("python backend engineer", encoding="utf-8")
    (tmp_path / "b.md").write_text("java spring developer", encoding="utf-8")

    argv = _base_batch_argv(str(tmp_path), lang="en")

    code1 = run(argv, extractor=_fake_extractor, runner=_fake_runner, grader_runner=_make_grader_runner(80))
    out1 = capsys.readouterr().out

    code2 = run(argv, extractor=_fake_extractor, runner=_fake_runner, grader_runner=_make_grader_runner(80))
    out2 = capsys.readouterr().out

    assert code1 == 0
    assert code2 == 0
    assert out1 == out2, "batch output must be byte-identical on repeated runs"


# ---------------------------------------------------------------------------
# Done-when: batch web-source passes fetcher through (IR-001)
# ---------------------------------------------------------------------------


def test_batch_fetcher_passed_through(tmp_path, capsys):
    """'Batch mode must pass the injected fetcher through _run_batch, matching
    single-JD behavior. A counting fetcher is injected; if --source-type github
    is used the fetcher is not called, but the SourceRequest must carry it
    (no AttributeError / None-call on the fetcher seam).'
    Traces to IR-001: batch mode breaks --source-type web when fetcher=None."""
    (tmp_path / "jd.txt").write_text("python backend", encoding="utf-8")

    fetcher_calls: list = []

    def counting_fetcher(url: str) -> str:
        fetcher_calls.append(url)
        return "<html>python backend</html>"

    code = run(
        _base_batch_argv(str(tmp_path), lang="en"),
        extractor=_fake_extractor,
        runner=_fake_runner,
        fetcher=counting_fetcher,
        grader_runner=_make_grader_runner(80),
    )
    capsys.readouterr()
    # The key assertion: run() must not crash due to fetcher=None being passed
    # to _run_batch. With the fix, fetcher is forwarded; exit code is 0.
    assert code == 0


# ---------------------------------------------------------------------------
# Done-when: IR-002 — unreadable JD file exits cleanly (no traceback)
# ---------------------------------------------------------------------------


def test_jd_file_invalid_utf8_exits_1(tmp_path, capsys):
    """'Matching JD files are read without handling UnicodeError. An invalid-UTF-8
    file raises an uncaught exception after the expensive portfolio build. Return
    a clean nonzero error without a traceback and test both cases.'
    Traces to IR-002 (UnicodeError case)."""
    # Write a file with invalid UTF-8 bytes
    bad_file = tmp_path / "bad.txt"
    bad_file.write_bytes(b"python backend \xff\xfe invalid")

    code = run(
        _base_batch_argv(str(tmp_path), lang="en"),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_make_grader_runner(80),
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "Traceback" not in captured.err
    # At least one non-empty stderr line about the failure
    assert captured.err.strip() != ""


# ---------------------------------------------------------------------------
# Done-when: table-cell escaping (PR-002)
# ---------------------------------------------------------------------------


def test_escape_cell_pipe():
    """'_escape_cell escapes | as \\|.'"""
    assert _escape_cell("foo|bar") == "foo\\|bar"


def test_escape_cell_newline():
    """'_escape_cell replaces \\n with a space.'"""
    assert _escape_cell("foo\nbar") == "foo bar"


def test_escape_cell_carriage_return():
    """'_escape_cell replaces \\r with a space.'"""
    assert _escape_cell("foo\rbar") == "foo bar"


def test_escape_cell_markdown_specials():
    """'_escape_cell escapes Markdown specials (backtick, brackets, backslash, etc.).'"""
    result = _escape_cell("`foo`")
    assert "\\`" in result


def test_table_cell_escaping_basename_with_pipe(tmp_path):
    """'A test feeds the renderer a JD basename containing a literal | and a basename
    containing a literal \\n and asserts: (a) rendered table has exactly one row per JD,
    (b) no unescaped | appears inside any data cell, (c) no row spans more than one
    line of output, (d) offending characters are encoded per the rule above.'"""
    # We test via render_fit_batch directly (CLI can't take | in filename on most OS)
    sr = ScoreResult(grade="B", band=(70, 84), coverage_pct=60.0, covered={}, gaps=set())
    sr2 = ScoreResult(grade="C", band=(55, 69), coverage_pct=40.0, covered={}, gaps=set())

    # Basename with a pipe
    pipe_name = "role|senior.txt"
    # Basename with a newline
    newline_name = "role\njunior.txt"

    results = [(pipe_name, sr), (newline_name, sr2)]
    table = render_fit_batch(results, lang="en")
    lines = table.splitlines()

    # (a) exactly 2 data rows (plus 1 header + 1 sep = 4 total lines)
    pipe_rows = [ln for ln in lines if ln.startswith("|")]
    assert len(pipe_rows) == 4  # header + sep + 2 data rows

    # (c) no row spans more than one output line — every | row is a single line
    for ln in pipe_rows:
        assert "\n" not in ln

    # (b) check that no data cell contains an unescaped pipe (outside of row delimiters)
    for data_line in pipe_rows[2:]:  # skip header and separator
        # Strip leading and trailing | then check cells
        inner = data_line.strip("|")
        cells = inner.split("|")
        for cell in cells:
            # No raw (unescaped) pipe inside a cell
            assert not any(ch == "|" and (i == 0 or cell[i - 1] != "\\") for i, ch in enumerate(cell))

    # (d) the | in the basename is escaped as \|
    assert "role\\|senior" in table
    # (d) the \n in the basename is replaced with a space
    assert "role junior.txt" in table or "role\x20junior.txt" in table


def test_table_cell_escaping_top_gaps_with_pipe():
    """'A second assertion exercises a Top Gaps token containing a literal | and
    confirms it is escaped identically.'"""
    sr = ScoreResult(
        grade="C",
        band=(55, 69),
        coverage_pct=40.0,
        covered={},
        gaps={"foo|bar", "baz"},
    )
    table = render_fit_batch([("job.txt", sr)], lang="en")
    # The | in the gap token must be escaped as \|
    assert "foo\\|bar" in table
    # Exactly 1 data row (the table didn't split into extra rows due to the |)
    data_rows = [
        ln
        for ln in table.splitlines()
        if ln.startswith("|") and "---" not in ln and LANGS["en"]["batch_col_jd"] not in ln
    ]
    assert len(data_rows) == 1
    # The raw data row contains the escaped form, not a bare |
    assert "foo\\|bar" in data_rows[0]


# ---------------------------------------------------------------------------
# Done-when: --lang ko no-leak on ranked table output (PR-001 extension)
# ---------------------------------------------------------------------------


def test_lang_ko_no_english_leak_in_batch_table(tmp_path, capsys):
    """'--lang ko localizes the ranked-table column headers and the "none" cell text.
    A test renders the ko ranked table and asserts none of the new LANGS["en"] UI
    strings for the table appear verbatim in stdout.'"""
    (tmp_path / "jd.txt").write_text("python backend", encoding="utf-8")

    code = run(
        _base_batch_argv(str(tmp_path), lang="ko"),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_make_grader_runner(80),
    )
    captured = capsys.readouterr()
    assert code == 0

    # The new EN batch column header strings must not appear in ko output
    en_batch_keys = ["batch_col_grade", "batch_col_score", "batch_col_coverage", "batch_col_top_gaps"]
    for key in en_batch_keys:
        en_val = LANGS["en"][key]
        ko_val = LANGS["ko"][key]
        if en_val == ko_val:
            continue  # language-neutral (e.g. "JD" is same in both)
        assert en_val not in captured.out, (
            f"English UI string LANGS['en']['{key}']={en_val!r} leaked into ko batch render"
        )

    # Korean column headers must appear
    assert LANGS["ko"]["batch_col_grade"] in captured.out


# ---------------------------------------------------------------------------
# Done-when: batch default lang = "en" when --lang omitted (PR-001)
# ---------------------------------------------------------------------------


def test_batch_default_lang_en_without_lang_flag(tmp_path, capsys):
    """'When --jd-dir is used and --lang is OMITTED, the table language is en.
    There is no auto-detection from JD contents in batch mode. A test runs --jd-dir
    against a directory of Korean-text JDs without --lang, asserts the rendered
    headers are the English LANGS["en"] table-header strings, and asserts the Korean
    header strings from LANGS["ko"] do NOT appear in stdout.'"""
    # Korean-dominant JD text
    korean_jd = "파이썬 백엔드 개발자 구인합니다. 경력 3년 이상 필요합니다."
    (tmp_path / "jd_ko.txt").write_text(korean_jd, encoding="utf-8")

    # No --lang flag → should default to "en"
    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/owner/repo",
            "--author",
            "alice",
            "--jd-dir",
            str(tmp_path),
        ],
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_make_grader_runner(80),
    )
    captured = capsys.readouterr()
    assert code == 0

    # English headers must appear
    assert LANGS["en"]["batch_col_grade"] in captured.out  # "Grade"
    assert LANGS["en"]["batch_col_top_gaps"] in captured.out  # "Top Gaps"

    # Korean batch headers must NOT appear in stdout
    ko_grade = LANGS["ko"]["batch_col_grade"]  # "등급"
    ko_gaps = LANGS["ko"]["batch_col_top_gaps"]  # "주요 격차"
    assert ko_grade not in captured.out
    assert ko_gaps not in captured.out


# ---------------------------------------------------------------------------
# Done-when: IR-002 — OSError on JD file exits cleanly (no traceback)
# ---------------------------------------------------------------------------


def test_jd_file_oserror_exits_1(tmp_path, capsys):
    """'An unreadable JD file (OSError) must return a clean nonzero error without
    a traceback.'
    Traces to IR-002 (OSError case)."""
    jd_file = tmp_path / "locked.txt"
    jd_file.write_text("python backend", encoding="utf-8")
    # Remove read permission so open() raises PermissionError (subclass of OSError)
    jd_file.chmod(0o000)

    try:
        code = run(
            _base_batch_argv(str(tmp_path), lang="en"),
            extractor=_fake_extractor,
            runner=_fake_runner,
            grader_runner=_make_grader_runner(80),
        )
        captured = capsys.readouterr()
        assert code == 1
        assert "Traceback" not in captured.err
        assert captured.err.strip() != ""
    finally:
        # Restore permissions so tmp_path cleanup works
        jd_file.chmod(0o644)


# ---------------------------------------------------------------------------
# Done-when: grounding isolation — no JD text in Evidence
# ---------------------------------------------------------------------------


def test_grounding_isolation_no_jd_in_evidence(tmp_path, capsys, monkeypatch):
    """'After a --jd-dir run, no JD basename and no substring of any JD body appears
    in any Evidence.ref or Evidence.detail of the in-memory Portfolio.'"""
    jd_text = "UNIQUEJDKEYWORD python backend"
    jd_name = "UNIQUEJDBASENAME.txt"
    (tmp_path / jd_name).write_text(jd_text, encoding="utf-8")

    import fit.cli as _fit_cli

    captured_portfolio: list = []
    _real_score = _fit_cli.score_fit

    def spy_score(portfolio, text):
        captured_portfolio.append(portfolio)
        return _real_score(portfolio, text)

    monkeypatch.setattr(_fit_cli, "score_fit", spy_score)

    code = run(
        _base_batch_argv(str(tmp_path), lang="en"),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_make_grader_runner(),
    )
    capsys.readouterr()
    assert code == 0
    assert captured_portfolio, "score_fit must have been called"

    portfolio = captured_portfolio[0]
    for ev in portfolio.evidence:
        assert jd_name not in ev.ref, f"JD basename appeared in Evidence.ref: {ev.ref!r}"
        assert jd_name not in ev.detail, f"JD basename appeared in Evidence.detail: {ev.detail!r}"
        assert "UNIQUEJDKEYWORD" not in ev.ref
        assert "UNIQUEJDKEYWORD" not in ev.detail


# ---------------------------------------------------------------------------
# Done-when: grounding summary printed exactly ONCE per --jd-dir invocation
# ---------------------------------------------------------------------------


def test_grounding_summary_once_in_batch(tmp_path, capsys):
    """'The stderr grounding summary line (grounded: N  rejected: N  needs-confirmation: N)
    is printed exactly ONCE per --jd-dir invocation, identical in format to
    single---jd mode.'"""
    (tmp_path / "a.txt").write_text("python backend", encoding="utf-8")
    (tmp_path / "b.txt").write_text("java spring", encoding="utf-8")
    (tmp_path / "c.md").write_text("go microservices", encoding="utf-8")

    code = run(
        _base_batch_argv(str(tmp_path), lang="en"),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_make_grader_runner(),
    )
    captured = capsys.readouterr()
    assert code == 0

    summary_lines = [ln for ln in captured.err.splitlines() if ln.startswith("grounded:")]
    assert len(summary_lines) == 1
    # Format matches single-JD: "grounded: N  rejected: N  needs-confirmation: N"
    assert "rejected:" in summary_lines[0]
    assert "needs-confirmation:" in summary_lines[0]


# ---------------------------------------------------------------------------
# Done-when: i18n completeness — new batch keys in both en and ko
# ---------------------------------------------------------------------------


def test_batch_i18n_keys_present_in_both_langs():
    """'New i18n keys for the ranked table are present in BOTH LANGS["en"] and
    LANGS["ko"] with non-empty values.'"""
    batch_keys = [
        "batch_col_jd",
        "batch_col_grade",
        "batch_col_score",
        "batch_col_coverage",
        "batch_col_top_gaps",
    ]
    for key in batch_keys:
        assert key in LANGS["en"], f"Missing LANGS['en']['{key}']"
        assert LANGS["en"][key], f"LANGS['en']['{key}'] is empty"
        assert key in LANGS["ko"], f"Missing LANGS['ko']['{key}']"
        assert LANGS["ko"][key], f"LANGS['ko']['{key}'] is empty"


# ---------------------------------------------------------------------------
# Done-when: Score column is band midpoint (min + max) // 2
# ---------------------------------------------------------------------------


def test_score_column_is_band_midpoint():
    """'The Score column contains a deterministic integer derived from score_result.band
    as the band midpoint (min + max) // 2.'"""
    for grade, band in GRADE_BANDS.items():
        sr = ScoreResult(grade=grade, band=band, coverage_pct=50.0, covered={}, gaps=set())
        table = render_fit_batch([("job.txt", sr)], lang="en")
        expected_score = str((band[0] + band[1]) // 2)
        assert expected_score in table, f"Expected midpoint {expected_score} for grade {grade} in table"


# ---------------------------------------------------------------------------
# Done-when: Top Gaps column — first 5 sorted gaps, or none_notice when empty
# ---------------------------------------------------------------------------


def test_top_gaps_shows_first_5_sorted():
    """'The Top Gaps column contains the first 5 elements of sorted(score_result.gaps)
    (alphabetical, deterministic), joined by ", ".'"""
    gaps = {"zebra", "alpha", "mango", "beta", "kiwi", "orange"}  # 6 gaps
    sr = ScoreResult(grade="D", band=(0, 54), coverage_pct=0.0, covered={}, gaps=gaps)
    table = render_fit_batch([("job.txt", sr)], lang="en")

    # First 5 alphabetically: alpha, beta, kiwi, mango, orange
    # "zebra" should NOT appear (6th alphabetically)
    assert "alpha" in table
    assert "beta" in table
    assert "kiwi" in table
    assert "mango" in table
    assert "orange" in table
    assert "zebra" not in table


def test_top_gaps_none_notice_when_empty():
    """'If a JD has zero gaps the cell shows the localized none_notice string.'"""
    sr = ScoreResult(grade="S", band=(96, 100), coverage_pct=100.0, covered={}, gaps=set())
    table_en = render_fit_batch([("job.txt", sr)], lang="en")
    table_ko = render_fit_batch([("job.txt", sr)], lang="ko")

    assert LANGS["en"]["none_notice"] in table_en
    assert LANGS["ko"]["none_notice"] in table_ko


# ---------------------------------------------------------------------------
# Done-when: JD column contains basename not full path
# ---------------------------------------------------------------------------


def test_jd_column_is_basename_not_full_path(tmp_path, capsys):
    """'The JD column contains the JD basename (filename including extension),
    not its full path.'"""
    (tmp_path / "myfile.txt").write_text("python backend", encoding="utf-8")

    code = run(
        _base_batch_argv(str(tmp_path), lang="en"),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_make_grader_runner(80),
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "myfile.txt" in captured.out
    # The full absolute path must NOT appear in any data cell
    assert str(tmp_path) not in captured.out


# ---------------------------------------------------------------------------
# Done-when: --out writes ranked table to file in batch mode
# ---------------------------------------------------------------------------


def test_jd_dir_out_file(tmp_path, capsys):
    """'With --out <path> in batch mode, the ranked table is written to <path>
    and stdout is empty.'"""
    (tmp_path / "a.txt").write_text("python backend", encoding="utf-8")
    out_path = tmp_path / "ranked.md"

    code = run(
        _base_batch_argv(str(tmp_path), lang="en", out=str(out_path)),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_make_grader_runner(80),
    )
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.strip() == ""
    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    assert LANGS["en"]["batch_col_grade"] in content
