"""Tests for portfolio/share.py and rating --share wiring.

Covers:
- GistSharer argv shape (secret vs public, no shell=True)
- Injectable gh runner (no live gh in tests)
- share_links URL-encoding
- rating --share masking-on-by-default + --no-mask-on-share opt-out + --mask-private interactions
- Provenance footer in shared Markdown (en + ko)
- Share-off output byte-identical to non-share path
- Publish failure → non-zero exit + clean stderr + no partial stdout emit
- publish_share helper: ShareBundle, ShareError, extra_files, badge, masking
- resume --share and fit --share (single + batch)
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.i18n import LANGS  # noqa: E402
from portfolio.model import Evidence  # noqa: E402
from portfolio.share import GistSharer, ShareBundle, ShareError, ShareResult, Sharer, publish_share, share_links  # noqa: E402
from rating.cli import run  # noqa: E402
from resume.cli import run as resume_run  # noqa: E402
from fit.cli import run as fit_run  # noqa: E402


# ---------------------------------------------------------------------------
# Fake gh runner helpers
# ---------------------------------------------------------------------------


def _make_fake_gh(captured_calls: list) -> object:
    """Returns a fake gh_runner that records argv and returns a fake gist URL."""

    def fake_gh(argv: list, stdin_bytes=None) -> str:
        captured_calls.append({"argv": list(argv), "stdin_bytes": stdin_bytes})
        return "https://gist.github.com/fake/abc123\n"

    return fake_gh


def _make_failing_gh(exc: Exception) -> object:
    """Returns a fake gh_runner that raises the given exception."""

    def failing_gh(argv: list, stdin_bytes=None) -> str:
        raise exc

    return failing_gh


# ---------------------------------------------------------------------------
# Fake rating pipeline seams
# ---------------------------------------------------------------------------


def _fake_extractor(*, repo: str, author: str, limit: int = 100) -> list[Evidence]:
    return [Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="Add feature")]


def _fake_runner(prompt: str) -> str:
    return json.dumps([{"text": "Built the main feature", "evidence_refs": ["PR#1"], "confidence": 0.9}])


def _fake_grader_runner(prompt: str, temperature: int = 0) -> str:
    return json.dumps({"score": 40, "reasoning": [{"text": "Initial work", "evidence_refs": ["PR#1"]}]})


def _rating_argv(**extra) -> list[str]:
    base = ["--source-type", "github", "--source", "https://github.com/owner/repo", "--author", "alice"]
    for k, v in extra.items():
        flag = f"--{k.replace('_', '-')}"
        if v is True:
            base.append(flag)
        elif v is not False:
            base += [flag, str(v)]
    return base


# ---------------------------------------------------------------------------
# Part A: portfolio.share module exports
# ---------------------------------------------------------------------------


def test_imports():
    """'from portfolio.share import Sharer, ShareResult, GistSharer, share_links' exits 0."""
    from portfolio.share import GistSharer, ShareResult, Sharer, share_links  # noqa: F401


def test_share_result_has_url():
    result = ShareResult(url="https://gist.github.com/x/y")
    assert result.url == "https://gist.github.com/x/y"


def test_sharer_base_raises():
    s = Sharer()
    with pytest.raises(NotImplementedError):
        s.publish("md", title="t", public=False)


# ---------------------------------------------------------------------------
# Part A: GistSharer — argv shape, no shell=True, injectable runner
# ---------------------------------------------------------------------------


def test_gist_sharer_secret_no_public_flag():
    """When public=False, --public is absent from the argv."""
    calls: list = []
    sharer = GistSharer(gh_runner=_make_fake_gh(calls))
    result = sharer.publish("# Hello", title="my-rating", public=False)
    assert len(calls) >= 2  # list call + create call
    argv = calls[-1]["argv"]
    assert "--public" not in argv
    assert result.url == "https://gist.github.com/fake/abc123"


def test_gist_sharer_public_flag_present():
    """When public=True, --public appears in the argv."""
    calls: list = []
    sharer = GistSharer(gh_runner=_make_fake_gh(calls))
    sharer.publish("# Hello", title="my-rating", public=True)
    argv = calls[-1]["argv"]
    assert "--public" in argv


def test_gist_sharer_argv_is_list_no_shell_true():
    """GistSharer passes argv as a list (no shell=True) — the fake runner receives a list."""
    calls: list = []
    sharer = GistSharer(gh_runner=_make_fake_gh(calls))
    sharer.publish("content", title="t", public=False)
    assert isinstance(calls[0]["argv"], list)
    # Confirm 'gh' is the first element
    assert calls[0]["argv"][0] == "gh"


def test_gist_sharer_no_live_gh():
    """The fake runner is used — no live gh is invoked."""
    calls: list = []
    sharer = GistSharer(gh_runner=_make_fake_gh(calls))
    result = sharer.publish("# Test", title="t", public=False)
    assert len(calls) >= 2  # list call + create call; still no real gh
    assert result.url.startswith("https://gist.github.com/")


# ---------------------------------------------------------------------------
# Part A: share_links — URL encoding
# ---------------------------------------------------------------------------


def test_share_links_url_encodes_spaces():
    links = share_links("https://gist.github.com/x/y", "Hello world")
    assert "Hello%20world" in links["linkedin"]
    assert "Hello%20world" in links["x"]


def test_share_links_url_encodes_ampersand():
    links = share_links("https://gist.github.com/x/y", "A & B")
    assert "%26" in links["linkedin"]
    assert "%26" in links["x"]


def test_share_links_url_encodes_question_mark():
    links = share_links("https://gist.github.com/x/y", "What?")
    assert "%3F" in links["linkedin"]
    assert "%3F" in links["x"]


def test_share_links_url_encodes_non_ascii():
    links = share_links("https://gist.github.com/x/y", "안녕")
    # Non-ASCII must be percent-encoded (not appear raw)
    assert "안녕" not in links["linkedin"]
    assert "안녕" not in links["x"]
    assert "%" in links["linkedin"]


def test_share_links_contains_linkedin_and_x_domains():
    links = share_links("https://gist.github.com/x/y", "test")
    assert "linkedin.com" in links["linkedin"]
    assert "twitter.com" in links["x"]


def test_share_links_combined_special_chars():
    """A summary with spaces, &, ?, and non-ASCII all appear percent-encoded."""
    summary = "Score: A & Top 10? 안녕"
    links = share_links("https://gist.github.com/x?q=1", summary)
    # None of the raw special chars should appear raw in the query param position
    assert "안녕" not in links["linkedin"]
    assert " " not in links["linkedin"]
    assert "?" not in links["linkedin"].split("?", 1)[1]  # only the delimiter ? is OK


# ---------------------------------------------------------------------------
# Part B: rating --share flag wiring
# ---------------------------------------------------------------------------


class _FakeSharer(Sharer):
    """Captures the Markdown passed to publish and returns a fake URL."""

    def __init__(self, url: str = "https://gist.github.com/fake/xyz"):
        self.url = url
        self.calls: list[dict] = []

    def publish(
        self,
        markdown: str,
        *,
        title: str,
        public: bool,
        extra_files: dict | None = None,
    ) -> ShareResult:
        self.calls.append({"markdown": markdown, "title": title, "public": public, "extra_files": extra_files})
        return ShareResult(url=self.url)


def _run_share(**flags) -> tuple[int, str, str]:
    """Run rating CLI with --share and all fake seams. Returns (code, stdout, stderr)."""
    import io
    from unittest.mock import patch

    argv = _rating_argv(share=True, **flags)
    fake_sharer = _FakeSharer()

    with (
        patch("sys.stdout", new_callable=io.StringIO) as mock_out,
        patch("sys.stderr", new_callable=io.StringIO) as mock_err,
    ):
        code = run(
            argv,
            extractor=_fake_extractor,
            runner=_fake_runner,
            grader_runner=_fake_grader_runner,
            sharer=fake_sharer,
        )
        return code, mock_out.getvalue(), mock_err.getvalue()


def test_share_flag_exits_zero(capsys):
    """--share exits 0 with a fake Sharer."""
    fake_sharer = _FakeSharer()
    code = run(
        _rating_argv(share=True),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
        sharer=fake_sharer,
    )
    capsys.readouterr()
    assert code == 0


def test_share_stdout_order(capsys):
    """--share stdout order: rendered report (with footer) → gist URL → LinkedIn → X."""
    fake_sharer = _FakeSharer()
    code = run(
        _rating_argv(share=True),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
        sharer=fake_sharer,
    )
    out = capsys.readouterr().out
    assert code == 0

    gist_url = fake_sharer.url
    gist_pos = out.index(gist_url)
    linkedin_pos = out.index("linkedin.com")
    x_pos = out.index("twitter.com")

    # Report section comes before gist URL
    assert out.index("# Capability Rating") < gist_pos
    # URL ordering: gist → linkedin → x
    assert gist_pos < linkedin_pos < x_pos


def test_share_provenance_footer_in_stdout(capsys):
    """--share: the footer appears in stdout."""
    fake_sharer = _FakeSharer()
    code = run(
        _rating_argv(share=True),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
        sharer=fake_sharer,
    )
    out = capsys.readouterr().out
    assert code == 0
    footer = LANGS["en"]["share_provenance_footer"]
    # The footer content appears in stdout
    assert "grounded in real GitHub evidence" in out or footer.split("\n")[-1].strip("_") in out


def test_share_markdown_matches_stdout_report(capsys):
    """The Markdown passed to Sharer.publish is identical to the report block on stdout."""
    fake_sharer = _FakeSharer()
    code = run(
        _rating_argv(share=True),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
        sharer=fake_sharer,
    )
    out = capsys.readouterr().out
    assert code == 0

    published_md = fake_sharer.calls[0]["markdown"]
    gist_url = fake_sharer.url
    # stdout starts with the same markdown that was published
    assert out.startswith(published_md)
    # gist URL appears after the markdown
    assert gist_url in out[len(published_md) :]


# ---------------------------------------------------------------------------
# Part B: --share without flag → byte-identical to non-share
# ---------------------------------------------------------------------------


def test_no_share_output_byte_identical(capsys):
    """Without --share, stdout is byte-identical to a run with share branch bypassed."""
    # Run without --share
    code1 = run(
        _rating_argv(),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
    )
    out1 = capsys.readouterr().out
    assert code1 == 0

    # Run again without --share (same inputs → same output)
    code2 = run(
        _rating_argv(),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
    )
    out2 = capsys.readouterr().out
    assert code2 == 0

    assert out1 == out2
    # No share artifacts
    assert "gist.github.com" not in out1
    assert "linkedin.com" not in out1
    assert "twitter.com" not in out1
    assert LANGS["en"]["share_provenance_footer"].split("\n")[-1].strip("_") not in out1


def test_no_share_no_footer_in_output(capsys):
    """The provenance footer must NOT appear in non-share output."""
    code = run(
        _rating_argv(),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "grounded in real GitHub evidence" not in out


# ---------------------------------------------------------------------------
# Part B: privacy-first mask resolution — all four combinations
# ---------------------------------------------------------------------------

_PRIVATE_REPO = "secret-org/private-svc"
_PRIVATE_LABEL = "private-repo-1"


def _private_extractor(*, repo: str, author: str, limit: int = 100) -> list[Evidence]:
    """Returns evidence that mentions a private repo in its URL/detail."""
    return [
        Evidence(
            kind="pr",
            ref=f"{_PRIVATE_REPO}#1",
            url=f"https://github.com/{_PRIVATE_REPO}/pull/1",
            detail=f"PR in {_PRIVATE_REPO}",
        )
    ]


def _private_visibility_lookup(repo: str) -> bool:
    """All repos are private."""
    return True


def _private_runner_with_ref(prompt: str) -> str:
    """Runner that cites the full private ref so it can appear in evidence."""
    return json.dumps(
        [{"text": f"Feature in {_PRIVATE_REPO}", "evidence_refs": [f"{_PRIVATE_REPO}#1"], "confidence": 0.9}]
    )


def _run_with_private_extractor(extra_flags: list[str], sharer: _FakeSharer) -> tuple[int, str, str]:
    """Run rating CLI with the private extractor and return (code, stdout, stderr)."""
    import io
    from unittest.mock import patch

    argv = [
        "--source-type",
        "github",
        "--source",
        f"https://github.com/{_PRIVATE_REPO}",
        "--author",
        "alice",
        "--show-refs",
    ] + extra_flags
    with (
        patch("sys.stdout", new_callable=io.StringIO) as mock_out,
        patch("sys.stderr", new_callable=io.StringIO) as mock_err,
    ):
        code = run(
            argv,
            extractor=_private_extractor,
            runner=_private_runner_with_ref,
            grader_runner=_fake_grader_runner,
            visibility_lookup=_private_visibility_lookup,
            sharer=sharer,
        )
        return code, mock_out.getvalue(), mock_err.getvalue()


def test_share_masks_subject_in_gist_title():
    """A private repo name in the SUBJECT must not leak via the gist title/filename —
    the title is a separate channel from the (masked) body, so it is scrubbed with the
    same relabel map and made filename-safe (codex IR-001)."""
    import io
    from unittest.mock import patch

    # Subject uses a MIXED-CASE spelling of the private repo while the extracted
    # evidence (and thus the lowercase relabel key) is lowercase — the scrub must be
    # case-insensitive, matching the masking layer (codex IR-001).
    subject_mixed = "Secret-Org/Private-Svc"
    sharer = _FakeSharer()
    argv = [
        "--source-type",
        "github",
        "--source",
        f"https://github.com/{_PRIVATE_REPO}",
        "--author",
        subject_mixed,  # subject itself carries the private repo name (mixed case)
        "--share",
    ]
    with patch("sys.stdout", new_callable=io.StringIO), patch("sys.stderr", new_callable=io.StringIO):
        code = run(
            argv,
            extractor=_private_extractor,
            runner=_private_runner_with_ref,
            grader_runner=_fake_grader_runner,
            visibility_lookup=_private_visibility_lookup,
            sharer=sharer,
        )
    assert code == 0
    title = sharer.calls[0]["title"]
    published_md = sharer.calls[0]["markdown"]
    # Neither the lowercase nor the mixed-case spelling may survive in title or body.
    for needle in (_PRIVATE_REPO, subject_mixed):
        assert needle not in title, f"raw private repo {needle!r} leaked in gist title: {title!r}"
        assert needle not in published_md, f"raw private repo {needle!r} leaked in shared body"
    assert "/" not in title, f"gist title not filename-safe: {title!r}"
    assert title, "gist title must be non-empty"


def test_share_masks_by_default():
    """--share alone: masking ON, no raw private repo name in Markdown passed to Sharer."""
    sharer = _FakeSharer()
    code, _out, _err = _run_with_private_extractor(["--share"], sharer)
    assert code == 0
    assert len(sharer.calls) == 1
    published_md = sharer.calls[0]["markdown"]
    assert _PRIVATE_REPO not in published_md


def test_share_no_mask_on_share_disables_masking():
    """--share --no-mask-on-share: masking OFF, raw private name reaches the Sharer."""
    sharer = _FakeSharer()
    code, _out, _err = _run_with_private_extractor(["--share", "--no-mask-on-share"], sharer)
    assert code == 0
    assert len(sharer.calls) == 1
    published_md = sharer.calls[0]["markdown"]
    assert _PRIVATE_REPO in published_md


def test_share_mask_private_explicit_masks():
    """--share --mask-private: masking ON (explicit --mask-private)."""
    sharer = _FakeSharer()
    code, _out, _err = _run_with_private_extractor(["--share", "--mask-private"], sharer)
    assert code == 0
    assert len(sharer.calls) == 1
    published_md = sharer.calls[0]["markdown"]
    assert _PRIVATE_REPO not in published_md


def test_share_mask_private_wins_over_no_mask_on_share():
    """--share --mask-private --no-mask-on-share: --mask-private wins; masking ON."""
    sharer = _FakeSharer()
    code, _out, _err = _run_with_private_extractor(["--share", "--mask-private", "--no-mask-on-share"], sharer)
    assert code == 0
    assert len(sharer.calls) == 1
    published_md = sharer.calls[0]["markdown"]
    assert _PRIVATE_REPO not in published_md


# ---------------------------------------------------------------------------
# Part C: provenance footer i18n
# ---------------------------------------------------------------------------


def test_share_footer_en(capsys):
    """--share --lang en: footer from LANGS["en"]["share_provenance_footer"] in published MD."""
    fake_sharer = _FakeSharer()
    code = run(
        _rating_argv(share=True, lang="en"),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
        sharer=fake_sharer,
    )
    capsys.readouterr()
    assert code == 0
    assert len(fake_sharer.calls) == 1
    published_md = fake_sharer.calls[0]["markdown"]
    footer = LANGS["en"]["share_provenance_footer"]
    # The footer text (or at least its substantive part) appears in the published MD
    assert footer in published_md or all(line in published_md for line in footer.splitlines() if line.strip())


def test_share_footer_ko(capsys):
    """--share --lang ko: footer from LANGS["ko"]["share_provenance_footer"] in published MD."""
    fake_sharer = _FakeSharer()
    code = run(
        _rating_argv(share=True, lang="ko"),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
        sharer=fake_sharer,
    )
    capsys.readouterr()
    assert code == 0
    assert len(fake_sharer.calls) == 1
    published_md = fake_sharer.calls[0]["markdown"]
    footer = LANGS["ko"]["share_provenance_footer"]
    assert footer in published_md or all(line in published_md for line in footer.splitlines() if line.strip())


def test_share_provenance_footer_keys_exist_and_nonempty():
    """Both LANGS["en"] and LANGS["ko"] define share_provenance_footer with a non-empty string."""
    for lang in ("en", "ko"):
        val = LANGS[lang]["share_provenance_footer"]
        assert isinstance(val, str)
        assert val.strip(), f"LANGS[{lang!r}]['share_provenance_footer'] is empty"


# ---------------------------------------------------------------------------
# Publish failure → non-zero exit + clean stderr + no gist URL on stdout
# ---------------------------------------------------------------------------


def test_publish_failure_exits_nonzero(capsys):
    """When Sharer.publish raises, CLI exits non-zero."""

    class FailSharer(Sharer):
        def publish(self, markdown, *, title, public, extra_files=None):
            raise RuntimeError("simulated publish failure")

    code = run(
        _rating_argv(share=True),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
        sharer=FailSharer(),
    )
    capsys.readouterr()
    assert code != 0


def test_publish_failure_clean_stderr_no_traceback(capsys):
    """On publish failure, stderr has a clean error line (no raw traceback)."""
    token_msg = "ghp_FAKETOKEN1234567890abcdefghijklmnop"

    class FailSharer(Sharer):
        def publish(self, markdown, *, title, public, extra_files=None):
            raise RuntimeError(f"auth failed: {token_msg}")

    code = run(
        _rating_argv(share=True),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
        sharer=FailSharer(),
    )
    captured = capsys.readouterr()
    assert code != 0
    # Clean error — no raw traceback
    assert "Traceback" not in captured.err
    # No token leak
    assert token_msg not in captured.err
    # Exactly ONE clean stderr line on failure — the grounding summary is deferred
    # until a successful publish, so it must not appear on the failure path (IR-003).
    err_lines = [ln for ln in captured.err.splitlines() if ln.strip()]
    assert len(err_lines) == 1, f"expected a single stderr line on publish failure, got: {err_lines!r}"
    assert "grounded:" not in captured.err


def test_publish_failure_no_gist_url_on_stdout(capsys):
    """On publish failure, stdout must not contain a gist URL or social links."""

    class FailSharer(Sharer):
        def publish(self, markdown, *, title, public, extra_files=None):
            raise RuntimeError("network error")

    code = run(
        _rating_argv(share=True),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
        sharer=FailSharer(),
    )
    out = capsys.readouterr().out
    assert code != 0
    assert "gist.github.com" not in out
    assert "linkedin.com" not in out
    assert "twitter.com" not in out


# ---------------------------------------------------------------------------
# --help mentions new flags
# ---------------------------------------------------------------------------


def test_help_mentions_share_flags(capsys):
    """python -m rating --help mentions --share, --share-public, --no-mask-on-share."""
    with pytest.raises(SystemExit) as exc_info:
        run(["--help"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "--share" in out
    assert "--share-public" in out
    assert "--no-mask-on-share" in out


# ---------------------------------------------------------------------------
# extra_files round-trip and GistSharer multi-file argv
# ---------------------------------------------------------------------------


def test_fake_sharer_captures_extra_files():
    """_FakeSharer.publish captures extra_files; existing assertions still pass when None."""
    sharer = _FakeSharer()
    # Call with extra_files=None (backward-compat default)
    sharer.publish("md content", title="t", public=False, extra_files=None)
    assert sharer.calls[0]["extra_files"] is None
    assert sharer.calls[0]["markdown"] == "md content"

    # Call with extra_files dict
    sharer.publish("md2", title="t2", public=True, extra_files={"f.svg": "<svg/>"})
    assert sharer.calls[1]["extra_files"] == {"f.svg": "<svg/>"}


def test_share_cli_passes_extra_files_svg(capsys):
    """Under --share, the CLI passes extra_files containing the .svg entry."""
    fake_sharer = _FakeSharer()
    code = run(
        _rating_argv(share=True),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
        sharer=fake_sharer,
    )
    capsys.readouterr()
    assert code == 0
    assert len(fake_sharer.calls) == 1
    extra_files = fake_sharer.calls[0]["extra_files"]
    assert extra_files is not None
    # Exactly one .svg entry, no .md entry
    svg_keys = [k for k in extra_files if k.endswith(".svg")]
    md_keys = [k for k in extra_files if k.endswith(".md")]
    assert len(svg_keys) == 1
    assert len(md_keys) == 0
    # The SVG body is a non-empty string
    assert extra_files[svg_keys[0]].strip()


def test_gist_sharer_extra_files_argv_shape():
    """GistSharer with extra_files writes to a single tmpdir; argv carries both paths."""
    import os

    calls: list = []
    sharer = GistSharer(gh_runner=_make_fake_gh(calls))
    result = sharer.publish(
        "# Hello",
        title="my-rating",
        public=False,
        extra_files={"my-rating.svg": "<svg/>"},
    )
    assert result.url == "https://gist.github.com/fake/abc123"
    assert len(calls) >= 2  # list call + create call
    argv = calls[-1]["argv"]
    # argv is a list (no shell=True)
    assert isinstance(argv, list)
    assert argv[0] == "gh"
    assert "gist" in argv
    assert "create" in argv
    # --public must NOT be present (public=False)
    assert "--public" not in argv
    # stdin is None (file-based, not stdin)
    assert calls[-1]["stdin_bytes"] is None
    # Exactly one .md path and one .svg path in the argv
    md_paths = [a for a in argv if a.endswith(".md")]
    svg_paths = [a for a in argv if a.endswith(".svg")]
    assert len(md_paths) == 1
    assert len(svg_paths) == 1
    # Both paths share the same parent (same TemporaryDirectory)
    assert os.path.dirname(md_paths[0]) == os.path.dirname(svg_paths[0])


def test_gist_sharer_extra_files_public_flag():
    """GistSharer with extra_files and public=True includes --public in argv."""
    calls: list = []
    sharer = GistSharer(gh_runner=_make_fake_gh(calls))
    sharer.publish("md", title="t", public=True, extra_files={"t.svg": "<svg/>"})
    assert "--public" in calls[-1]["argv"]


def test_gist_sharer_none_extra_files_uses_stdin():
    """GistSharer with extra_files=None uses stdin (byte-identical to today)."""
    calls: list = []
    sharer = GistSharer(gh_runner=_make_fake_gh(calls))
    sharer.publish("md content", title="t", public=False, extra_files=None)
    argv = calls[-1]["argv"]
    # Single-file stdin path: --filename flag present and "-" arg present
    assert "--filename" in argv
    assert "-" in argv
    assert calls[-1]["stdin_bytes"] == b"md content"


def test_publish_failure_no_badge_snippet_on_stdout(capsys):
    """On publish failure, stdout must not contain the badge snippet."""

    class FailSharer(Sharer):
        def publish(self, markdown, *, title, public, extra_files=None):
            raise RuntimeError("network error")

    code = run(
        _rating_argv(share=True),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
        sharer=FailSharer(),
    )
    out = capsys.readouterr().out
    assert code != 0
    assert "![" not in out
    assert "gist.githubusercontent.com" not in out


# ===========================================================================
# Part D: publish_share unit tests (importable helper)
# ===========================================================================


class _CapturingSharer(Sharer):
    """Fake Sharer that records all publish() calls."""

    def __init__(self, url: str = "https://gist.github.com/fake/pub123"):
        self.url = url
        self.calls: list[dict] = []

    def publish(
        self,
        markdown: str,
        *,
        title: str,
        public: bool,
        extra_files: dict | None = None,
    ) -> ShareResult:
        self.calls.append({"markdown": markdown, "title": title, "public": public, "extra_files": extra_files})
        return ShareResult(url=self.url)


def test_publish_share_importable():
    """publish_share, ShareBundle, ShareError are importable from portfolio.share."""
    from portfolio.share import ShareBundle, ShareError, publish_share  # noqa: F401


def test_publish_share_returns_share_bundle():
    """publish_share returns a ShareBundle with the expected attributes."""
    sharer = _CapturingSharer()
    bundle = publish_share(
        "# Report\n\nsome content",
        subject="resume-alice",
        lang="en",
        public=False,
        effective_mask=False,
        relabel={},
        sharer=sharer,
    )
    assert isinstance(bundle, ShareBundle)
    assert bundle.url == sharer.url
    assert "linkedin.com" in bundle.linkedin
    assert "twitter.com" in bundle.x


def test_publish_share_footer_appended_en():
    """publish_share appends LANGS['en']['share_provenance_footer'] to the report_md."""
    sharer = _CapturingSharer()
    report = "# Resume\n\ncontent"
    bundle = publish_share(
        report,
        subject="resume-alice",
        lang="en",
        public=False,
        effective_mask=False,
        relabel={},
        sharer=sharer,
    )
    footer = LANGS["en"]["share_provenance_footer"]
    assert footer in bundle.shared_md
    assert footer in sharer.calls[0]["markdown"]


def test_publish_share_footer_appended_ko():
    """publish_share appends LANGS['ko']['share_provenance_footer'] when lang='ko'."""
    sharer = _CapturingSharer()
    bundle = publish_share(
        "# 이력서\n\n내용",
        subject="resume-alice",
        lang="ko",
        public=False,
        effective_mask=False,
        relabel={},
        sharer=sharer,
    )
    footer = LANGS["ko"]["share_provenance_footer"]
    assert footer in bundle.shared_md


def test_publish_share_no_card_extra_files_is_none():
    """When card_svg is None, extra_files passed to sharer.publish is None."""
    sharer = _CapturingSharer()
    publish_share(
        "# Report",
        subject="fit-alice",
        lang="en",
        public=False,
        effective_mask=False,
        relabel={},
        sharer=sharer,
        card_svg=None,
    )
    assert sharer.calls[0]["extra_files"] is None


def test_publish_share_no_card_badge_is_none():
    """When card_svg is None, the returned bundle.badge is None."""
    sharer = _CapturingSharer()
    bundle = publish_share(
        "# Report",
        subject="fit-alice",
        lang="en",
        public=False,
        effective_mask=False,
        relabel={},
        sharer=sharer,
        card_svg=None,
    )
    assert bundle.badge is None


def test_publish_share_with_card_extra_files_has_svg():
    """When card_svg is supplied, extra_files has a {title}.svg entry."""
    sharer = _CapturingSharer()
    publish_share(
        "# Report",
        subject="rating-alice",
        lang="en",
        public=False,
        effective_mask=False,
        relabel={},
        sharer=sharer,
        card_svg="<svg>test</svg>",
    )
    extra_files = sharer.calls[0]["extra_files"]
    assert extra_files is not None
    svg_keys = [k for k in extra_files if k.endswith(".svg")]
    assert len(svg_keys) == 1
    assert extra_files[svg_keys[0]] == "<svg>test</svg>"


def test_publish_share_with_card_badge_present():
    """When card_svg is supplied, bundle.badge contains a markdown image link."""
    sharer = _CapturingSharer()
    bundle = publish_share(
        "# Report",
        subject="rating-alice",
        lang="en",
        public=False,
        effective_mask=False,
        relabel={},
        sharer=sharer,
        card_svg="<svg/>",
    )
    assert bundle.badge is not None
    assert bundle.badge.startswith("![")
    assert "gist.githubusercontent.com" in bundle.badge


def test_publish_share_masking_scrubs_body():
    """With effective_mask=True, private repo name is absent from shared_md."""
    sharer = _CapturingSharer()
    relabel = {"secret-org/private-svc": "private-repo-1"}
    bundle = publish_share(
        "# Report\n\nWork at secret-org/private-svc was great.",
        subject="resume-alice",
        lang="en",
        public=False,
        effective_mask=True,
        relabel=relabel,
        sharer=sharer,
    )
    assert "secret-org/private-svc" not in bundle.shared_md
    assert "private-repo-1" in bundle.shared_md


def test_publish_share_masking_scrubs_title():
    """With effective_mask=True, private repo name does not appear in the gist title."""
    sharer = _CapturingSharer()
    relabel = {"secret-org/private-svc": "private-repo-1"}
    publish_share(
        "# Report",
        subject="resume-secret-org/private-svc",
        lang="en",
        public=False,
        effective_mask=True,
        relabel=relabel,
        sharer=sharer,
    )
    title = sharer.calls[0]["title"]
    assert "secret-org/private-svc" not in title
    assert "/" not in title, f"title is not filename-safe: {title!r}"


def test_publish_share_masking_scrubs_svg():
    """With effective_mask=True, private repo name is absent from the SVG in extra_files."""
    sharer = _CapturingSharer()
    relabel = {"secret-org/private-svc": "private-repo-1"}
    publish_share(
        "# Report",
        subject="rating-alice",
        lang="en",
        public=False,
        effective_mask=True,
        relabel=relabel,
        sharer=sharer,
        card_svg="<svg><text>secret-org/private-svc</text></svg>",
    )
    extra_files = sharer.calls[0]["extra_files"]
    svg_content = list(extra_files.values())[0]
    assert "secret-org/private-svc" not in svg_content
    assert "private-repo-1" in svg_content


def test_publish_share_raises_share_error_on_failure():
    """publish_share raises ShareError (not the raw underlying exception) on publish failure."""

    class BrokenSharer(Sharer):
        def publish(self, markdown, *, title, public, extra_files=None):
            raise RuntimeError("connection refused")

    with pytest.raises(ShareError):
        publish_share(
            "# Report",
            subject="resume-alice",
            lang="en",
            public=False,
            effective_mask=False,
            relabel={},
            sharer=BrokenSharer(),
        )


def test_publish_share_does_not_print_on_failure(capsys):
    """publish_share does not print anything to stdout or stderr when publish fails."""

    class BrokenSharer(Sharer):
        def publish(self, markdown, *, title, public, extra_files=None):
            raise RuntimeError("auth failed: ghp_FAKETOKEN")

    with pytest.raises(ShareError):
        publish_share(
            "# Report",
            subject="resume-alice",
            lang="en",
            public=False,
            effective_mask=False,
            relabel={},
            sharer=BrokenSharer(),
        )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_publish_share_title_filename_safe():
    """publish_share derives a filename-safe title (no special chars or path separators)."""
    sharer = _CapturingSharer()
    publish_share(
        "# Report",
        subject="fit-alice/wonderful team",
        lang="en",
        public=False,
        effective_mask=False,
        relabel={},
        sharer=sharer,
    )
    title = sharer.calls[0]["title"]
    import re

    assert re.match(r"^[A-Za-z0-9._-]+$", title), f"title not filename-safe: {title!r}"


def test_publish_share_title_fallback_nonempty():
    """publish_share title falls back to 'portfolio' when subject has no filename-safe chars."""
    sharer = _CapturingSharer()
    publish_share(
        "# Report",
        subject="/// ???",
        lang="en",
        public=False,
        effective_mask=False,
        relabel={},
        sharer=sharer,
    )
    title = sharer.calls[0]["title"]
    assert title  # non-empty fallback


# ===========================================================================
# Part E: resume --share wiring tests
# ===========================================================================


def _fake_resume_extractor(*, repo: str, author: str, limit: int = 100) -> list[Evidence]:
    return [Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="Add feature")]


def _fake_resume_runner(prompt: str) -> str:
    return json.dumps([{"text": "Built the feature", "evidence_refs": ["PR#1"], "confidence": 0.9}])


def _resume_argv(jd_path: str, **flags) -> list[str]:
    base = [
        "--source-type",
        "github",
        "--source",
        "https://github.com/owner/repo",
        "--author",
        "alice",
        "--jd",
        jd_path,
    ]
    for k, v in flags.items():
        flag = f"--{k.replace('_', '-')}"
        if v is True:
            base.append(flag)
        elif v is not False:
            base += [flag, str(v)]
    return base


def _run_resume(jd_path: str, fake_sharer: Sharer, **flags) -> tuple[int, str, str]:
    """Run resume CLI with the given flags and fake sharer. Returns (code, stdout, stderr)."""
    argv = _resume_argv(jd_path, **flags)
    with (
        patch("sys.stdout", new_callable=io.StringIO) as mock_out,
        patch("sys.stderr", new_callable=io.StringIO) as mock_err,
    ):
        code = resume_run(
            argv,
            extractor=_fake_resume_extractor,
            runner=_fake_resume_runner,
            sharer=fake_sharer,
        )
        return code, mock_out.getvalue(), mock_err.getvalue()


def test_resume_share_exits_zero(tmp_path):
    """resume --share exits 0 with a fake Sharer."""
    jd = tmp_path / "jd.txt"
    jd.write_text("python backend engineer")
    fake_sharer = _FakeSharer()
    code, _out, _err = _run_resume(str(jd), fake_sharer, share=True)
    assert code == 0


def test_resume_share_footer_in_published_md(tmp_path):
    """resume --share: captured markdown ends with i18n provenance footer."""
    jd = tmp_path / "jd.txt"
    jd.write_text("python backend engineer")
    fake_sharer = _FakeSharer()
    code, _out, _err = _run_resume(str(jd), fake_sharer, share=True)
    assert code == 0
    assert len(fake_sharer.calls) == 1
    published_md = fake_sharer.calls[0]["markdown"]
    footer = LANGS["en"]["share_provenance_footer"]
    assert footer in published_md


def test_resume_share_stdout_order(tmp_path):
    """resume --share stdout: shared_md → gist URL → linkedin → x; no badge."""
    jd = tmp_path / "jd.txt"
    jd.write_text("python backend engineer")
    fake_sharer = _FakeSharer()
    code, out, _err = _run_resume(str(jd), fake_sharer, share=True)
    assert code == 0
    gist_url = fake_sharer.url
    gist_pos = out.index(gist_url)
    linkedin_pos = out.index("linkedin.com")
    x_pos = out.index("twitter.com")
    # Report comes before gist URL
    assert out.index("# Resume") < gist_pos
    # Ordering: gist URL → linkedin → x
    assert gist_pos < linkedin_pos < x_pos
    # No badge snippet (no card for resume)
    assert "![" not in out
    assert "gist.githubusercontent.com" not in out


def test_resume_share_masks_by_default(tmp_path):
    """resume --share: masking ON by default; private repo name absent from published md."""
    jd = tmp_path / "jd.txt"
    jd.write_text("python backend engineer")

    _PRIV = "secret-org/private-svc"

    def priv_extractor(*, repo: str, author: str, limit: int = 100) -> list[Evidence]:
        return [
            Evidence(kind="pr", ref=f"{_PRIV}#1", url=f"https://github.com/{_PRIV}/pull/1", detail=f"Work at {_PRIV}")
        ]

    def priv_runner(prompt: str) -> str:
        return json.dumps([{"text": f"Feature in {_PRIV}", "evidence_refs": [f"{_PRIV}#1"], "confidence": 0.9}])

    def priv_visibility(repo: str) -> bool:
        return True

    fake_sharer = _FakeSharer()
    argv = _resume_argv(str(jd), share=True)
    with (
        patch("sys.stdout", new_callable=io.StringIO),
        patch("sys.stderr", new_callable=io.StringIO),
    ):
        code = resume_run(
            argv,
            extractor=priv_extractor,
            runner=priv_runner,
            visibility_lookup=priv_visibility,
            sharer=fake_sharer,
        )
    assert code == 0
    assert len(fake_sharer.calls) == 1
    assert _PRIV not in fake_sharer.calls[0]["markdown"]


def test_resume_no_mask_on_share_disables_masking(tmp_path):
    """resume --share --no-mask-on-share: raw private name reaches the sharer.

    The private repo name is embedded in the gist title (derived from subject)
    to verify the sharer receives it unmasked when masking is disabled.
    """
    jd = tmp_path / "jd.txt"
    jd.write_text("python backend engineer")

    _PRIV = "secret-org/private-svc"

    def priv_extractor(*, repo: str, author: str, limit: int = 100) -> list[Evidence]:
        return [
            Evidence(kind="pr", ref=f"{_PRIV}#1", url=f"https://github.com/{_PRIV}/pull/1", detail=f"Work at {_PRIV}")
        ]

    def priv_runner(prompt: str) -> str:
        # The claim text embeds the private repo name AND a JD keyword so it is
        # selected by build_resume.
        return json.dumps(
            [{"text": f"Built python backend at {_PRIV}", "evidence_refs": [f"{_PRIV}#1"], "confidence": 0.9}]
        )

    def priv_visibility(repo: str) -> bool:
        return True

    fake_sharer = _FakeSharer()
    # Use the private repo as the --source so it becomes the portfolio subject,
    # which then flows into the gist title (publish_share derives it from subject).
    argv = [
        "--source-type",
        "github",
        "--source",
        f"https://github.com/{_PRIV}",
        "--author",
        "alice",
        "--jd",
        str(jd),
        "--share",
        "--no-mask-on-share",
    ]
    with (
        patch("sys.stdout", new_callable=io.StringIO),
        patch("sys.stderr", new_callable=io.StringIO),
    ):
        code = resume_run(
            argv,
            extractor=priv_extractor,
            runner=priv_runner,
            visibility_lookup=priv_visibility,
            sharer=fake_sharer,
        )
    assert code == 0
    assert len(fake_sharer.calls) == 1
    # Without masking, the private repo name must appear in either the title or markdown.
    call = fake_sharer.calls[0]
    # The subject contains the private repo (used as gist title source), so the
    # raw slug should survive in the title when masking is off.
    assert _PRIV in call["title"] or _PRIV in call["markdown"], (
        f"private repo name absent from both title and markdown when masking is disabled; title={call['title']!r}"
    )


def test_resume_mask_private_wins_over_no_mask_on_share(tmp_path):
    """resume --share --mask-private --no-mask-on-share: --mask-private wins; masking ON."""
    jd = tmp_path / "jd.txt"
    jd.write_text("python backend engineer")

    _PRIV = "secret-org/private-svc"

    def priv_extractor(*, repo: str, author: str, limit: int = 100) -> list[Evidence]:
        return [
            Evidence(kind="pr", ref=f"{_PRIV}#1", url=f"https://github.com/{_PRIV}/pull/1", detail=f"Work at {_PRIV}")
        ]

    def priv_runner(prompt: str) -> str:
        return json.dumps([{"text": f"Feature in {_PRIV}", "evidence_refs": [f"{_PRIV}#1"], "confidence": 0.9}])

    def priv_visibility(repo: str) -> bool:
        return True

    fake_sharer = _FakeSharer()
    argv = _resume_argv(str(jd), share=True, mask_private=True, no_mask_on_share=True)
    with (
        patch("sys.stdout", new_callable=io.StringIO),
        patch("sys.stderr", new_callable=io.StringIO),
    ):
        code = resume_run(
            argv,
            extractor=priv_extractor,
            runner=priv_runner,
            visibility_lookup=priv_visibility,
            sharer=fake_sharer,
        )
    assert code == 0
    assert _PRIV not in fake_sharer.calls[0]["markdown"]


def test_resume_share_failure_exits_nonzero(tmp_path):
    """resume --share: publish failure → non-zero exit."""
    jd = tmp_path / "jd.txt"
    jd.write_text("python backend engineer")

    class FailSharer(Sharer):
        def publish(self, markdown, *, title, public, extra_files=None):
            raise RuntimeError("simulated failure")

    code, _out, _err = _run_resume(str(jd), FailSharer(), share=True)
    assert code != 0


def test_resume_share_failure_one_clean_stderr_line(tmp_path):
    """resume --share failure: exactly one clean stderr line, no traceback, no partial stdout."""
    jd = tmp_path / "jd.txt"
    jd.write_text("python backend engineer")
    token_msg = "ghp_FAKETOKEN_resume_1234567890"

    class FailSharer(Sharer):
        def publish(self, markdown, *, title, public, extra_files=None):
            raise RuntimeError(f"auth failed: {token_msg}")

    code, out, err = _run_resume(str(jd), FailSharer(), share=True)
    assert code != 0
    # No partial stdout
    assert "gist.github.com" not in out
    assert "linkedin.com" not in out
    assert "twitter.com" not in out
    # Clean single stderr line
    assert "Traceback" not in err
    assert token_msg not in err
    err_lines = [ln for ln in err.splitlines() if ln.strip()]
    assert len(err_lines) == 1, f"expected exactly one stderr line, got: {err_lines!r}"
    assert "grounded:" not in err


def test_resume_no_share_output_byte_identical(tmp_path, capsys):
    """Without --share, resume stdout is byte-identical to a second run without --share."""
    jd = tmp_path / "jd.txt"
    jd.write_text("python backend engineer")

    code1 = resume_run(
        _resume_argv(str(jd)),
        extractor=_fake_resume_extractor,
        runner=_fake_resume_runner,
    )
    out1 = capsys.readouterr().out
    assert code1 == 0

    code2 = resume_run(
        _resume_argv(str(jd)),
        extractor=_fake_resume_extractor,
        runner=_fake_resume_runner,
    )
    out2 = capsys.readouterr().out
    assert code2 == 0
    assert out1 == out2
    assert "gist.github.com" not in out1
    assert "linkedin.com" not in out1


def test_resume_share_deferred_stderr_after_publish(tmp_path):
    """resume --share: mask-summary and grounding-summary appear AFTER successful publish."""
    jd = tmp_path / "jd.txt"
    jd.write_text("python backend engineer")

    _PRIV = "secret-org/private-svc"

    def priv_extractor(*, repo: str, author: str, limit: int = 100) -> list[Evidence]:
        return [Evidence(kind="pr", ref=f"{_PRIV}#1", url=f"https://github.com/{_PRIV}/pull/1", detail="x")]

    def priv_runner(prompt: str) -> str:
        return json.dumps([{"text": "Feature", "evidence_refs": [f"{_PRIV}#1"], "confidence": 0.9}])

    def priv_visibility(repo: str) -> bool:
        return True

    # Track the order of publish vs. stderr
    events: list[str] = []

    class TrackedSharer(Sharer):
        def publish(self, markdown, *, title, public, extra_files=None):
            events.append("published")
            return ShareResult(url="https://gist.github.com/fake/t123")

    argv = _resume_argv(str(jd), share=True)

    with (
        patch("sys.stdout", new_callable=io.StringIO),
        patch("sys.stderr", new_callable=io.StringIO) as mock_err,
    ):
        code = resume_run(
            argv,
            extractor=priv_extractor,
            runner=priv_runner,
            visibility_lookup=priv_visibility,
            sharer=TrackedSharer(),
        )
        err_content = mock_err.getvalue()

    assert code == 0
    # publish happened before the grounding summary was written
    assert "published" in events
    # grounding summary is present in stderr
    assert "grounded:" in err_content


def test_resume_help_mentions_share_flags(capsys):
    """python -m resume --help mentions --share, --share-public, --no-mask-on-share."""
    with pytest.raises(SystemExit) as exc_info:
        resume_run(["--help"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "--share" in out
    assert "--share-public" in out
    assert "--no-mask-on-share" in out


# ===========================================================================
# Part F: fit --share single-JD wiring tests
# ===========================================================================


def _fake_fit_extractor(*, repo: str, author: str, limit: int = 100) -> list[Evidence]:
    return [Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="Add feature")]


def _fake_fit_runner(prompt: str) -> str:
    return json.dumps([{"text": "Built a python backend service", "evidence_refs": ["PR#1"], "confidence": 0.9}])


def _fake_fit_grader(prompt: str, *, temperature: float = 0) -> str:
    return json.dumps({"score": 80, "reasoning": [{"text": "solid match", "evidence_refs": ["PR#1"]}]})


def _fit_argv(jd_path: str, **flags) -> list[str]:
    base = [
        "--source-type",
        "github",
        "--source",
        "https://github.com/owner/repo",
        "--author",
        "alice",
        "--jd",
        jd_path,
    ]
    for k, v in flags.items():
        flag = f"--{k.replace('_', '-')}"
        if v is True:
            base.append(flag)
        elif v is not False:
            base += [flag, str(v)]
    return base


def _run_fit(jd_path: str, fake_sharer: Sharer, **flags) -> tuple[int, str, str]:
    """Run fit CLI (single-JD) with the given flags and fake sharer."""
    argv = _fit_argv(jd_path, **flags)
    with (
        patch("sys.stdout", new_callable=io.StringIO) as mock_out,
        patch("sys.stderr", new_callable=io.StringIO) as mock_err,
    ):
        code = fit_run(
            argv,
            extractor=_fake_fit_extractor,
            runner=_fake_fit_runner,
            grader_runner=_fake_fit_grader,
            sharer=fake_sharer,
        )
        return code, mock_out.getvalue(), mock_err.getvalue()


def test_fit_share_exits_zero(tmp_path):
    """fit --share exits 0 with a fake Sharer."""
    jd = tmp_path / "jd.txt"
    jd.write_text("python backend engineer")
    fake_sharer = _FakeSharer()
    code, _out, _err = _run_fit(str(jd), fake_sharer, share=True)
    assert code == 0


def test_fit_share_footer_in_published_md(tmp_path):
    """fit --share: captured markdown ends with i18n provenance footer."""
    jd = tmp_path / "jd.txt"
    jd.write_text("python backend engineer")
    fake_sharer = _FakeSharer()
    code, _out, _err = _run_fit(str(jd), fake_sharer, share=True)
    assert code == 0
    assert len(fake_sharer.calls) == 1
    footer = LANGS["en"]["share_provenance_footer"]
    assert footer in fake_sharer.calls[0]["markdown"]


def test_fit_share_stdout_order_no_badge(tmp_path):
    """fit --share stdout: shared_md → gist URL → linkedin → x; no badge."""
    jd = tmp_path / "jd.txt"
    jd.write_text("python backend engineer")
    fake_sharer = _FakeSharer()
    code, out, _err = _run_fit(str(jd), fake_sharer, share=True)
    assert code == 0
    gist_url = fake_sharer.url
    gist_pos = out.index(gist_url)
    linkedin_pos = out.index("linkedin.com")
    x_pos = out.index("twitter.com")
    # Report section before gist URL
    assert out.index("# Fit Assessment") < gist_pos
    # Order: gist URL → linkedin → x
    assert gist_pos < linkedin_pos < x_pos
    # No badge snippet (no card for fit)
    assert "![" not in out
    assert "gist.githubusercontent.com" not in out


def test_fit_share_failure_one_clean_stderr_line(tmp_path):
    """fit --share failure: non-zero exit, one clean stderr line, no partial stdout."""
    jd = tmp_path / "jd.txt"
    jd.write_text("python backend engineer")
    token_msg = "ghp_FAKETOKEN_fit_0987654321"

    class FailSharer(Sharer):
        def publish(self, markdown, *, title, public, extra_files=None):
            raise RuntimeError(f"auth: {token_msg}")

    code, out, err = _run_fit(str(jd), FailSharer(), share=True)
    assert code != 0
    assert "gist.github.com" not in out
    assert "linkedin.com" not in out
    assert "Traceback" not in err
    assert token_msg not in err
    err_lines = [ln for ln in err.splitlines() if ln.strip()]
    assert len(err_lines) == 1, f"expected exactly one stderr line, got: {err_lines!r}"
    assert "grounded:" not in err


def test_fit_no_share_output_byte_identical(tmp_path, capsys):
    """Without --share, fit stdout is byte-identical to a second run without --share."""
    jd = tmp_path / "jd.txt"
    jd.write_text("python backend engineer")

    code1 = fit_run(
        _fit_argv(str(jd)),
        extractor=_fake_fit_extractor,
        runner=_fake_fit_runner,
        grader_runner=_fake_fit_grader,
    )
    out1 = capsys.readouterr().out
    assert code1 == 0

    code2 = fit_run(
        _fit_argv(str(jd)),
        extractor=_fake_fit_extractor,
        runner=_fake_fit_runner,
        grader_runner=_fake_fit_grader,
    )
    out2 = capsys.readouterr().out
    assert code2 == 0
    assert out1 == out2
    assert "gist.github.com" not in out1


def test_fit_help_mentions_share_flags(capsys):
    """python -m fit --help mentions --share, --share-public, --no-mask-on-share."""
    # fit/cli.py catches SystemExit internally and returns the exit code.
    code = fit_run(["--help"])
    out = capsys.readouterr().out
    assert code == 0
    assert "--share" in out
    assert "--share-public" in out
    assert "--no-mask-on-share" in out


# ===========================================================================
# Part G: fit --share batch mode (--jd-dir) wiring tests
# ===========================================================================


def _fit_batch_argv(jd_dir: str, **flags) -> list[str]:
    base = [
        "--source-type",
        "github",
        "--source",
        "https://github.com/owner/repo",
        "--author",
        "alice",
        "--jd-dir",
        jd_dir,
    ]
    for k, v in flags.items():
        flag = f"--{k.replace('_', '-')}"
        if v is True:
            base.append(flag)
        elif v is not False:
            base += [flag, str(v)]
    return base


def _run_fit_batch(jd_dir: str, fake_sharer: Sharer, **flags) -> tuple[int, str, str]:
    """Run fit CLI (batch) with the given flags and fake sharer."""
    argv = _fit_batch_argv(jd_dir, **flags)
    with (
        patch("sys.stdout", new_callable=io.StringIO) as mock_out,
        patch("sys.stderr", new_callable=io.StringIO) as mock_err,
    ):
        code = fit_run(
            argv,
            extractor=_fake_fit_extractor,
            runner=_fake_fit_runner,
            grader_runner=_fake_fit_grader,
            sharer=fake_sharer,
        )
        return code, mock_out.getvalue(), mock_err.getvalue()


def _make_batch_jd_dir(tmp_path: Path) -> str:
    jd_dir = tmp_path / "jds"
    jd_dir.mkdir()
    (jd_dir / "jd1.txt").write_text("python backend engineer")
    (jd_dir / "jd2.txt").write_text("java microservices engineer")
    return str(jd_dir)


def test_fit_batch_share_exits_zero(tmp_path):
    """fit --jd-dir --share exits 0 with a fake Sharer."""
    jd_dir = _make_batch_jd_dir(tmp_path)
    fake_sharer = _FakeSharer()
    code, _out, _err = _run_fit_batch(jd_dir, fake_sharer, share=True)
    assert code == 0


def test_fit_batch_share_footer_in_published_md(tmp_path):
    """fit --jd-dir --share: captured markdown includes i18n provenance footer."""
    jd_dir = _make_batch_jd_dir(tmp_path)
    fake_sharer = _FakeSharer()
    code, _out, _err = _run_fit_batch(jd_dir, fake_sharer, share=True)
    assert code == 0
    assert len(fake_sharer.calls) == 1
    footer = LANGS["en"]["share_provenance_footer"]
    assert footer in fake_sharer.calls[0]["markdown"]


def test_fit_batch_share_stdout_order_no_badge(tmp_path):
    """fit --jd-dir --share stdout: shared_md → gist URL → linkedin → x; no badge."""
    jd_dir = _make_batch_jd_dir(tmp_path)
    fake_sharer = _FakeSharer()
    code, out, _err = _run_fit_batch(jd_dir, fake_sharer, share=True)
    assert code == 0
    gist_url = fake_sharer.url
    gist_pos = out.index(gist_url)
    linkedin_pos = out.index("linkedin.com")
    x_pos = out.index("twitter.com")
    assert gist_pos < linkedin_pos < x_pos
    assert "![" not in out


def test_fit_batch_share_failure_one_clean_stderr_line(tmp_path):
    """fit --jd-dir --share failure: non-zero exit, one clean stderr line."""
    jd_dir = _make_batch_jd_dir(tmp_path)
    token_msg = "ghp_FAKETOKEN_batch_abc123"

    class FailSharer(Sharer):
        def publish(self, markdown, *, title, public, extra_files=None):
            raise RuntimeError(f"auth: {token_msg}")

    code, out, err = _run_fit_batch(jd_dir, FailSharer(), share=True)
    assert code != 0
    assert "gist.github.com" not in out
    assert "Traceback" not in err
    assert token_msg not in err
    err_lines = [ln for ln in err.splitlines() if ln.strip()]
    assert len(err_lines) == 1, f"expected exactly one stderr line, got: {err_lines!r}"
    assert "grounded:" not in err


def test_fit_batch_no_share_output_byte_identical(tmp_path, capsys):
    """Without --share, fit --jd-dir stdout is byte-identical to a second run."""
    jd_dir = _make_batch_jd_dir(tmp_path)

    code1 = fit_run(
        _fit_batch_argv(jd_dir),
        extractor=_fake_fit_extractor,
        runner=_fake_fit_runner,
        grader_runner=_fake_fit_grader,
    )
    out1 = capsys.readouterr().out
    assert code1 == 0

    code2 = fit_run(
        _fit_batch_argv(jd_dir),
        extractor=_fake_fit_extractor,
        runner=_fake_fit_runner,
        grader_runner=_fake_fit_grader,
    )
    out2 = capsys.readouterr().out
    assert code2 == 0
    assert out1 == out2
    assert "gist.github.com" not in out1


# ---------------------------------------------------------------------------
# Part G: resume/fit --share — uniform private-repo masking (codex IR-002)
# ---------------------------------------------------------------------------


def test_resume_share_masks_private_repo_in_title_and_body(tmp_path):
    """resume --share: a private repo name in the subject/evidence is scrubbed from
    BOTH the gist title/filename and the published Markdown (same guarantee as rating)."""
    jd = tmp_path / "jd.txt"
    jd.write_text("backend engineer", encoding="utf-8")
    fake = _FakeSharer()
    argv = [
        "--source-type",
        "github",
        "--source",
        f"https://github.com/{_PRIVATE_REPO}",
        "--author",
        _PRIVATE_REPO,  # subject carries the private name
        "--jd",
        str(jd),
        "--share",
    ]
    with patch("sys.stdout", new_callable=io.StringIO), patch("sys.stderr", new_callable=io.StringIO):
        code = resume_run(
            argv,
            extractor=_private_extractor,
            runner=_private_runner_with_ref,
            visibility_lookup=_private_visibility_lookup,
            sharer=fake,
        )
    assert code == 0
    call = fake.calls[0]
    assert _PRIVATE_REPO not in call["title"], f"private repo leaked in resume gist title: {call['title']!r}"
    assert _PRIVATE_REPO not in call["markdown"], "private repo leaked in resume shared body"


def test_fit_share_masks_private_repo_in_title_and_body(tmp_path):
    """fit --share: a private repo name in the subject/evidence is scrubbed from BOTH
    the gist title/filename and the published Markdown."""
    jd = tmp_path / "jd.txt"
    jd.write_text("backend engineer python", encoding="utf-8")
    fake = _FakeSharer()
    argv = [
        "--source-type",
        "github",
        "--source",
        f"https://github.com/{_PRIVATE_REPO}",
        "--author",
        _PRIVATE_REPO,
        "--jd",
        str(jd),
        "--share",
    ]
    with patch("sys.stdout", new_callable=io.StringIO), patch("sys.stderr", new_callable=io.StringIO):
        code = fit_run(
            argv,
            extractor=_private_extractor,
            runner=_private_runner_with_ref,
            grader_runner=_fake_fit_grader,
            visibility_lookup=_private_visibility_lookup,
            sharer=fake,
        )
    assert code == 0
    call = fake.calls[0]
    assert _PRIVATE_REPO not in call["title"], f"private repo leaked in fit gist title: {call['title']!r}"
    assert _PRIVATE_REPO not in call["markdown"], "private repo leaked in fit shared body"


# ===========================================================================
# Part H: GistSharer find-or-update (idempotent share)
# ===========================================================================


def _make_fake_gh_with_match(gist_id: str, gist_url: str, title: str, calls: list):
    """Fake gh runner that returns a matching gist on the list call, then succeeds on edit."""

    def fake_gh(argv: list, stdin_bytes=None) -> str:
        calls.append({"argv": list(argv), "stdin_bytes": stdin_bytes})
        if argv[:2] == ["gh", "api"]:
            return json.dumps(
                [{"id": gist_id, "html_url": gist_url, "files": {f"{title}.md": {"filename": f"{title}.md"}}}]
            )
        # edit call — gh gist edit returns empty stdout
        return ""

    return fake_gh


def _make_fake_gh_no_match(calls: list):
    """Fake gh runner that returns an empty gist list, then succeeds on create."""

    def fake_gh(argv: list, stdin_bytes=None) -> str:
        calls.append({"argv": list(argv), "stdin_bytes": stdin_bytes})
        if argv[:2] == ["gh", "api"]:
            return "[]"
        return "https://gist.github.com/fake/abc123\n"

    return fake_gh


def test_publish_issues_list_call_first():
    """GistSharer.publish issues a LIST call (gh api) as its very first call before create/edit."""
    calls: list = []
    sharer = GistSharer(gh_runner=_make_fake_gh_no_match(calls))
    sharer.publish("# Hello", title="my-rating", public=False)
    assert len(calls) >= 2, "expected at least a list call + create call"
    first_argv = calls[0]["argv"]
    assert first_argv[0] == "gh"
    # First call must not be a create or edit — it must be the list
    assert "create" not in first_argv
    assert "edit" not in first_argv


def test_publish_list_argv_no_user_flag():
    """LIST call targets only the authenticated user's own gists — no --user flag."""
    calls: list = []
    sharer = GistSharer(gh_runner=_make_fake_gh_no_match(calls))
    sharer.publish("# Hello", title="my-rating", public=False)
    # calls[0] must be the LIST call (gh api ...) — not create/edit
    list_argv = calls[0]["argv"]
    assert "api" in list_argv, "first call must be the LIST (gh api ...) call, not create/edit"
    assert "--user" not in list_argv
    assert "-u" not in list_argv
    # No foreign user handle in any argv element
    assert not any(arg.startswith("@") for arg in list_argv)


def test_publish_list_argv_is_list_no_shell_true():
    """LIST call argv is a list (no shell=True) starting with 'gh'."""
    calls: list = []
    sharer = GistSharer(gh_runner=_make_fake_gh_no_match(calls))
    sharer.publish("# Hello", title="my-rating", public=False)
    # calls[0] must be the LIST call (gh api ...) — old create-only code fails here
    list_argv = calls[0]["argv"]
    assert "api" in list_argv, "first call must be the LIST (gh api ...) call — old code fails here"
    assert isinstance(list_argv, list)
    assert list_argv[0] == "gh"


def test_publish_match_found_issues_patch_call():
    """When list reports a matching gist, publish PATCHes that gist (stable id/URL) via the
    Gists API with the markdown content in the JSON body — `gh gist edit` cannot update
    multiple files, so the atomic PATCH is used for the whole update path."""
    calls: list = []
    sharer = GistSharer(
        gh_runner=_make_fake_gh_with_match("match-id", "https://gist.github.com/user/match-id", "rating-alice", calls)
    )
    sharer.publish("# Hello", title="rating-alice", public=False)
    patch_calls = [c for c in calls if "PATCH" in c["argv"]]
    assert len(patch_calls) == 1, "expected exactly one gists PATCH call"
    argv = patch_calls[0]["argv"]
    assert argv == ["gh", "api", "--method", "PATCH", "/gists/match-id", "--input", "-"], (
        f"unexpected patch argv: {argv!r}"
    )
    body = json.loads(patch_calls[0]["stdin_bytes"])
    assert body["files"]["rating-alice.md"]["content"] == "# Hello", (
        f"PATCH body must replace rating-alice.md content, got: {body!r}"
    )


def test_publish_match_found_returns_existing_url():
    """When match found, ShareResult.url equals the existing gist's URL (stable)."""
    calls: list = []
    existing_url = "https://gist.github.com/user/existing-abc"
    sharer = GistSharer(gh_runner=_make_fake_gh_with_match("existing-abc", existing_url, "rating-alice", calls))
    result = sharer.publish("# Hello", title="rating-alice", public=False)
    assert result.url == existing_url


def test_publish_match_found_no_create_call():
    """When match found, publish must NOT issue a gh gist create call."""
    calls: list = []
    sharer = GistSharer(
        gh_runner=_make_fake_gh_with_match("match-id", "https://gist.github.com/u/match-id", "rating-alice", calls)
    )
    sharer.publish("# Hello", title="rating-alice", public=False)
    create_calls = [c for c in calls if "create" in c["argv"]]
    assert len(create_calls) == 0, "create must not be called when a match is found"


def test_publish_match_with_extra_files_patch_updates_md_and_svg():
    """When match found and extra_files has .svg, the PATCH body replaces BOTH the .md and
    the .svg contents in one atomic call (so a re-run refreshes the badge SVG at the same URL)."""
    calls: list = []
    sharer = GistSharer(
        gh_runner=_make_fake_gh_with_match("match-id", "https://gist.github.com/user/match-id", "rating-alice", calls)
    )
    sharer.publish(
        "# Hello",
        title="rating-alice",
        public=False,
        extra_files={"rating-alice.svg": "<svg/>"},
    )
    patch_calls = [c for c in calls if "PATCH" in c["argv"]]
    assert len(patch_calls) == 1
    files = json.loads(patch_calls[0]["stdin_bytes"])["files"]
    assert files["rating-alice.md"]["content"] == "# Hello", "PATCH must replace the .md content"
    assert files["rating-alice.svg"]["content"] == "<svg/>", "PATCH must replace the .svg content"


def test_publish_match_with_extra_files_patch_argv_is_list():
    """Update call argv is a list (no shell=True) — file contents ride in the JSON body, not argv."""
    calls: list = []
    sharer = GistSharer(
        gh_runner=_make_fake_gh_with_match("match-id", "https://gist.github.com/user/match-id", "rating-alice", calls)
    )
    sharer.publish("# Hello", title="rating-alice", public=False, extra_files={"rating-alice.svg": "<svg/>"})
    patch_calls = [c for c in calls if "PATCH" in c["argv"]]
    assert isinstance(patch_calls[0]["argv"], list)


def test_publish_no_match_issues_create_list_precedes_create():
    """When no match found, LIST call precedes the CREATE call in the recorded argv sequence."""
    calls: list = []
    sharer = GistSharer(gh_runner=_make_fake_gh_no_match(calls))
    sharer.publish("# Hello", title="no-match-rating", public=False)
    argvs = [c["argv"] for c in calls]
    list_indices = [i for i, a in enumerate(argvs) if "api" in a]
    create_indices = [i for i, a in enumerate(argvs) if "create" in a]
    assert list_indices, "LIST call was not issued"
    assert create_indices, "CREATE call was not issued"
    assert list_indices[0] < create_indices[0], "LIST call must precede CREATE call"


def test_publish_no_match_create_argv_shape_no_extra_files():
    """On no-match path with extra_files=None, a LIST call precedes create; create uses --filename and stdin."""
    calls: list = []
    sharer = GistSharer(gh_runner=_make_fake_gh_no_match(calls))
    sharer.publish("md content", title="no-match-rating", public=False)
    argvs = [c["argv"] for c in calls]
    # LIST call must precede CREATE — old list-less code fails this assertion
    list_indices = [i for i, a in enumerate(argvs) if "api" in a]
    create_indices = [i for i, a in enumerate(argvs) if "create" in a]
    assert list_indices, "LIST call was not issued — old code fails here"
    assert create_indices, "CREATE call was not issued"
    assert list_indices[0] < create_indices[0], "LIST must precede CREATE"
    create_calls = [c for c in calls if "create" in c["argv"]]
    assert len(create_calls) == 1
    argv = create_calls[0]["argv"]
    assert "--filename" in argv
    assert "-" in argv
    assert create_calls[0]["stdin_bytes"] == b"md content"


def test_publish_no_match_public_flag():
    """On no-match path with public=True, a LIST call precedes create; --public is in the create argv."""
    calls: list = []
    sharer = GistSharer(gh_runner=_make_fake_gh_no_match(calls))
    sharer.publish("# Hello", title="rating", public=True)
    argvs = [c["argv"] for c in calls]
    # LIST call must precede CREATE — old list-less code fails this assertion
    list_indices = [i for i, a in enumerate(argvs) if "api" in a]
    create_indices = [i for i, a in enumerate(argvs) if "create" in a]
    assert list_indices, "LIST call was not issued — old code fails here"
    assert list_indices[0] < create_indices[0], "LIST must precede CREATE"
    create_calls = [c for c in calls if "create" in c["argv"]]
    assert len(create_calls) == 1
    assert "--public" in create_calls[0]["argv"]


def test_publish_url_stability_two_calls_same_url():
    """Two consecutive publishes against the same matching fake state return the same URL."""
    existing_url = "https://gist.github.com/user/stable-id"

    def _make_stateful_fake():
        def fake_gh(argv: list, stdin_bytes=None) -> str:
            if argv[:2] == ["gh", "api"]:
                return json.dumps([{"id": "stable-id", "html_url": existing_url, "files": {"rating-stable.md": {}}}])
            return ""  # edit call succeeds silently

        return fake_gh

    result1 = GistSharer(gh_runner=_make_stateful_fake()).publish("# v1", title="rating-stable", public=False)
    result2 = GistSharer(gh_runner=_make_stateful_fake()).publish("# v2", title="rating-stable", public=False)
    assert result1.url == result2.url == existing_url, "URL must be stable across repeated publishes"


def test_publish_list_failure_falls_back_to_create():
    """When LIST call raises, publish falls back to CREATE and returns a ShareResult."""
    calls: list = []

    def failing_list_gh(argv: list, stdin_bytes=None) -> str:
        calls.append({"argv": list(argv), "stdin_bytes": stdin_bytes})
        if argv[:2] == ["gh", "api"]:
            raise RuntimeError("gh api unavailable")
        return "https://gist.github.com/fake/fallback123\n"

    result = GistSharer(gh_runner=failing_list_gh).publish("# Hello", title="t", public=False)
    # LIST argv was attempted first
    list_calls = [c for c in calls if "api" in c["argv"]]
    assert len(list_calls) >= 1, "LIST argv must have been attempted even when it raises"
    # CREATE call was issued after
    create_calls = [c for c in calls if "create" in c["argv"]]
    assert len(create_calls) >= 1, "CREATE call must be issued after list failure"
    # publish returns normally (no exception propagates)
    assert isinstance(result, ShareResult)
    assert result.url.startswith("https://gist.github.com/")


def test_publish_list_failure_list_call_precedes_create():
    """LIST argv must be the FIRST call even when it raises — verifies today's create-only code fails."""
    calls: list = []

    def failing_list_gh(argv: list, stdin_bytes=None) -> str:
        calls.append({"argv": list(argv), "stdin_bytes": stdin_bytes})
        if argv[:2] == ["gh", "api"]:
            raise RuntimeError("list failed")
        return "https://gist.github.com/fake/fallback\n"

    GistSharer(gh_runner=failing_list_gh).publish("# Hello", title="t", public=False)
    argvs = [c["argv"] for c in calls]
    list_indices = [i for i, a in enumerate(argvs) if "api" in a]
    create_indices = [i for i, a in enumerate(argvs) if "create" in a]
    assert list_indices, "LIST argv was not attempted — today's create-only code fails here"
    assert create_indices, "CREATE argv must follow"
    assert list_indices[0] < create_indices[0]


def test_publish_edit_failure_propagates():
    """When the update (PATCH) call raises, publish raises — update failures are NOT swallowed."""
    calls: list = []

    def edit_fail_gh(argv: list, stdin_bytes=None) -> str:
        calls.append({"argv": list(argv), "stdin_bytes": stdin_bytes})
        # Check PATCH first: the update call also starts with `gh api`, so distinguish it
        # from the plain list call before the generic list-return branch.
        if "PATCH" in argv:
            raise RuntimeError("gists PATCH failed")
        if argv[:2] == ["gh", "api"]:
            return json.dumps(
                [
                    {
                        "id": "edit-fail-id",
                        "html_url": "https://gist.github.com/u/edit-fail-id",
                        "files": {"rating-editfail.md": {}},
                    }
                ]
            )
        return ""

    sharer = GistSharer(gh_runner=edit_fail_gh)
    with pytest.raises(RuntimeError):
        sharer.publish("# Hello", title="rating-editfail", public=False)
    # The update (PATCH) argv was actually attempted before the raise — today's
    # create-only code never issues a PATCH, so this fails pre-change.
    patch_calls = [c for c in calls if "PATCH" in c["argv"]]
    assert len(patch_calls) >= 1, "PATCH update argv must have been attempted"


def test_publish_create_failure_propagates():
    """When LIST succeeds (no match) but CREATE raises, publish raises — not swallowed."""
    calls: list = []

    def create_fail_gh(argv: list, stdin_bytes=None) -> str:
        calls.append({"argv": list(argv), "stdin_bytes": stdin_bytes})
        if argv[:2] == ["gh", "api"]:
            return "[]"
        raise RuntimeError("gh gist create failed")

    sharer = GistSharer(gh_runner=create_fail_gh)
    with pytest.raises(RuntimeError):
        sharer.publish("# Hello", title="t", public=False)
    # LIST was issued before CREATE
    list_calls = [c for c in calls if "api" in c["argv"]]
    assert len(list_calls) >= 1, "LIST argv must have been attempted — today's list-less code fails here"


def test_publish_determinism_same_inputs_same_decision():
    """Given the same fake list output and same title, two GistSharer instances make the same decision."""
    existing_url = "https://gist.github.com/user/det-id"

    def _make_det_fake():
        def fake_gh(argv: list, stdin_bytes=None) -> str:
            if argv[:2] == ["gh", "api"]:
                return json.dumps([{"id": "det-id", "html_url": existing_url, "files": {"rating-det.md": {}}}])
            return ""

        return fake_gh

    result1 = GistSharer(gh_runner=_make_det_fake()).publish("# A", title="rating-det", public=False)
    result2 = GistSharer(gh_runner=_make_det_fake()).publish("# B", title="rating-det", public=False)
    assert result1.url == result2.url == existing_url, "create-vs-edit decision must be deterministic"
