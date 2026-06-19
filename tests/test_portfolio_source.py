"""Tests for --source-type portfolio: load + re-ground, no narration.

Each test traces to a Done-when item in outcome.md via its docstring.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.model import Claim, Evidence, Portfolio  # noqa: E402
from portfolio.sources import SourceRequest, known_source_types, resolve_source  # noqa: E402
from portfolio.store import portfolio_to_json  # noqa: E402


_REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_portfolio(subject: str = "alice") -> Portfolio:
    evidence = [
        Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="Add thing", context=""),
        Evidence(kind="commit", ref="abc123", url="", detail="Fix", context=""),
    ]
    claims = [
        Claim(text="Built the thing", evidence_refs=["PR#1"], confidence=0.9, grounded=True),
        Claim(text="Fixed bug", evidence_refs=["abc123"], confidence=0.8, grounded=True),
    ]
    return Portfolio(subject=subject, evidence=evidence, claims=claims)


def _write_portfolio(tmp_path: Path, p: Portfolio) -> Path:
    f = tmp_path / "portfolio.json"
    f.write_text(portfolio_to_json(p), encoding="utf-8")
    return f


# ---------------------------------------------------------------------------
# Done-when: sources registration
# ---------------------------------------------------------------------------


def test_portfolio_in_known_source_types():
    """'portfolio' appears in known_source_types()."""
    assert "portfolio" in known_source_types()


# ---------------------------------------------------------------------------
# Done-when: prebuilt seam not set for legacy sources
# ---------------------------------------------------------------------------


def test_github_handler_prebuilt_is_none():
    """_github_handler / _web_handler / _github_author_handler return ResolvedSource
    whose prebuilt slot is None / unset."""
    from portfolio.sources import _HANDLERS

    # github
    req = SourceRequest(source="https://github.com/owner/repo", author="alice")
    resolved = _HANDLERS["github"](req)
    assert getattr(resolved, "prebuilt", None) is None

    # web
    req_web = SourceRequest(source="https://blog.example.com/post", author="alice")
    resolved_web = _HANDLERS["web"](req_web)
    assert getattr(resolved_web, "prebuilt", None) is None

    # github-author
    req_author = SourceRequest(source=None, author="alice")
    resolved_author = _HANDLERS["github-author"](req_author)
    assert getattr(resolved_author, "prebuilt", None) is None


# ---------------------------------------------------------------------------
# Done-when: re-grounding on load
# ---------------------------------------------------------------------------


def test_regrounding_drops_hallucinated_ref_claim(tmp_path):
    """A fixture JSON whose claims cite a ref not present in the JSON's evidence list →
    after resolve_source + downstream helper, the offending claim is absent from Portfolio.claims."""
    # Build a portfolio with a claim that has a hallucinated ref (not in evidence)
    evidence = [Evidence(kind="pr", ref="PR#1", url="", detail="", context="")]
    claims = [
        Claim(text="Real claim", evidence_refs=["PR#1"], confidence=0.9, grounded=True),
        Claim(text="Hallucinated claim", evidence_refs=["PR#999"], confidence=0.9, grounded=True),
    ]
    p = Portfolio(subject="alice", evidence=evidence, claims=claims)
    # Write it (note: portfolio_to_json serializes as-is, grounded=True even for bad ref)
    saved = tmp_path / "portfolio.json"
    saved.write_text(portfolio_to_json(p), encoding="utf-8")

    # Load via resolve_source — the re-grounding step should drop PR#999 claim
    resolved = resolve_source("portfolio", SourceRequest(source=str(saved), author=None))
    assert resolved.prebuilt is not None
    from portfolio.pipeline import resolve_to_build_result

    def never_called(_prompt):
        raise AssertionError("narration runner must not be called")

    result = resolve_to_build_result(resolved, subject=resolved.subject, runner=never_called)
    claim_texts = [c.text for c in result.portfolio.claims]
    assert "Real claim" in claim_texts
    assert "Hallucinated claim" not in claim_texts


# ---------------------------------------------------------------------------
# Done-when: --author ignored on portfolio source
# ---------------------------------------------------------------------------


def test_author_ignored_portfolio_source(tmp_path):
    """A portfolio JSON with subject='alice', run with --author bob, still produces
    a Portfolio whose subject is 'alice'."""
    p = _make_portfolio(subject="alice")
    saved = _write_portfolio(tmp_path, p)

    resolved = resolve_source("portfolio", SourceRequest(source=str(saved), author="bob"))
    assert resolved.subject == "alice"
    assert resolved.prebuilt is not None
    assert resolved.prebuilt.subject == "alice"


# ---------------------------------------------------------------------------
# Done-when: clean errors from portfolio source
# ---------------------------------------------------------------------------


def test_missing_source_raises_value_error():
    """Missing --source → ValueError."""
    with pytest.raises(ValueError, match="--source"):
        resolve_source("portfolio", SourceRequest(source=None, author=None))


def test_nonexistent_path_raises_value_error(tmp_path):
    """Source path does not exist → ValueError."""
    with pytest.raises(ValueError, match="not found"):
        resolve_source("portfolio", SourceRequest(source=str(tmp_path / "nonexistent.json"), author=None))


def test_invalid_json_raises_value_error(tmp_path):
    """File is not valid JSON → ValueError."""
    bad = tmp_path / "bad.json"
    bad.write_text("not json at all", encoding="utf-8")
    with pytest.raises(ValueError):
        resolve_source("portfolio", SourceRequest(source=str(bad), author=None))


def test_bad_schema_raises_value_error(tmp_path):
    """File fails PortfolioStoreError validation → ValueError."""
    bad = tmp_path / "bad_schema.json"
    bad.write_text('{"schema_version": 99, "subject": "x", "evidence": [], "claims": []}', encoding="utf-8")
    with pytest.raises(ValueError):
        resolve_source("portfolio", SourceRequest(source=str(bad), author=None))


# ---------------------------------------------------------------------------
# Done-when: narration runner never called for portfolio source (portfolio CLI)
# ---------------------------------------------------------------------------


def test_portfolio_cli_narration_runner_not_called(tmp_path, capsys):
    """portfolio CLI invoked with --source-type portfolio and a raise-on-call runner → returns 0."""
    from portfolio.cli import run

    p = _make_portfolio()
    saved = _write_portfolio(tmp_path, p)

    def raise_on_call(_prompt):
        raise AssertionError("narration runner must not be called")

    code = run(
        ["--source-type", "portfolio", "--source", str(saved)],
        runner=raise_on_call,
    )
    capsys.readouterr()
    assert code == 0


# ---------------------------------------------------------------------------
# Done-when: narration runner never called (resume CLI)
# ---------------------------------------------------------------------------


def test_resume_cli_narration_runner_not_called(tmp_path, capsys):
    """resume CLI invoked with --source-type portfolio and a raise-on-call runner → returns 0."""
    from resume.cli import run

    p = _make_portfolio()
    saved = _write_portfolio(tmp_path, p)

    jd = tmp_path / "jd.txt"
    jd.write_text("python backend engineer", encoding="utf-8")

    def raise_on_call(_prompt):
        raise AssertionError("narration runner must not be called")

    code = run(
        ["--source-type", "portfolio", "--source", str(saved), "--jd", str(jd)],
        runner=raise_on_call,
    )
    capsys.readouterr()
    assert code == 0


# ---------------------------------------------------------------------------
# Done-when: narration runner never called (fit CLI)
# ---------------------------------------------------------------------------


def test_fit_cli_narration_runner_not_called(tmp_path, capsys):
    """fit CLI invoked with --source-type portfolio and a raise-on-call runner → returns 0."""
    from fit.cli import run
    import json as _json

    p = _make_portfolio()
    saved = _write_portfolio(tmp_path, p)

    jd = tmp_path / "jd.txt"
    jd.write_text("python backend engineer", encoding="utf-8")

    def raise_on_call(_prompt):
        raise AssertionError("narration runner must not be called")

    def fake_grader(prompt, *, temperature=0):
        return _json.dumps({"score": 80, "reasoning": [{"text": "good", "evidence_refs": ["PR#1"]}]})

    code = run(
        ["--source-type", "portfolio", "--source", str(saved), "--jd", str(jd)],
        runner=raise_on_call,
        grader_runner=fake_grader,
    )
    capsys.readouterr()
    assert code == 0


# ---------------------------------------------------------------------------
# Done-when: narration runner never called (rating CLI)
# ---------------------------------------------------------------------------


def test_rating_cli_narration_runner_not_called(tmp_path, capsys):
    """rating CLI invoked with --source-type portfolio and a raise-on-call runner → returns 0."""
    from rating.cli import run
    import json as _json

    p = _make_portfolio()
    saved = _write_portfolio(tmp_path, p)

    def raise_on_call(_prompt):
        raise AssertionError("narration runner must not be called")

    def fake_grader(prompt, temperature=0):
        return _json.dumps({"score": 40, "reasoning": [{"text": "ok", "evidence_refs": ["PR#1"]}]})

    code = run(
        ["--source-type", "portfolio", "--source", str(saved)],
        runner=raise_on_call,
        grader_runner=fake_grader,
    )
    capsys.readouterr()
    assert code == 0


@pytest.mark.parametrize(
    "payload,as_bytes",
    [
        ("this is not json at all", False),  # invalid JSON
        ('{"schema_version": 2, "subject": "a", "evidence": [], "claims": []}', False),  # bad schema
        (b"\xff\xfe not valid utf-8", True),  # invalid UTF-8 bytes
    ],
)
def test_portfolio_cli_malformed_source_exits_2(tmp_path, capsys, payload, as_bytes):
    """A malformed portfolio file (invalid JSON / bad schema / invalid UTF-8) reaches the
    CLI exit-2 boundary with a clean message, never a traceback; the narration runner is
    never called (failure happens at source resolution)."""
    from portfolio.cli import run

    bad = tmp_path / "bad.json"
    if as_bytes:
        bad.write_bytes(payload)
    else:
        bad.write_text(payload, encoding="utf-8")

    def raise_on_call(_prompt):
        raise AssertionError("narration runner must not be called for a malformed source")

    code = run(["--source-type", "portfolio", "--source", str(bad)], runner=raise_on_call)
    err = capsys.readouterr().err
    assert code == 2
    assert err.strip()  # a human-readable message, not an empty output or a traceback


# ---------------------------------------------------------------------------
# Done-when: grader seams preserved (fit)
# ---------------------------------------------------------------------------


def test_fit_grader_seam_called_with_portfolio(tmp_path, capsys):
    """fit CLI with --source-type portfolio still calls grader_runner against the loaded Portfolio."""
    from fit.cli import run
    import json as _json

    p = _make_portfolio()
    saved = _write_portfolio(tmp_path, p)

    jd = tmp_path / "jd.txt"
    jd.write_text("python backend engineer", encoding="utf-8")

    grader_calls = []

    def recording_grader(prompt, *, temperature=0):
        grader_calls.append(prompt)
        return _json.dumps({"score": 80, "reasoning": [{"text": "good", "evidence_refs": ["PR#1"]}]})

    code = run(
        ["--source-type", "portfolio", "--source", str(saved), "--jd", str(jd)],
        runner=lambda _p: "[]",
        grader_runner=recording_grader,
    )
    capsys.readouterr()
    assert code == 0
    assert len(grader_calls) == 1


# ---------------------------------------------------------------------------
# Done-when: grader seams preserved (rating)
# ---------------------------------------------------------------------------


def test_rating_grader_seam_called_with_portfolio(tmp_path, capsys):
    """rating CLI with --source-type portfolio still calls grader_runner against the loaded Portfolio."""
    from rating.cli import run
    import json as _json

    p = _make_portfolio()
    saved = _write_portfolio(tmp_path, p)

    grader_calls = []

    def recording_grader(prompt, temperature=0):
        grader_calls.append(prompt)
        return _json.dumps({"score": 40, "reasoning": [{"text": "ok", "evidence_refs": ["PR#1"]}]})

    code = run(
        ["--source-type", "portfolio", "--source", str(saved)],
        runner=lambda _p: "[]",
        grader_runner=recording_grader,
    )
    capsys.readouterr()
    assert code == 0
    assert len(grader_calls) == 1


# ---------------------------------------------------------------------------
# Done-when: --jd still required for resume and fit with --source-type portfolio
# ---------------------------------------------------------------------------


def test_resume_jd_still_required(tmp_path, capsys):
    """Omitting --jd while passing --source-type portfolio to resume causes argparse to exit 2."""
    from resume.cli import run

    p = _make_portfolio()
    saved = _write_portfolio(tmp_path, p)

    with pytest.raises(SystemExit) as exc_info:
        run(["--source-type", "portfolio", "--source", str(saved)], runner=lambda _p: "[]")
    assert exc_info.value.code == 2


def test_fit_jd_still_required(tmp_path, capsys):
    """Omitting --jd while passing --source-type portfolio to fit causes argparse to exit 2."""
    from fit.cli import run

    p = _make_portfolio()
    saved = _write_portfolio(tmp_path, p)

    code = run(["--source-type", "portfolio", "--source", str(saved)], runner=lambda _p: "[]")
    assert code == 2


# ---------------------------------------------------------------------------
# Done-when: reference_check narration skipped, letter composition still runs
# ---------------------------------------------------------------------------


def test_reference_check_narration_skipped_letter_runs_prompt_aware(tmp_path, capsys):
    """PR-006(a): prompt-aware runner asserting 'GROUNDED CLAIMS' in prompt on every call →
    CLI returns 0, proving every call was a letter call, never a narration call."""
    from reference_check.cli import run

    p = _make_portfolio()
    saved = _write_portfolio(tmp_path, p)

    def prompt_aware_runner(prompt: str) -> str:
        assert "GROUNDED CLAIMS" in prompt, f"expected letter prompt, got: {prompt[:100]!r}"
        return json.dumps([{"text": "excellent contribution", "evidence_refs": ["PR#1"]}])

    code = run(
        ["--source-type", "portfolio", "--source", str(saved)],
        runner=prompt_aware_runner,
    )
    capsys.readouterr()
    assert code == 0


def test_reference_check_counting_runner_called_exactly_once(tmp_path, capsys):
    """PR-006(b): counting runner returning stub paragraph JSON → CLI returns 0 and call count == 1."""
    from reference_check.cli import run

    p = _make_portfolio()
    saved = _write_portfolio(tmp_path, p)

    call_count = [0]

    def counting_runner(prompt: str) -> str:
        call_count[0] += 1
        return json.dumps([{"text": "great work", "evidence_refs": ["PR#1"]}])

    code = run(
        ["--source-type", "portfolio", "--source", str(saved)],
        runner=counting_runner,
    )
    capsys.readouterr()
    assert code == 0
    assert call_count[0] == 1


def test_reference_check_raise_on_call_runner_exits_nonzero(tmp_path, capsys):
    """PR-006(c): runner that raises RuntimeError → CLI exits non-zero through build_letter exception boundary."""
    from reference_check.cli import run

    p = _make_portfolio()
    saved = _write_portfolio(tmp_path, p)

    def raise_runner(prompt: str) -> str:
        raise RuntimeError("called")

    code = run(
        ["--source-type", "portfolio", "--source", str(saved)],
        runner=raise_runner,
    )
    capsys.readouterr()
    assert code != 0


# ---------------------------------------------------------------------------
# Done-when: PR-002 portfolio CLI accepts --source-type portfolio
# ---------------------------------------------------------------------------


def test_portfolio_cli_source_type_portfolio_byte_identical_markdown(tmp_path, capsys):
    """PR-002: python -m portfolio --source-type portfolio --source <saved.json> returns 0,
    narration runner is not called, and produced Markdown equals the originating run's Markdown."""
    from portfolio.cli import run
    import json as _json

    evidence = [Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="Add thing", context="")]

    def fake_extractor(*, repo, author):
        return evidence

    def fake_runner(_prompt):
        return _json.dumps([{"text": "Built the thing", "evidence_refs": ["PR#1"], "confidence": 0.9}])

    # First run: emit to JSON
    emit_path = tmp_path / "saved.json"
    code1 = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/owner/repo",
            "--author",
            "alice",
            "--emit-portfolio",
            str(emit_path),
        ],
        extractor=fake_extractor,
        runner=fake_runner,
    )
    captured1 = capsys.readouterr()
    assert code1 == 0
    md1 = captured1.out

    def raise_on_call(_prompt):
        raise AssertionError("narration runner must not be called")

    # Second run: re-render from saved JSON
    code2 = run(
        ["--source-type", "portfolio", "--source", str(emit_path)],
        runner=raise_on_call,
    )
    captured2 = capsys.readouterr()
    assert code2 == 0
    md2 = captured2.out
    assert md1 == md2


# ---------------------------------------------------------------------------
# Done-when: --emit-portfolio works independently of --out
# ---------------------------------------------------------------------------


def test_emit_portfolio_independent_of_out(tmp_path, capsys):
    """--emit-portfolio is independent of --out: write JSON file (and optionally Markdown file)."""
    from portfolio.cli import run
    import json as _json

    evidence = [Evidence(kind="pr", ref="PR#1", url="", detail="", context="")]

    def fake_extractor(*, repo, author):
        return evidence

    def fake_runner(_prompt):
        return _json.dumps([{"text": "Built thing", "evidence_refs": ["PR#1"], "confidence": 0.9}])

    emit_path = tmp_path / "out.json"
    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/owner/repo",
            "--author",
            "alice",
            "--emit-portfolio",
            str(emit_path),
        ],
        extractor=fake_extractor,
        runner=fake_runner,
    )
    capsys.readouterr()
    assert code == 0
    assert emit_path.exists()

    from portfolio.store import portfolio_from_json

    loaded = portfolio_from_json(emit_path.read_text(encoding="utf-8"))
    assert loaded.subject == "alice"


def test_emit_portfolio_oserror_exits_2(tmp_path, capsys):
    """OSError writing --emit-portfolio file → portfolio.cli.run returns 2 with single-line stderr."""
    from portfolio.cli import run
    import json as _json

    evidence = [Evidence(kind="pr", ref="PR#1", url="", detail="", context="")]

    def fake_extractor(*, repo, author):
        return evidence

    def fake_runner(_prompt):
        return _json.dumps([{"text": "Built thing", "evidence_refs": ["PR#1"], "confidence": 0.9}])

    # Use a path under a non-existent directory to force OSError
    bad_path = tmp_path / "nonexistent_dir" / "out.json"

    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/owner/repo",
            "--author",
            "alice",
            "--emit-portfolio",
            str(bad_path),
        ],
        extractor=fake_extractor,
        runner=fake_runner,
    )
    captured = capsys.readouterr()
    assert code == 2
    err_lines = [line for line in captured.err.splitlines() if line.strip()]
    assert len(err_lines) == 1 or "Traceback" not in captured.err


# ---------------------------------------------------------------------------
# Done-when: clean error from portfolio source via CLI (exit 2, single-line stderr, no traceback)
# ---------------------------------------------------------------------------


def test_portfolio_source_missing_file_cli_exit2(tmp_path, capsys):
    """Source path does not exist → exit 2 with single-line stderr (no traceback) via portfolio CLI."""
    from portfolio.cli import run

    code = run(
        ["--source-type", "portfolio", "--source", str(tmp_path / "nonexistent.json")],
        runner=lambda _p: "[]",
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "Traceback" not in captured.err
    assert captured.err.strip() != ""
