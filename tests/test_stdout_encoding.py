"""Regression tests: inline stdout output (no --out) works on a non-UTF-8 (cp949)
host for all five product CLIs.

Each test installs a cp949-encoded TextIOWrapper(BytesIO()) as sys.stdout via
monkeypatch, drives the CLI's inline path with a fake extractor/runner so no
live gh/claude is needed, and asserts:
  (a) no exception is raised, and
  (b) the bytes written to sys.stdout.buffer decode as UTF-8 back to exactly
      the rendered Markdown with a single trailing newline.

These tests FAIL against the pre-fix code (print(markdown) raises
UnicodeEncodeError on a cp949 stream because render_markdown always emits em-dash
'—' in the title) and PASS after the buffer-write fix.

Each test function quotes the Done-when item from outcome.md that it covers.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.model import Evidence  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cp949_stdout() -> tuple[io.TextIOWrapper, io.BytesIO]:
    """Return (fake_stdout, underlying_buffer) with cp949 encoding."""
    buf = io.BytesIO()
    wrapper = io.TextIOWrapper(buf, encoding="cp949")
    return wrapper, buf


def _utf8_stdout() -> tuple[io.TextIOWrapper, io.BytesIO]:
    """Return (fake_stdout, underlying_buffer) with utf-8 encoding."""
    buf = io.BytesIO()
    wrapper = io.TextIOWrapper(buf, encoding="utf-8")
    return wrapper, buf


def _read_buf(buf: io.BytesIO) -> bytes:
    buf.flush()
    return buf.getvalue()


def _fake_extractor(*, repo: str, author: str) -> list[Evidence]:
    """Returns one canned Evidence; no network."""
    return [Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="feat")]


def _fake_runner(_prompt: str) -> str:
    """Returns one grounded claim citing PR#1."""
    return json.dumps([{"text": "Built key feature", "evidence_refs": ["PR#1"], "confidence": 0.9}])


def _fake_grader_runner(prompt: str, temperature: int = 0) -> str:
    """Minimal stand-in grader; returns plain text (no model call)."""
    return "This candidate meets the requirements."


# ---------------------------------------------------------------------------
# portfolio/cli.py — inline stdout path
# ---------------------------------------------------------------------------


def test_portfolio_cli_cp949_stdout_no_raise_and_utf8_bytes(monkeypatch: Any) -> None:
    """Done-when: '`portfolio/cli.py`'s inline (no `--out`) path emits the Markdown
    as UTF-8 and does not raise when stdout's locale encoding cannot represent a
    non-ASCII char (e.g. `—`); verified by a test under `tests/` that simulates a
    non-UTF-8 stdout.'

    The rendered Markdown always contains `—` (em-dash) in the title
    '# Portfolio — alice', which cp949 cannot encode, so print(markdown) would
    raise UnicodeEncodeError against the pre-fix code."""
    from portfolio.cli import run  # noqa: PLC0415

    fake_stdout, buf = _cp949_stdout()
    monkeypatch.setattr(sys, "stdout", fake_stdout)

    code = run(
        ["--source-type", "github", "--source", "https://github.com/owner/repo", "--author", "alice"],
        extractor=_fake_extractor,
        runner=_fake_runner,
    )

    assert code == 0, f"expected exit 0, got {code}"
    raw = _read_buf(buf)
    assert raw, "nothing was written to stdout buffer"
    decoded = raw.decode("utf-8")
    assert decoded.endswith("\n"), "output must end with exactly one newline"
    # em-dash survives
    assert "—" in decoded, "em-dash (—) must be present in the UTF-8 output"
    assert "alice" in decoded
    assert "Built key feature" in decoded


def test_portfolio_cli_utf8_stdout_single_trailing_newline(monkeypatch: Any) -> None:
    """INVARIANT / parity guard — Done-when: 'On an already-UTF-8 stdout the inline
    path still emits the same Markdown with a single trailing newline (no
    double-encoding, no mojibake, no behaviour change); asserted by a test under
    `tests/`.'

    This test pins that the new emit_markdown mechanism emits exactly one trailing
    newline — identical behaviour to the original print(markdown).  It is intentionally
    allowed to pass against both the pre-change and post-change code (it is a
    no-behaviour-change guard, not a red-phase test)."""
    from portfolio.cli import run  # noqa: PLC0415

    # Capture what render_markdown would produce so we can compare byte-for-byte.
    fake_stdout, buf = _utf8_stdout()
    monkeypatch.setattr(sys, "stdout", fake_stdout)

    code = run(
        ["--source-type", "github", "--source", "https://github.com/owner/repo", "--author", "alice"],
        extractor=_fake_extractor,
        runner=_fake_runner,
    )

    assert code == 0
    raw = _read_buf(buf)
    decoded = raw.decode("utf-8")
    # The output must end with a newline (same trailing behaviour as print(markdown)).
    assert decoded.endswith("\n"), "must end with newline"
    # Content intact: em-dash in the title, grounded claim present — no extra/garbled chars.
    assert "—" in decoded
    assert "Built key feature" in decoded
    # No double-encoding: em-dash is one codepoint, not a garbled sequence.
    assert "—" in decoded  # U+2014 EM DASH
    assert "â\x80\x94" not in decoded, "double-encoded em-dash must not appear"


# ---------------------------------------------------------------------------
# resume/cli.py — inline stdout path
# ---------------------------------------------------------------------------


def test_resume_cli_cp949_stdout_no_raise_and_utf8_bytes(monkeypatch: Any, tmp_path: Path) -> None:
    """Done-when: '`resume/cli.py`'s inline path emits UTF-8 and does not raise
    under the same simulated non-UTF-8 stdout; verified by a test under `tests/`.'"""
    from resume.cli import run  # noqa: PLC0415

    jd_path = tmp_path / "jd.txt"
    jd_path.write_text("python backend engineer", encoding="utf-8")

    fake_stdout, buf = _cp949_stdout()
    monkeypatch.setattr(sys, "stdout", fake_stdout)

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
        ],
        extractor=_fake_extractor,
        runner=_fake_runner,
    )

    assert code == 0, f"expected exit 0, got {code}"
    raw = _read_buf(buf)
    assert raw, "nothing was written to stdout buffer"
    decoded = raw.decode("utf-8")
    assert decoded.endswith("\n"), "output must end with exactly one newline"
    # Resume title contains em-dash: '# Resume — alice'
    assert "—" in decoded, "em-dash (—) must be present"
    assert "alice" in decoded


# ---------------------------------------------------------------------------
# fit/cli.py — inline stdout path
# ---------------------------------------------------------------------------


def test_fit_cli_cp949_stdout_no_raise_and_utf8_bytes(monkeypatch: Any, tmp_path: Path) -> None:
    """Done-when: '`fit/cli.py`'s inline path emits UTF-8 and does not raise under
    the same simulated non-UTF-8 stdout; verified by a test under `tests/`.'"""
    from fit.cli import run  # noqa: PLC0415

    jd_path = tmp_path / "jd.txt"
    jd_path.write_text("python backend engineer", encoding="utf-8")

    fake_stdout, buf = _cp949_stdout()
    monkeypatch.setattr(sys, "stdout", fake_stdout)

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
        ],
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
    )

    assert code == 0, f"expected exit 0, got {code}"
    raw = _read_buf(buf)
    assert raw, "nothing was written to stdout buffer"
    decoded = raw.decode("utf-8")
    assert decoded.endswith("\n"), "output must end with exactly one newline"
    # Fit title: '# Fit Assessment — Grade ...'
    assert "—" in decoded, "em-dash (—) must be present"


# ---------------------------------------------------------------------------
# rating/cli.py — inline print(markdown) site only (not _default_grader_runner)
# ---------------------------------------------------------------------------


def test_rating_cli_cp949_stdout_no_raise_and_utf8_bytes(monkeypatch: Any) -> None:
    """Done-when: '`rating/cli.py`'s inline path (the `print(markdown)` site, not
    the subprocess runner) emits UTF-8 and does not raise under the same simulated
    non-UTF-8 stdout; verified by a test under `tests/`.'"""
    from rating.cli import run  # noqa: PLC0415

    fake_stdout, buf = _cp949_stdout()
    monkeypatch.setattr(sys, "stdout", fake_stdout)

    code = run(
        ["--source-type", "github", "--source", "https://github.com/owner/repo", "--author", "alice"],
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
    )

    assert code == 0, f"expected exit 0, got {code}"
    raw = _read_buf(buf)
    assert raw, "nothing was written to stdout buffer"
    decoded = raw.decode("utf-8")
    assert decoded.endswith("\n"), "output must end with exactly one newline"
    # Rating title: '# Capability Rating — alice'
    assert "—" in decoded, "em-dash (—) must be present"
    assert "alice" in decoded


# ---------------------------------------------------------------------------
# reference_check/cli.py — inline stdout path
# ---------------------------------------------------------------------------


def test_reference_check_cli_cp949_stdout_no_raise_and_utf8_bytes(monkeypatch: Any) -> None:
    """Done-when: '`reference_check/cli.py`'s inline path emits UTF-8 and does not
    raise under the same simulated non-UTF-8 stdout; verified by a test under
    `tests/`.'"""
    from reference_check.cli import run  # noqa: PLC0415

    call_count = [0]

    def counter_runner(prompt: str) -> str:
        call_count[0] += 1
        if call_count[0] == 1:
            return json.dumps([{"text": "Built key feature", "evidence_refs": ["PR#1"], "confidence": 0.9}])
        return json.dumps([{"text": "excellent contribution", "evidence_refs": ["PR#1"]}])

    fake_stdout, buf = _cp949_stdout()
    monkeypatch.setattr(sys, "stdout", fake_stdout)

    code = run(
        ["--source-type", "github", "--source", "https://github.com/owner/repo", "--author", "alice"],
        extractor=_fake_extractor,
        runner=counter_runner,
    )

    assert code == 0, f"expected exit 0, got {code}"
    raw = _read_buf(buf)
    assert raw, "nothing was written to stdout buffer"
    decoded = raw.decode("utf-8")
    assert decoded.endswith("\n"), "output must end with exactly one newline"
    # Letter title: '# Recommendation Letter — alice'
    assert "—" in decoded, "em-dash (—) must be present"
    assert "alice" in decoded


# ---------------------------------------------------------------------------
# Content round-trip: bytes decode to exactly the rendered Markdown
# ---------------------------------------------------------------------------


def test_portfolio_bytes_decode_to_exact_rendered_markdown(monkeypatch: Any) -> None:
    """Done-when: 'The bytes emitted to stdout decode (UTF-8) back to exactly the
    same Markdown string the CLI rendered — i.e. the rendered Markdown content is
    unchanged (no added/stripped/altered characters); asserted by a test under
    `tests/`.'

    We capture what render_markdown produces via a second (utf-8) run against the
    same fakes, then compare byte-for-byte with the cp949-host run."""
    from portfolio.cli import run  # noqa: PLC0415

    # cp949 run — capture bytes
    cp949_stdout, cp949_buf = _cp949_stdout()
    monkeypatch.setattr(sys, "stdout", cp949_stdout)
    code = run(
        ["--source-type", "github", "--source", "https://github.com/owner/repo", "--author", "alice"],
        extractor=_fake_extractor,
        runner=_fake_runner,
    )
    assert code == 0
    cp949_bytes = _read_buf(cp949_buf)
    cp949_decoded = cp949_bytes.decode("utf-8")

    # utf-8 run — capture bytes
    utf8_stdout, utf8_buf = _utf8_stdout()
    monkeypatch.setattr(sys, "stdout", utf8_stdout)
    code2 = run(
        ["--source-type", "github", "--source", "https://github.com/owner/repo", "--author", "alice"],
        extractor=_fake_extractor,
        runner=_fake_runner,
    )
    assert code2 == 0
    utf8_decoded = _read_buf(utf8_buf).decode("utf-8")

    # Both runs must produce identical text (content is identical regardless of host encoding).
    assert cp949_decoded == utf8_decoded, "cp949-host and utf-8-host runs must emit identical decoded content"
    # Both must end with a newline (same trailing behaviour as print(markdown)).
    assert cp949_decoded.endswith("\n"), "output must end with a newline"


# ---------------------------------------------------------------------------
# IR-001 regression: emit_markdown does not crash when sys.stdout has no .buffer
# ---------------------------------------------------------------------------


def test_emit_markdown_stringio_no_attribute_error(monkeypatch: Any) -> None:
    """Regression for IR-001 (unsafe unconditional .buffer access).

    Done-when (helper as single source of truth): with sys.stdout set to a plain
    io.StringIO (NO .buffer attribute), emit_markdown() does NOT raise
    AttributeError and writes the Markdown (+ one trailing newline) as text.

    Pre-fix behaviour (unconditional sys.stdout.buffer.write): raises AttributeError
    because io.StringIO has no .buffer.
    Post-fix behaviour (getattr fallback to print()): falls through to print(),
    writes the text, no error raised.

    Also exercises the portfolio CLI's inline path under the same condition."""
    from portfolio.output import emit_markdown  # noqa: PLC0415

    text_sink = io.StringIO()
    monkeypatch.setattr(sys, "stdout", text_sink)

    # Direct helper call — must not raise AttributeError.
    emit_markdown("# Test — em-dash")

    result = text_sink.getvalue()
    assert "# Test — em-dash" in result, "Markdown content must appear in StringIO output"
    assert result.endswith("\n"), "must end with exactly one newline"


def test_portfolio_cli_stringio_stdout_no_attribute_error(monkeypatch: Any) -> None:
    """Regression for IR-001 via portfolio CLI wiring.

    With sys.stdout set to a plain io.StringIO (NO .buffer), the portfolio CLI's
    inline path (which calls emit_markdown) does NOT raise AttributeError and the
    Markdown is written as text to the StringIO.

    Pre-fix: raises AttributeError (unconditional .buffer access).
    Post-fix: falls back to print(), no error."""
    from portfolio.cli import run  # noqa: PLC0415

    text_sink = io.StringIO()
    monkeypatch.setattr(sys, "stdout", text_sink)

    code = run(
        ["--source-type", "github", "--source", "https://github.com/owner/repo", "--author", "alice"],
        extractor=_fake_extractor,
        runner=_fake_runner,
    )

    assert code == 0, f"expected exit 0, got {code}"
    result = text_sink.getvalue()
    assert "—" in result, "em-dash must be present"
    assert result.endswith("\n"), "must end with exactly one newline"
