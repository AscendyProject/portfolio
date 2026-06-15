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

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.cli import parse_github_source, run  # noqa: E402 — after sys.path setup per test-conventions
from portfolio.model import Evidence  # noqa: E402 — after sys.path setup per test-conventions


# ---------------------------------------------------------------------------
# Fakes (no live services)
# ---------------------------------------------------------------------------


def _fake_extractor(*, repo: str, author: str) -> list[Evidence]:
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
# Done-when: --source-type others is recognized but not supported yet
# ---------------------------------------------------------------------------


def test_others_source_type_not_supported(capsys):
    """ "`--source-type others` exits non-zero with the "not supported yet" message
    and produces no Markdown document"."""
    code = run(["--source-type", "others", "--source", "https://example.com/blog"], runner=_fake_runner)
    captured = capsys.readouterr()
    assert code != 0
    assert "not supported" in captured.err.lower()
    assert "# Portfolio" not in captured.out


# ---------------------------------------------------------------------------
# Done-when: an unparseable / non-GitHub source is rejected without extracting
# ---------------------------------------------------------------------------


def test_non_github_source_rejected_without_extracting(capsys):
    """ "a non-GitHub / unparseable `--source` URL exits non-zero with a clear error
    and never invokes the extractor"."""
    extractor, calls = _recording_extractor()
    code = run(
        ["--source-type", "github", "--source", "https://gitlab.com/owner/repo", "--author", "alice"],
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


# ---------------------------------------------------------------------------
# parse_github_source unit cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/owner/repo", "owner/repo"),
        ("https://github.com/owner/repo/", "owner/repo"),  # trailing slash
        ("https://github.com/owner/repo.git", "owner/repo"),  # .git suffix
        ("http://github.com/owner/repo", "owner/repo"),  # http accepted
    ],
)
def test_parse_github_source_accepts(url, expected):
    """A clean GitHub repo URL parses to owner/repo (trailing slash / .git / http tolerated)."""
    assert parse_github_source(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://gitlab.com/owner/repo",  # wrong host
        "https://github.com/owner",  # missing repo
        "https://github.com/owner/repo/pull/1",  # extra path segments -> reject, don't guess
        "https://github.com/owner//repo",  # empty middle segment -> reject, don't collapse
        "https://github.com/owner/%2Frepo",  # %-encoded separator -> not a clean name
        "https://github.com/owner/re po",  # whitespace in name
        "https://github.com/owner/repo?x=1",  # query string -> reject
        "https://github.com/owner/..",  # dot segment -> never a real name
        "https://github.com/./repo",  # dot segment -> never a real name
        "git@github.com:owner/repo.git",  # ssh form, not http(s)
        "owner/repo",  # no scheme/host
        "",  # empty
    ],
)
def test_parse_github_source_rejects(url):
    """A URL that is not a clean GitHub owner/repo is rejected (raise rather than guess)."""
    with pytest.raises(ValueError):
        parse_github_source(url)
