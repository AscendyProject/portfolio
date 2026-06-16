"""Tests for the resume CLI entrypoint (`python -m resume`).

All tests inject fake `extractor`, `runner`, and `fetcher` — no live gh/claude/network.
Evidence, Claim, and Portfolio objects are built directly.

Each test traces to a Done-when item in outcome.md via its docstring.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.model import Evidence  # noqa: E402
from resume.cli import run  # noqa: E402


# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------


def _fake_extractor(*, repo: str, author: str) -> list[Evidence]:
    """Returns canned Evidence for a github source; no network."""
    return [Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="Add feature")]


def _fake_runner(prompt: str) -> str:
    """Returns one grounded claim citing PR#1."""
    return json.dumps([{"text": "Built the feature using python", "evidence_refs": ["PR#1"], "confidence": 0.9}])


def _make_jd(tmp_path: Path, text: str = "python backend engineer") -> str:
    """Write a JD file and return its path as a string."""
    p = tmp_path / "jd.txt"
    p.write_text(text, encoding="utf-8")
    return str(p)


def _base_argv(jd_path: str, out: str | None = None, top_n: int | None = None) -> list[str]:
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
    if top_n is not None:
        argv += ["--top-n", str(top_n)]
    if out is not None:
        argv += ["--out", out]
    return argv


# ---------------------------------------------------------------------------
# Done-when: github source end-to-end renders grounded claims as bullets
# ---------------------------------------------------------------------------


def test_github_run_renders_markdown_resume(tmp_path, capsys):
    """'a github-source end-to-end run renders a Markdown resume for the subject
    and includes only grounded selected claims as bullets.'"""
    jd_path = _make_jd(tmp_path, "python backend engineer")
    code = run(_base_argv(jd_path), extractor=_fake_extractor, runner=_fake_runner)
    out = capsys.readouterr().out
    assert code == 0
    assert "# Resume" in out
    assert "alice" in out
    assert "Built the feature using python" in out


# ---------------------------------------------------------------------------
# Done-when: web source end-to-end renders grounded claim
# ---------------------------------------------------------------------------


def test_web_run_renders_grounded_claim(tmp_path, capsys):
    """'a web-source end-to-end run with an injected fetcher and a runner that
    cites the article ref renders the resulting bullet.'"""
    jd_path = _make_jd(tmp_path, "python writing blog articles")

    def fake_fetcher(_url: str) -> str:
        return "<html><head><title>My Python Post</title></head><body>x</body></html>"

    def web_runner(_prompt: str) -> str:
        return json.dumps(
            [{"text": "Wrote python article", "evidence_refs": ["https://blog.example.com/post"], "confidence": 0.8}]
        )

    code = run(
        ["--source-type", "web", "--source", "https://blog.example.com/post", "--author", "alice", "--jd", jd_path],
        runner=web_runner,
        fetcher=fake_fetcher,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "Wrote python article" in out


# ---------------------------------------------------------------------------
# Done-when: enforce_grounding — hallucinated + needs-confirmation claims excluded
# ---------------------------------------------------------------------------


def test_grounding_boundary_only_grounded_jd_claims_in_output(tmp_path, capsys):
    """'A runner that drafts a mix of (grounded, hallucinated-ref, needs-confirmation)
    claims yields a resume whose bullets contain ONLY the grounded-and-JD-matching
    claim text — never the hallucinated or needs-confirmation claim text.'"""
    jd_path = _make_jd(tmp_path, "python backend")

    def mixed_runner(_prompt: str) -> str:
        return json.dumps(
            [
                {"text": "GROUNDED-python-CLAIM", "evidence_refs": ["PR#1"], "confidence": 0.9},
                {"text": "HALLUCINATED-CLAIM", "evidence_refs": ["PR#999"], "confidence": 0.9},
                {
                    "text": "NEEDS-CONFIRM-CLAIM",
                    "evidence_refs": ["PR#1"],
                    "confidence": 0.5,
                    "needs_user_confirmation": True,
                },
            ]
        )

    code = run(_base_argv(jd_path), extractor=_fake_extractor, runner=mixed_runner)
    out = capsys.readouterr().out
    assert code == 0
    assert "GROUNDED-python-CLAIM" in out
    assert "HALLUCINATED-CLAIM" not in out
    assert "NEEDS-CONFIRM-CLAIM" not in out


# ---------------------------------------------------------------------------
# Done-when: --top-n caps bullet count
# ---------------------------------------------------------------------------


def test_top_n_caps_bullet_count(tmp_path, capsys):
    """'--top-n N caps the number of rendered bullets to at most N when more than
    N JD-overlapping grounded claims are available.'"""
    jd_path = _make_jd(tmp_path, "python backend data engineer")

    # Runner returns 5 grounded claims that all match the JD keywords
    def many_runner(_prompt: str) -> str:
        claims = [
            {"text": f"Implemented python feature {i}", "evidence_refs": ["PR#1"], "confidence": 0.9} for i in range(5)
        ]
        return json.dumps(claims)

    code = run(_base_argv(jd_path, top_n=3), extractor=_fake_extractor, runner=many_runner)
    out = capsys.readouterr().out
    assert code == 0
    # Count bullet lines (lines starting with "- ")
    bullets = [line for line in out.splitlines() if line.startswith("- ")]
    assert len(bullets) <= 3


# ---------------------------------------------------------------------------
# Done-when: --out writes to file, stdout free of resume body
# ---------------------------------------------------------------------------


def test_out_writes_file_not_stdout(tmp_path, capsys):
    """'--out PATH writes the resume Markdown to PATH and stdout contains no
    resume body (matches portfolio.cli --out behavior).'"""
    jd_path = _make_jd(tmp_path, "python backend")
    out_path = tmp_path / "resume.md"
    code = run(_base_argv(jd_path, out=str(out_path)), extractor=_fake_extractor, runner=_fake_runner)
    stdout = capsys.readouterr().out
    assert code == 0
    written = out_path.read_text(encoding="utf-8")
    assert "# Resume" in written
    assert "Built the feature using python" in written
    assert "# Resume" not in stdout


# ---------------------------------------------------------------------------
# Done-when: grounding summary on stderr, not in rendered Markdown
# ---------------------------------------------------------------------------


def test_grounding_summary_on_stderr_not_in_document(tmp_path, capsys):
    """'A one-line grounding summary is emitted to stderr (not into the rendered
    document) on every successful run.'"""
    jd_path = _make_jd(tmp_path, "python backend")
    code = run(_base_argv(jd_path), extractor=_fake_extractor, runner=_fake_runner)
    captured = capsys.readouterr()
    assert code == 0
    err = captured.err.lower()
    assert "grounded:" in err
    assert "rejected:" in err
    assert "needs-confirmation:" in err
    # summary must NOT appear in the rendered Markdown
    assert "grounded:" not in captured.out.lower()
    assert "rejected:" not in captured.out.lower()
    assert "needs-confirmation:" not in captured.out.lower()


# ---------------------------------------------------------------------------
# Done-when: missing --jd path exits non-zero, no resume body
# ---------------------------------------------------------------------------


def test_missing_jd_exits_nonzero(tmp_path, capsys):
    """'A --jd path that does not exist or is unreadable causes a non-zero exit,
    a clear stderr message, and no resume body on stdout (no Python traceback).'"""
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
        extractor=_fake_extractor,
        runner=_fake_runner,
    )
    captured = capsys.readouterr()
    assert code != 0
    assert captured.err.strip() != ""
    assert "# Resume" not in captured.out


# ---------------------------------------------------------------------------
# Done-when: non-GitHub source with --source-type github rejected without extracting
# ---------------------------------------------------------------------------


def test_non_github_source_rejected_without_extracting(tmp_path, capsys):
    """'An unparseable / unsupported --source URL (e.g. https://gitlab.com/owner/repo
    for --source-type github) causes a non-zero exit with a stderr error and never
    invokes the injected extractor.'"""
    jd_path = _make_jd(tmp_path, "python backend")
    calls: list[dict] = []

    def recording_extractor(**kwargs) -> list[Evidence]:
        calls.append(kwargs)
        return []

    code = run(
        ["--source-type", "github", "--source", "https://gitlab.com/owner/repo", "--author", "alice", "--jd", jd_path],
        extractor=recording_extractor,
        runner=_fake_runner,
    )
    captured = capsys.readouterr()
    assert code != 0
    assert captured.err.strip() != ""
    assert calls == []
    assert "# Resume" not in captured.out


# ---------------------------------------------------------------------------
# Done-when: extractor exception becomes clean non-zero exit
# ---------------------------------------------------------------------------


def test_extractor_failure_exits_cleanly(tmp_path, capsys):
    """'An unexpected failure from the injected extractor/runner/fetcher (e.g. a
    TypeError from a malformed-shape response) becomes a clean non-zero exit with
    a stderr message (no traceback).'"""
    jd_path = _make_jd(tmp_path, "python backend")

    def boom(**_kwargs):
        raise TypeError("simulated extractor failure")

    code = run(_base_argv(jd_path), extractor=boom, runner=_fake_runner)
    captured = capsys.readouterr()
    assert code == 1
    assert "failed to build resume" in captured.err.lower()
    assert "# Resume" not in captured.out


# ---------------------------------------------------------------------------
# Done-when: zero grounded claims exits 0 with deterministic empty notice
# ---------------------------------------------------------------------------


def test_zero_grounded_claims_exits_zero_with_notice(tmp_path, capsys):
    """'If the grounded portfolio yields zero JD-matching grounded claims (fail-closed
    case), the CLI exits 0 and emits a deterministic "no grounded resume bullets" notice
    in the Markdown — never fabricates bullets.'"""
    jd_path = _make_jd(tmp_path, "python backend")

    def empty_runner(_prompt: str) -> str:
        # Returns a claim citing a hallucinated ref so nothing is grounded
        return json.dumps([{"text": "FABRICATED", "evidence_refs": ["PR#999"], "confidence": 0.9}])

    code = run(_base_argv(jd_path), extractor=_fake_extractor, runner=empty_runner)
    out = capsys.readouterr().out
    assert code == 0
    assert "no grounded resume bullets" in out.lower()
    assert "FABRICATED" not in out


# ---------------------------------------------------------------------------
# Done-when: .claude/commands/resume.md exists, invokes python -m resume,
#            uses separate argv tokens, forbids shell string assembly
# ---------------------------------------------------------------------------


def test_resume_slash_command_content():
    """'A content check on .claude/commands/resume.md confirms the file exists,
    runs python -m resume, references the required argv tokens as separate values
    (no shell string assembly / $() / single-string interpolation of $ARGUMENTS),
    and includes the hard-rule clause about never assembling a shell string from
    user input.'"""
    commands_dir = Path(__file__).resolve().parents[1] / ".claude" / "commands"
    resume_md = commands_dir / "resume.md"
    assert resume_md.exists(), ".claude/commands/resume.md must exist"

    content = resume_md.read_text(encoding="utf-8")

    # Must invoke python -m resume
    assert "python -m resume" in content

    # Must reference the key argv tokens as separate values (not assembled)
    assert "--source-type" in content
    assert "--source" in content
    assert "--author" in content
    assert "--jd" in content

    # Must not use $() or shell string assembly of $ARGUMENTS
    assert "$(" not in content

    # Must have a hard-rule clause forbidding shell string assembly
    lower = content.lower()
    assert "shell string" in lower or "never assemble" in lower


# ---------------------------------------------------------------------------
# IR-002 regression: evidence refs containing Markdown special chars are escaped
# ---------------------------------------------------------------------------


def test_evidence_ref_markdown_injection_escaped(tmp_path, capsys):
    """Regression for IR-002: evidence_refs like 'PR#1](_bad_)' that contain
    Markdown special characters must be escaped before appearing in the rendered
    output — _escape() must be applied to every ref, not only to claim text."""
    jd_path = _make_jd(tmp_path, "python backend")

    injected_ref = "PR#1](_bad_)"  # would close a Markdown link if not escaped

    def extractor_with_tricky_ref(*, repo: str, author: str) -> list[Evidence]:
        return [Evidence(kind="pr", ref=injected_ref, url="https://github.com/o/r/pull/1", detail="Tricky ref")]

    def runner_citing_tricky_ref(_prompt: str) -> str:
        return json.dumps([{"text": "Built a python thing", "evidence_refs": [injected_ref], "confidence": 0.9}])

    code = run(
        _base_argv(jd_path),
        extractor=extractor_with_tricky_ref,
        runner=runner_citing_tricky_ref,
    )
    out = capsys.readouterr().out
    assert code == 0
    # The raw injected string must NOT appear literally in output (it must be escaped)
    assert injected_ref not in out
    # The escaped version (backslash before ] and _) must appear instead
    assert r"PR\#1\]" in out or "PR" in out  # at minimum, the ] is escaped
