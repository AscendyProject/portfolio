"""Tests for the CLI entrypoint (`python -m portfolio`).

The CLI wires extract -> narrate -> ground -> render for a GitHub source. Per
test-conventions, no live `gh`/`claude` is used: a fake `extractor` and a fake
`runner` are injected into `run()`, and `Evidence`/`Claim` objects are built
directly.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.cli import run  # noqa: E402 — after sys.path setup per test-conventions
from portfolio.model import Evidence  # noqa: E402 — after sys.path setup per test-conventions


# ---------------------------------------------------------------------------
# Fakes (no live services)
# ---------------------------------------------------------------------------


def _fake_extractor(*, repo: str, author: str, limit: int = 100) -> list[Evidence]:
    """Stand-in for extract_merged_prs: returns canned Evidence, no network."""
    return [Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="Add thing")]


def _fake_runner(_prompt: str) -> str:
    """Stand-in model runner: returns one claim citing the real ref PR#1."""
    return json.dumps([{"text": "Built the thing", "evidence_refs": ["PR#1"], "confidence": 0.9}])


def _recording_extractor():
    """An extractor that records the kwargs it was called with."""
    calls: list[dict] = []

    def extractor(**kwargs) -> list[Evidence]:
        calls.append(kwargs)
        return [Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1")]

    return extractor, calls


def _github_argv(out: str | None = None) -> list[str]:
    argv = ["--source-type", "github", "--source", "https://github.com/owner/repo", "--author", "alice"]
    if out is not None:
        argv += ["--out", out]
    return argv


# ---------------------------------------------------------------------------
# Done-when: a github run renders subject + grounded claims to stdout
# ---------------------------------------------------------------------------


def test_github_run_renders_markdown_to_stdout(capsys):
    """ "a github run renders the subject + grounded claims to stdout"."""
    code = run(_github_argv(), extractor=_fake_extractor, runner=_fake_runner)
    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("# Portfolio")
    assert "alice" in out  # subject
    assert "Built the thing" in out  # the grounded claim


# ---------------------------------------------------------------------------
# Done-when: writes to a file when --out is given (and not to stdout)
# ---------------------------------------------------------------------------


def test_out_file_written_not_stdout(tmp_path, capsys):
    """ "writes to a file when `--out` is given"."""
    target = tmp_path / "portfolio.md"
    code = run(_github_argv(out=str(target)), extractor=_fake_extractor, runner=_fake_runner)
    out = capsys.readouterr().out
    assert code == 0
    assert target.read_text(encoding="utf-8").startswith("# Portfolio")
    assert "Built the thing" in target.read_text(encoding="utf-8")
    assert "# Portfolio" not in out  # document went to the file, not stdout


# ---------------------------------------------------------------------------
# Done-when: grounding summary goes to stderr, not into the Markdown
# ---------------------------------------------------------------------------


def test_grounding_summary_on_stderr_not_in_document(capsys):
    """ "the grounding summary ... is emitted to stderr, not into the Markdown"."""
    code = run(_github_argv(), extractor=_fake_extractor, runner=_fake_runner)
    captured = capsys.readouterr()
    assert code == 0
    # the summary reports exact counts for ALL three partitions on stderr
    err = captured.err.lower()
    assert "grounded: 1" in err
    assert "rejected: 0" in err
    assert "needs-confirmation: 0" in err
    # but the rendered document (stdout) must not carry the summary line
    assert "grounded:" not in captured.out.lower()


def _mixed_runner(_prompt: str) -> str:
    """A runner that drafts three claims: one grounded, one citing a hallucinated
    ref (PR#999, absent from the evidence), one grounded-but-needs-confirmation."""
    return json.dumps(
        [
            {"text": "GROUNDED-CLAIM", "evidence_refs": ["PR#1"], "confidence": 0.9},
            {"text": "HALLUCINATED-CLAIM", "evidence_refs": ["PR#999"], "confidence": 0.9},
            {
                "text": "NEEDS-CONFIRM-CLAIM",
                "evidence_refs": ["PR#1"],
                "confidence": 0.5,
                "needs_user_confirmation": True,
            },
        ]
    )


def test_grounding_boundary_only_grounded_claims_rendered(capsys):
    """The CLI renders ONLY grounded claims: a hallucinated-ref claim and a
    needs-confirmation claim are kept out of the Markdown but still counted on
    stderr — the product's core trust gate, enforced at the CLI wiring level."""
    code = run(_github_argv(), extractor=_fake_extractor, runner=_mixed_runner)
    captured = capsys.readouterr()
    assert code == 0
    # only the grounded claim reaches the rendered document
    assert "GROUNDED-CLAIM" in captured.out
    assert "HALLUCINATED-CLAIM" not in captured.out
    assert "NEEDS-CONFIRM-CLAIM" not in captured.out
    # but all three partitions are reported on stderr
    err = captured.err.lower()
    assert "grounded: 1" in err
    assert "rejected: 1" in err
    assert "needs-confirmation: 1" in err


# ---------------------------------------------------------------------------
# Done-when: a `web` run renders the article as grounded evidence (injected fetcher)
# ---------------------------------------------------------------------------


def test_web_run_renders_with_injected_fetcher(capsys):
    """A `--source-type web` run fetches via the injected fetcher, and a claim citing
    the article ref renders — proving the second source works end-to-end."""

    def fake_fetcher(_url: str) -> str:
        return "<html><head><title>My Post</title></head><body>x</body></html>"

    def web_runner(_prompt: str) -> str:
        return json.dumps(
            [{"text": "Wrote My Post", "evidence_refs": ["https://blog.example.com/post"], "confidence": 0.8}]
        )

    code = run(
        ["--source-type", "web", "--source", "https://blog.example.com/post", "--author", "alice"],
        runner=web_runner,
        fetcher=fake_fetcher,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("# Portfolio")
    assert "Wrote My Post" in out  # the grounded claim citing the article


# ---------------------------------------------------------------------------
# Done-when: an unparseable / malformed source is rejected without extracting
# ---------------------------------------------------------------------------


def test_limit_flag_threaded_to_extractor():
    """`--limit N` reaches the extractor as limit=N."""
    extractor, calls = _recording_extractor()
    code = run(_github_argv() + ["--limit", "300"], extractor=extractor, runner=_fake_runner)
    assert code == 0
    assert calls[0]["limit"] == 300


def test_default_limit_is_100():
    """Without --limit, the extractor is called with the 100 default."""
    extractor, calls = _recording_extractor()
    code = run(_github_argv(), extractor=extractor, runner=_fake_runner)
    assert code == 0
    assert calls[0]["limit"] == 100


def test_invalid_limit_rejected_without_extracting(capsys):
    """`--limit 0` exits non-zero with a clear error and never extracts."""
    extractor, calls = _recording_extractor()
    code = run(_github_argv() + ["--limit", "0"], extractor=extractor, runner=_fake_runner)
    captured = capsys.readouterr()
    assert code == 2
    assert "limit" in captured.err.lower()
    assert calls == []


def test_non_github_source_rejected_without_extracting(capsys):
    """ "a malformed / unparseable `--source` URL exits non-zero with a clear error
    and never invokes the extractor"."""
    extractor, calls = _recording_extractor()
    code = run(
        ["--source-type", "github", "--source", "https://github.com/owner", "--author", "alice"],  # missing repo
        extractor=extractor,
        runner=_fake_runner,
    )
    captured = capsys.readouterr()
    assert code != 0
    assert captured.err.strip() != ""  # a clear error message
    assert calls == []  # extractor never invoked
    assert "# Portfolio" not in captured.out


# ---------------------------------------------------------------------------
# Done-when: a valid GitHub URL parses to owner/repo and is passed to extractor
# ---------------------------------------------------------------------------


def test_extractor_failure_exits_cleanly_not_traceback(capsys):
    """An unexpected extractor/pipeline failure (e.g. a shape error on malformed
    gh JSON) becomes a clean non-zero exit with a stderr message, not a traceback."""

    def boom(**_kwargs):
        raise TypeError("'int' object is not subscriptable")  # simulates a shape error

    code = run(_github_argv(), extractor=boom, runner=_fake_runner)
    captured = capsys.readouterr()
    assert code == 1
    assert "failed to build portfolio" in captured.err.lower()
    assert "# Portfolio" not in captured.out


def test_valid_github_url_passed_as_owner_repo(capsys):
    """ "a valid `https://github.com/<owner>/<repo>` URL parses to `owner/repo` and
    is passed to the injected extractor"."""
    extractor, calls = _recording_extractor()
    code = run(_github_argv(), extractor=extractor, runner=_fake_runner)
    capsys.readouterr()
    assert code == 0
    assert len(calls) == 1
    assert calls[0]["repo"] == "owner/repo"
    assert calls[0]["author"] == "alice"


def test_registered_handler_is_usable_through_the_cli(capsys):
    """End-to-end seam: registering a handler in the dispatcher makes a new source
    type usable via `--source-type` through argparse, with NO change to the CLI —
    the dispatcher derives its choices from the registry."""
    from portfolio.model import Evidence as _Evidence
    from portfolio.sources import _HANDLERS, ResolvedSource

    _HANDLERS["fake"] = lambda _req: ResolvedSource(subject="zoe", extract=lambda: [_Evidence(kind="pr", ref="PR#1")])
    try:
        code = run(["--source-type", "fake"], extractor=_fake_extractor, runner=_fake_runner)
    finally:
        del _HANDLERS["fake"]
    out = capsys.readouterr().out
    assert code == 0  # argparse accepted "fake" and the handler was dispatched
    assert out.startswith("# Portfolio")
    assert "zoe" in out  # subject came from the registered handler


# ---------------------------------------------------------------------------
# Done-when: --show-refs flag hides refs by default, reveals them when passed
# ---------------------------------------------------------------------------


def test_show_refs_default_hides_refs(capsys):
    """'With --show-refs omitted, stdout contains no Evidence: block or inline ref text.'"""
    code = run(_github_argv(), extractor=_fake_extractor, runner=_fake_runner)
    captured = capsys.readouterr()
    assert code == 0
    # No Evidence block, no raw ref numbers from the Evidence sub-list
    assert "Evidence:" not in captured.out
    # The ref PR#1 should NOT appear as a sub-item (only in stats line as "1 merged PRs")
    assert "PR\\#1" not in captured.out
    assert "https://github.com/o/r/pull/1" not in captured.out


def test_show_refs_flag_reveals_refs(capsys):
    """'With --show-refs, stdout contains the Evidence: block and ref text.'"""
    argv = _github_argv() + ["--show-refs"]
    code = run(argv, extractor=_fake_extractor, runner=_fake_runner)
    captured = capsys.readouterr()
    assert code == 0
    # Evidence block present and ref appears
    assert "Evidence:" in captured.out
    assert "PR" in captured.out


def test_show_refs_grounding_summary_unchanged(capsys):
    """'stderr grounded/rejected/needs-confirmation summary appears with and without --show-refs.'"""
    # Without --show-refs
    run(_github_argv(), extractor=_fake_extractor, runner=_fake_runner)
    err1 = capsys.readouterr().err.lower()
    assert "grounded:" in err1 and "rejected:" in err1 and "needs-confirmation:" in err1

    # With --show-refs
    run(_github_argv() + ["--show-refs"], extractor=_fake_extractor, runner=_fake_runner)
    err2 = capsys.readouterr().err.lower()
    assert "grounded:" in err2 and "rejected:" in err2 and "needs-confirmation:" in err2
