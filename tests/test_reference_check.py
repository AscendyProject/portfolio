"""Tests for the reference-check CLI (python -m reference_check).

All tests inject fake `extractor`, `runner`, and `fetcher` — no live gh/claude/network.
Each test traces to a Done-when item in outcome.md via its docstring.
"""

from __future__ import annotations

import ast
import inspect
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.model import Evidence  # noqa: E402
from reference_check.cli import run  # noqa: E402


# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _fake_extractor(*, repo: str, author: str) -> list[Evidence]:
    """Returns canned Evidence for a github source; no network."""
    return [Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="Add feature")]


def _make_counter_runner(narrate_json: str, letter_json: str):
    """Return a runner that yields narrate_json on the 1st call and letter_json on the 2nd."""
    calls = [0]

    def runner(prompt: str) -> str:
        calls[0] += 1
        return narrate_json if calls[0] == 1 else letter_json

    return runner


# One grounded narration claim and one grounded letter paragraph — both cite PR#1.
_NARRATE_ONE = json.dumps([{"text": "Built key feature", "evidence_refs": ["PR#1"], "confidence": 0.9}])
_LETTER_ONE = json.dumps([{"text": "excellent contribution to the project", "evidence_refs": ["PR#1"]}])


def _base_argv(out: str | None = None) -> list[str]:
    argv = ["--source-type", "github", "--source", "https://github.com/owner/repo", "--author", "alice"]
    if out is not None:
        argv += ["--out", out]
    return argv


# ---------------------------------------------------------------------------
# Done-when: python -m reference_check --help exits 0 and lists the flags
# ---------------------------------------------------------------------------


def test_help_exits_zero_and_lists_flags():
    """'python -m reference_check --help exits 0 and lists the flags'."""
    result = subprocess.run(
        [sys.executable, "-m", "reference_check", "--help"],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0
    assert "--source-type" in result.stdout
    assert "--source" in result.stdout
    assert "--author" in result.stdout


# ---------------------------------------------------------------------------
# Done-when: reference_check/cli.py exposes run(argv, *, extractor=..., runner=..., fetcher=...) -> int
# ---------------------------------------------------------------------------


def test_run_function_has_injectable_seams():
    """'reference_check/cli.py exposes run(argv, *, extractor=..., runner=..., fetcher=...) -> int'."""
    sig = inspect.signature(run)
    params = sig.parameters
    assert "argv" in params
    assert "extractor" in params
    assert "runner" in params
    assert "fetcher" in params
    # All three injectable params must be keyword-only with defaults.
    for name in ("extractor", "runner", "fetcher"):
        p = params[name]
        assert p.kind == inspect.Parameter.KEYWORD_ONLY
        assert p.default is not inspect.Parameter.empty


# ---------------------------------------------------------------------------
# Done-when: reference_check/__main__.py calls reference_check.cli.main() under if __name__ == "__main__"
# ---------------------------------------------------------------------------


def test_main_module_structure():
    """'reference_check/__main__.py calls reference_check.cli.main() under if __name__ == "__main__"'."""
    main_py = _REPO_ROOT / "reference_check" / "__main__.py"
    assert main_py.exists(), "reference_check/__main__.py must exist"
    content = main_py.read_text(encoding="utf-8")
    assert "main()" in content
    assert '__name__ == "__main__"' in content
    # Must import from reference_check.cli (absolute) or .cli (relative)
    assert "reference_check.cli" in content or "from .cli import" in content


# ---------------------------------------------------------------------------
# Done-when: end-to-end run produces stdout with salutation, --author, grounded paragraph, cited refs
# ---------------------------------------------------------------------------


def test_end_to_end_salutation_author_paragraph_refs(capsys):
    """'End-to-end pytest run produces stdout with salutation, --author, grounded paragraph, cited refs'."""
    runner = _make_counter_runner(_NARRATE_ONE, _LETTER_ONE)
    code = run(_base_argv(), extractor=_fake_extractor, runner=runner)
    out = capsys.readouterr().out
    assert code == 0
    assert "Dear Hiring Manager" in out  # salutation
    assert "alice" in out  # --author in heading
    assert "excellent contribution" in out  # grounded paragraph text
    # Evidence ref appears in output (escaped form: PR\#1 or at least "PR")
    assert "PR" in out


# ---------------------------------------------------------------------------
# Done-when: hallucinated paragraph is dropped (fail-closed); grounded paragraph appears
# ---------------------------------------------------------------------------


def test_hallucinated_paragraph_dropped_grounded_appears(capsys):
    """'Hallucinated paragraph is dropped (fail-closed); grounded paragraph appears'."""
    letter_json = json.dumps(
        [
            {"text": "GROUNDED-PARA genuine content here", "evidence_refs": ["PR#1"]},
            {"text": "HALLUCINATED-PARA invented content", "evidence_refs": ["PR#999"]},
        ]
    )
    runner = _make_counter_runner(_NARRATE_ONE, letter_json)
    code = run(_base_argv(), extractor=_fake_extractor, runner=runner)
    out = capsys.readouterr().out
    assert code == 0
    assert "GROUNDED-PARA" in out
    assert "HALLUCINATED-PARA" not in out


# ---------------------------------------------------------------------------
# Done-when: every visible evidence ref is a real ref from the Portfolio
# ---------------------------------------------------------------------------


def test_visible_refs_are_real(capsys):
    """'Every visible evidence ref is a real ref from the Portfolio'."""
    # The fake extractor provides exactly one evidence item: PR#1.
    real_evidence_refs = {"PR#1"}
    runner = _make_counter_runner(_NARRATE_ONE, _LETTER_ONE)
    code = run(_base_argv(), extractor=_fake_extractor, runner=runner)
    out = capsys.readouterr().out
    assert code == 0
    # PR#999 is not in evidence — must not appear in any form
    assert "PR#999" not in out
    assert "999" not in out
    # Every ref visible in the rendered output must be a real evidence ref.
    import re

    visible_refs = set(re.findall(r"PR#\d+", out))
    for ref in visible_refs:
        assert ref in real_evidence_refs, f"rendered ref {ref!r} is not in the evidence set {real_evidence_refs!r}"


# ---------------------------------------------------------------------------
# Done-when: --out writes file; stdout has no letter body
# ---------------------------------------------------------------------------


def test_out_writes_file_not_stdout(tmp_path, capsys):
    """'--out writes file; stdout has no letter body'."""
    out_path = tmp_path / "letter.md"
    runner = _make_counter_runner(_NARRATE_ONE, _LETTER_ONE)
    code = run(_base_argv(out=str(out_path)), extractor=_fake_extractor, runner=runner)
    stdout = capsys.readouterr().out
    assert code == 0
    written = out_path.read_text(encoding="utf-8")
    assert "Dear Hiring Manager" in written
    assert "excellent contribution" in written
    # stdout must be silent (no letter body)
    assert "Dear Hiring Manager" not in stdout
    assert "excellent contribution" not in stdout


# ---------------------------------------------------------------------------
# Done-when: grounding summary on stderr only, not in rendered Markdown
# ---------------------------------------------------------------------------


def test_grounding_summary_stderr_only(capsys):
    """'Grounding summary on stderr only, not in rendered Markdown'."""
    runner = _make_counter_runner(_NARRATE_ONE, _LETTER_ONE)
    code = run(_base_argv(), extractor=_fake_extractor, runner=runner)
    captured = capsys.readouterr()
    assert code == 0
    err = captured.err
    assert "grounded:" in err
    assert "rejected:" in err
    # Summary keywords with colon must not appear in rendered Markdown
    assert "grounded:" not in captured.out
    assert "rejected:" not in captured.out


# ---------------------------------------------------------------------------
# Done-when: non-GitHub --source under --source-type github → non-zero exit, no letter body
# ---------------------------------------------------------------------------


def test_non_github_source_rejected(capsys):
    """'Non-GitHub --source under --source-type github → non-zero exit, no letter body'."""
    runner = _make_counter_runner(_NARRATE_ONE, _LETTER_ONE)
    extractor_calls = [0]

    def recording_extractor(*, repo: str, author: str) -> list:
        extractor_calls[0] += 1
        return _fake_extractor(repo=repo, author=author)

    code = run(
        ["--source-type", "github", "--source", "https://gitlab.com/owner/repo", "--author", "alice"],
        extractor=recording_extractor,
        runner=runner,
    )
    captured = capsys.readouterr()
    assert code != 0
    assert captured.err.strip() != ""
    assert "Dear Hiring Manager" not in captured.out
    # Extractor must NEVER be called when source validation fails.
    assert extractor_calls[0] == 0, "extractor must not be called for an invalid source"


# ---------------------------------------------------------------------------
# Done-when: malformed runner output → clean non-zero or fail-closed empty letter; no traceback
# ---------------------------------------------------------------------------


def test_malformed_runner_fail_closed(capsys):
    """'Malformed runner output → clean non-zero or fail-closed empty letter; no traceback, no fabricated paragraph'."""

    def malformed_runner(prompt: str) -> str:
        return "this is not json at all !!!"

    code = run(_base_argv(), extractor=_fake_extractor, runner=malformed_runner)
    captured = capsys.readouterr()
    # No Python traceback
    assert "Traceback" not in captured.out
    assert "Traceback" not in captured.err
    # No fabricated content — either exit non-zero or fail-closed with notice
    if code == 0:
        assert "insufficient grounded evidence" in captured.out.lower()


def test_malformed_letter_runner_fail_closed(capsys):
    """Malformed letter runner output → fail-closed; no fabricated paragraph in output."""
    calls = [0]

    def runner(prompt: str) -> str:
        calls[0] += 1
        if calls[0] == 1:
            # Valid narration: one grounded claim
            return json.dumps([{"text": "Built feature", "evidence_refs": ["PR#1"], "confidence": 0.9}])
        # Malformed letter output
        return "NOT VALID JSON AT ALL"

    code = run(_base_argv(), extractor=_fake_extractor, runner=runner)
    captured = capsys.readouterr()
    assert code == 0
    assert "Traceback" not in captured.out
    assert "Traceback" not in captured.err
    assert "insufficient grounded evidence" in captured.out.lower()


# ---------------------------------------------------------------------------
# Done-when: zero-grounded-claims → exit 0, 'insufficient grounded evidence' notice, no fabricated content
# ---------------------------------------------------------------------------


def test_zero_grounded_claims_insufficient_notice(capsys):
    """'Zero-grounded-claims → exit 0, insufficient grounded evidence notice, no fabricated content'."""

    def hallucinated_runner(prompt: str) -> str:
        # Always cites a hallucinated ref → grounding gate drops every claim
        return json.dumps([{"text": "FABRICATED", "evidence_refs": ["PR#999"], "confidence": 0.9}])

    code = run(_base_argv(), extractor=_fake_extractor, runner=hallucinated_runner)
    out = capsys.readouterr().out
    assert code == 0
    assert "insufficient grounded evidence" in out.lower()
    assert "FABRICATED" not in out


# ---------------------------------------------------------------------------
# Done-when: .claude/commands/reference-check.md content checks
# ---------------------------------------------------------------------------


def test_slash_command_content():
    """'.claude/commands/reference-check.md content checks: separate argv tokens, no $(, hard-rule clause'."""
    cmd_md = _REPO_ROOT / ".claude" / "commands" / "reference-check.md"
    assert cmd_md.exists(), ".claude/commands/reference-check.md must exist"
    content = cmd_md.read_text(encoding="utf-8")

    # Must invoke python -m reference_check
    assert "python -m reference_check" in content

    # Must reference key argv tokens as separate values (not assembled into one string)
    assert "--source-type" in content
    assert "--source" in content
    assert "--author" in content

    # Must not use $() command substitution
    assert "$(" not in content

    # Must have a hard-rule clause about shell string assembly
    lower = content.lower()
    assert "shell string" in lower or "never assemble" in lower


# ---------------------------------------------------------------------------
# Done-when: no new third-party runtime imports
# ---------------------------------------------------------------------------


def test_no_third_party_imports():
    """'No new third-party runtime imports' in reference_check modules."""
    pkg = _REPO_ROOT / "reference_check"
    allowed_roots = {
        "__future__",
        "json",
        "sys",
        "argparse",
        "re",
        "subprocess",
        "dataclasses",
        "pathlib",
        "collections",
        "abc",
        "typing",
        "os",
        "portfolio",
        "resume",
        "reference_check",
    }
    for py_file in pkg.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root in allowed_roots, f"unexpected top-level import {alias.name!r} in {py_file.name}"
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                root = module.split(".")[0]
                assert root in allowed_roots, f"unexpected import from {module!r} in {py_file.name}"


# ---------------------------------------------------------------------------
# Done-when: letter.py and render.py perform no subprocess/urllib/socket/file I/O
# ---------------------------------------------------------------------------


def test_letter_and_render_no_io_imports():
    """'letter.py and render.py perform no subprocess/urllib/socket/file I/O'."""
    pkg = _REPO_ROOT / "reference_check"
    banned_roots = {"subprocess", "urllib", "socket", "requests", "httpx", "aiohttp"}
    for name in ("letter.py", "render.py"):
        py_file = pkg / name
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root not in banned_roots, f"{name} must not import {alias.name!r}"
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                root = module.split(".")[0]
                assert root not in banned_roots, f"{name} must not import from {module!r}"


# ---------------------------------------------------------------------------
# Done-when: README.md documents /reference-check with python -m reference_check, --author, grounding mention
# ---------------------------------------------------------------------------


def test_readme_documents_reference_check():
    """'README.md documents /reference-check with python -m reference_check, --author, grounding mention'."""
    readme = _REPO_ROOT / "README.md"
    content = readme.read_text(encoding="utf-8")
    assert "python -m reference_check" in content
    assert "--author" in content
    lower = content.lower()
    assert "grounded" in lower or "grounding" in lower
    # Must mention reference-check or reference_check
    assert "reference-check" in lower or "reference_check" in lower
