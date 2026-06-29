"""Tests for portfolio/share.py and rating --share wiring.

Covers:
- GistSharer argv shape (secret vs public, no shell=True)
- Injectable gh runner (no live gh in tests)
- share_links URL-encoding
- rating --share masking-on-by-default + --no-mask-on-share opt-out + --mask-private interactions
- Provenance footer in shared Markdown (en + ko)
- Share-off output byte-identical to non-share path
- Publish failure → non-zero exit + clean stderr + no partial stdout emit
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.i18n import LANGS  # noqa: E402
from portfolio.model import Evidence  # noqa: E402
from portfolio.share import GistSharer, ShareResult, Sharer, share_links  # noqa: E402
from rating.cli import run  # noqa: E402


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
    assert len(calls) == 1
    argv = calls[0]["argv"]
    assert "--public" not in argv
    assert result.url == "https://gist.github.com/fake/abc123"


def test_gist_sharer_public_flag_present():
    """When public=True, --public appears in the argv."""
    calls: list = []
    sharer = GistSharer(gh_runner=_make_fake_gh(calls))
    sharer.publish("# Hello", title="my-rating", public=True)
    argv = calls[0]["argv"]
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
    assert len(calls) == 1  # exactly one call to fake, not real gh
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

    def publish(self, markdown: str, *, title: str, public: bool) -> ShareResult:
        self.calls.append({"markdown": markdown, "title": title, "public": public})
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
        def publish(self, markdown, *, title, public):
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
        def publish(self, markdown, *, title, public):
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
        def publish(self, markdown, *, title, public):
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
