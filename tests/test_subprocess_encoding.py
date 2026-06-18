"""Regression tests: every subprocess.run call in the affected runners must pass
encoding="utf-8" with text=True, deliver prompts via stdin (not argv), and keep
the --output-format json contract.  All tests monkeypatch subprocess.run so no
live gh / claude / codex is needed.

Each test function quotes the Done-when item from outcome.md that it covers.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.extract import _run_gh  # noqa: E402
from portfolio.narrative import run_claude, run_codex  # noqa: E402

# Import rating lazily inside tests so an ImportError surfaces as a test
# error (not collection failure) and gives a clear blocker message.


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_proc(stdout: str = "", returncode: int = 0, stderr: str = "") -> SimpleNamespace:
    """Return a fake subprocess.CompletedProcess-like object."""
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


# ---------------------------------------------------------------------------
# _run_gh tests
# ---------------------------------------------------------------------------


def test_run_gh_passes_encoding_utf8(monkeypatch):
    """Done-when: '`portfolio/extract.py` `_run_gh` (the `subprocess.run(["gh",
    *args], ...)` call at ~line 22) passes `encoding="utf-8"` together with
    `text=True`; verifiable by a test under `tests/` that captures the kwargs
    the `gh` runner uses (monkeypatched `subprocess.run`) and asserts
    `encoding == "utf-8"`.'"""
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _fake_proc(stdout="[]")

    monkeypatch.setattr(subprocess, "run", fake_run)
    _run_gh(["pr", "list"])

    assert captured["kwargs"].get("encoding") == "utf-8", (
        f"expected encoding='utf-8', got {captured['kwargs'].get('encoding')!r}"
    )
    assert captured["kwargs"].get("text") is True


def test_run_gh_roundtrips_non_ascii_stdout(monkeypatch):
    """Done-when: '`portfolio/extract.py` `_run_gh` round-trips non-ASCII (e.g.
    a Korean) child stdout without raising `UnicodeDecodeError`; verifiable by a
    test that has the faked `subprocess.run` return UTF-8 text and asserts the
    bytes survive unchanged.'

    Note: subprocess.run is monkeypatched, so this test does NOT exercise the
    OS-level byte decode (the real cp949 UnicodeDecodeError happens inside the
    real subprocess.run, which we replace). What this test pins is the *fix
    mechanism* — that `_run_gh` passes encoding="utf-8" — together with the
    runner returning non-ASCII stdout unchanged. The encoding="utf-8" assertion
    is what fails against the pre-change code; the round-trip assertion guards
    the observable contract."""
    korean_text = "한국어 PR 제목"  # Korean: "Korean PR title"
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _fake_proc(stdout=korean_text)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = _run_gh(["pr", "list"])

    # The mechanism: encoding must be utf-8.
    assert captured["kwargs"].get("encoding") == "utf-8", (
        f"encoding='utf-8' required for non-ASCII round-trip; got {captured['kwargs'].get('encoding')!r}"
    )
    # The observable result: text survives unchanged.
    assert result == korean_text, f"non-ASCII stdout not preserved: {result!r}"


# ---------------------------------------------------------------------------
# run_claude tests
# ---------------------------------------------------------------------------


def test_run_claude_passes_encoding_utf8(monkeypatch):
    """Done-when: '`portfolio/narrative.py` `run_claude` (the `subprocess.run`
    at ~line 92) passes `encoding="utf-8"` with `text=True`; verifiable by a
    test capturing the runner's kwargs.'"""
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _fake_proc(stdout=json.dumps({"result": "ok"}))

    monkeypatch.setattr(subprocess, "run", fake_run)
    run_claude("some prompt")

    assert captured["kwargs"].get("encoding") == "utf-8", (
        f"expected encoding='utf-8', got {captured['kwargs'].get('encoding')!r}"
    )
    assert captured["kwargs"].get("text") is True


def test_run_claude_prompt_via_stdin_not_argv(monkeypatch):
    """Done-when: '`portfolio/narrative.py` `run_claude` delivers the prompt via
    **stdin** (`input=<prompt>`) and the prompt string is **not** present as any
    argv element; verifiable by a test that asserts the captured `input` equals
    the prompt and that the prompt is not in the captured argv list.'"""
    prompt = "Write me portfolio claims for this developer."
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _fake_proc(stdout=json.dumps({"result": "claims text"}))

    monkeypatch.setattr(subprocess, "run", fake_run)
    run_claude(prompt)

    assert captured["kwargs"].get("input") == prompt, (
        f"prompt should be passed as stdin input=, got input={captured['kwargs'].get('input')!r}"
    )
    assert prompt not in captured["args"], f"prompt must not appear in argv; argv={captured['args']}"


def test_run_claude_returns_result_from_json_envelope_with_output_format_in_argv(monkeypatch):
    """Done-when: '`portfolio/narrative.py` `run_claude` still returns the parsed
    string `.result` from an unchanged `--output-format json` envelope; verifiable
    by a test feeding a `{"result": "..."}` JSON stdout and asserting the returned
    value, with `--output-format json` still present in argv.'

    This test combines the JSON-envelope contract with the stdin requirement so
    that it fails against current code (which passes the prompt as -p <prompt>
    argv rather than via stdin).  The --output-format json flag and result parsing
    are verified in the same call to pin both invariants."""
    expected = "This is the grounded narrative."
    prompt = "A very long grounded portfolio prompt."
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _fake_proc(stdout=json.dumps({"result": expected}))

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_claude(prompt)

    # The stdin contract must hold (this is the breaking change that makes the
    # test red against current code).
    assert captured["kwargs"].get("input") == prompt, (
        f"prompt should be via stdin, got input={captured['kwargs'].get('input')!r}"
    )
    assert prompt not in captured["args"], f"prompt must not be in argv; argv={captured['args']}"
    # The JSON-envelope contract must be preserved.
    assert "--output-format" in captured["args"], "--output-format must still be in argv"
    assert "json" in captured["args"], "json must follow --output-format in argv"
    assert result == expected, f"expected parsed .result={expected!r}, got {result!r}"


# ---------------------------------------------------------------------------
# run_codex tests
# ---------------------------------------------------------------------------


def test_run_codex_passes_encoding_utf8(monkeypatch):
    """Done-when: '`portfolio/narrative.py` `run_codex` (the `subprocess.run` at
    ~line 108) passes `encoding="utf-8"` with `text=True` (it already uses
    `input=prompt`); verifiable by a test capturing the runner's kwargs.'"""
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _fake_proc(stdout="codex output")

    monkeypatch.setattr(subprocess, "run", fake_run)
    run_codex("some prompt")

    assert captured["kwargs"].get("encoding") == "utf-8", (
        f"expected encoding='utf-8', got {captured['kwargs'].get('encoding')!r}"
    )
    assert captured["kwargs"].get("text") is True


# ---------------------------------------------------------------------------
# rating/cli.py _default_grader_runner tests
# ---------------------------------------------------------------------------


def test_default_grader_runner_passes_encoding_utf8(monkeypatch):
    """Done-when: '`rating/cli.py` `_default_grader_runner` (the `subprocess.run`
    at ~line 33) passes `encoding="utf-8"` with `text=True`; verifiable by a test
    under `tests/` (which may `import rating`) capturing the runner's kwargs.'"""
    import rating.cli as rating_cli  # noqa: PLC0415

    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _fake_proc(stdout=json.dumps({"result": "grade text"}))

    monkeypatch.setattr(subprocess, "run", fake_run)
    rating_cli._default_grader_runner("some prompt")

    assert captured["kwargs"].get("encoding") == "utf-8", (
        f"expected encoding='utf-8', got {captured['kwargs'].get('encoding')!r}"
    )
    assert captured["kwargs"].get("text") is True


def test_default_grader_runner_prompt_via_stdin_not_argv(monkeypatch):
    """Done-when: '`rating/cli.py` `_default_grader_runner` delivers the prompt
    via **stdin** (`input=<prompt>`), the prompt is **not** in argv, and
    `--output-format json` is still present; verifiable by a test asserting
    captured `input`, argv absence, and the parsed `.result` return value.'"""
    import rating.cli as rating_cli  # noqa: PLC0415

    prompt = "Grade this developer's portfolio."
    expected_result = "Senior Engineer"
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _fake_proc(stdout=json.dumps({"result": expected_result}))

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = rating_cli._default_grader_runner(prompt)

    # prompt delivered via stdin, not argv
    assert captured["kwargs"].get("input") == prompt, (
        f"prompt should be passed as stdin input=, got input={captured['kwargs'].get('input')!r}"
    )
    assert prompt not in captured["args"], f"prompt must not appear in argv; argv={captured['args']}"
    # --output-format json still present
    assert "--output-format" in captured["args"], "--output-format flag must still be present in argv"
    assert "json" in captured["args"], "json value must still be present after --output-format in argv"
    # parsed .result returned
    assert result == expected_result, f"expected {expected_result!r}, got {result!r}"


# ---------------------------------------------------------------------------
# shell=True absence tests — combined with encoding checks so they fail red
# ---------------------------------------------------------------------------


def test_run_gh_does_not_use_shell_true_and_passes_encoding(monkeypatch):
    """Done-when: 'No `subprocess.run` call in the affected files uses
    `shell=True`; all calls remain argv lists with separate items (no string
    assembly).' — covers the _run_gh call site.

    Combined with the encoding assertion so the test fails against current code
    (which lacks encoding=) rather than passing trivially (shell=False was never
    the bug)."""
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _fake_proc(stdout="[]")

    monkeypatch.setattr(subprocess, "run", fake_run)
    _run_gh(["pr", "list"])

    assert captured["kwargs"].get("shell") is not True, "shell=True must not be used in _run_gh"
    # encoding must also be set — both invariants pinned together
    assert captured["kwargs"].get("encoding") == "utf-8", (
        f"encoding='utf-8' must be set; got {captured['kwargs'].get('encoding')!r}"
    )


def test_run_claude_does_not_use_shell_true_and_passes_encoding(monkeypatch):
    """Done-when: 'No `subprocess.run` call in the affected files uses
    `shell=True`; all calls remain argv lists with separate items (no string
    assembly).' — covers the run_claude call site.

    Combined with encoding assertion so the test is red against current code."""
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _fake_proc(stdout=json.dumps({"result": "ok"}))

    monkeypatch.setattr(subprocess, "run", fake_run)
    run_claude("prompt")

    assert captured["kwargs"].get("shell") is not True, "shell=True must not be used in run_claude"
    assert captured["kwargs"].get("encoding") == "utf-8", (
        f"encoding='utf-8' must be set; got {captured['kwargs'].get('encoding')!r}"
    )


def test_run_codex_does_not_use_shell_true_and_passes_encoding(monkeypatch):
    """Done-when: 'No `subprocess.run` call in the affected files uses
    `shell=True`; all calls remain argv lists with separate items (no string
    assembly).' — covers the run_codex call site.

    Combined with encoding assertion so the test is red against current code."""
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _fake_proc(stdout="ok")

    monkeypatch.setattr(subprocess, "run", fake_run)
    run_codex("prompt")

    assert captured["kwargs"].get("shell") is not True, "shell=True must not be used in run_codex"
    assert captured["kwargs"].get("encoding") == "utf-8", (
        f"encoding='utf-8' must be set; got {captured['kwargs'].get('encoding')!r}"
    )


def test_default_grader_runner_does_not_use_shell_true_and_passes_encoding(monkeypatch):
    """Done-when: 'No `subprocess.run` call in the affected files uses
    `shell=True`; all calls remain argv lists with separate items (no string
    assembly).' — covers the _default_grader_runner call site.

    Combined with encoding assertion so the test is red against current code."""
    import rating.cli as rating_cli  # noqa: PLC0415

    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _fake_proc(stdout=json.dumps({"result": "ok"}))

    monkeypatch.setattr(subprocess, "run", fake_run)
    rating_cli._default_grader_runner("prompt")

    assert captured["kwargs"].get("shell") is not True, "shell=True must not be used in _default_grader_runner"
    assert captured["kwargs"].get("encoding") == "utf-8", (
        f"encoding='utf-8' must be set; got {captured['kwargs'].get('encoding')!r}"
    )
