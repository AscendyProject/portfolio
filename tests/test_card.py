"""Tests for portfolio/card.py SVG renderer and related CLI/share wiring.

Covers:
- render_card() returns well-formed XML with <svg> root
- Byte-deterministic across calls with identical inputs
- XML-escape of < > & " in subject, strength bullets, and verify_url
- Self-containment: no <script>, no external <image>/<link>, no @import
- Contains grade letter and numeric score
- Contains i18n card_tagline for en and ko
- No banned percentile/ranking lexicon
- gist_raw_url() pure string derivation
- --out-card writes file; OSError → non-zero exit + clean stderr
- --share: extra_files has .svg entry, badge snippet printed
- Masking parity: private repo name scrubbed from card body and svg filename
- GistSharer with extra_files: argv contains both file paths from single tmpdir
"""

from __future__ import annotations

import io
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.card import render_card  # noqa: E402
from portfolio.i18n import LANGS  # noqa: E402
from portfolio.model import Evidence  # noqa: E402
from portfolio.share import GistSharer, ShareResult, Sharer, gist_raw_url  # noqa: E402
from rating.cli import run  # noqa: E402
from rating.grade import GradeResult, _BANNED_PERCENTILE_RE  # noqa: E402
from rating.profile import DimensionResult, ProfileResult  # noqa: E402

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _make_profile_result(grade: str = "A", score: float = 87.0) -> ProfileResult:
    dims = {
        "volume": DimensionResult(name="volume", value=50, band="High"),
        "breadth": DimensionResult(name="breadth", value=100, band="Moderate"),
        "stack_diversity": DimensionResult(name="stack_diversity", value=3, band="Versatile"),
        "scale": DimensionResult(name="scale", value=50, band="Medium"),
    }
    score_min, score_max = {"S": (96, 100), "A": (85, 95), "B": (70, 84), "C": (55, 69), "D": (0, 54)}[grade]
    return ProfileResult(dimensions=dims, grade=grade, score_min=score_min, score_max=score_max, score=score)


def _make_grade_result(
    grade: str = "A",
    score: int = 87,
    reasoning: list | None = None,
) -> GradeResult:
    if reasoning is None:
        reasoning = [
            {"text": "Built a new authentication system", "evidence_refs": ["PR#1"]},
            {"text": "Refactored the data pipeline", "evidence_refs": ["PR#2"]},
        ]
    return GradeResult(score=score, grade=grade, reasoning=reasoning)


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
# A. render_card() — well-formed XML, SVG root
# ---------------------------------------------------------------------------


def test_render_card_returns_string():
    """render_card() returns a str."""
    result = render_card(_make_profile_result(), _make_grade_result(), subject="alice/repo")
    assert isinstance(result, str)


def test_render_card_valid_xml():
    """render_card() output parses as well-formed XML with an <svg> root element."""
    svg = render_card(_make_profile_result(), _make_grade_result(), subject="alice/repo")
    root = ET.fromstring(svg)
    # Tag may have namespace prefix
    assert root.tag.endswith("svg"), f"root tag is not svg: {root.tag!r}"


# ---------------------------------------------------------------------------
# B. render_card() — byte-deterministic
# ---------------------------------------------------------------------------


def test_render_card_is_deterministic():
    """Same inputs → byte-identical SVG across two consecutive calls."""
    pr = _make_profile_result()
    gr = _make_grade_result()
    svg1 = render_card(pr, gr, subject="alice/repo", lang="en")
    svg2 = render_card(pr, gr, subject="alice/repo", lang="en")
    assert svg1 == svg2


def test_render_card_deterministic_with_verify_url():
    """Determinism holds when verify_url is provided."""
    pr = _make_profile_result()
    gr = _make_grade_result()
    url = "https://gist.github.com/user/abc"
    assert render_card(pr, gr, subject="alice", verify_url=url) == render_card(pr, gr, subject="alice", verify_url=url)


# ---------------------------------------------------------------------------
# C. render_card() — XML-escape of injected text
# ---------------------------------------------------------------------------


def test_render_card_xml_escapes_subject_angle_brackets():
    """< and > in subject must be XML-escaped; SVG must still parse."""
    subject = "alice<evil>repo"
    svg = render_card(_make_profile_result(), _make_grade_result(), subject=subject)
    ET.fromstring(svg)  # must not raise
    assert "<evil>" not in svg
    assert "&lt;evil&gt;" in svg


def test_render_card_xml_escapes_subject_ampersand():
    """& in subject must be XML-escaped."""
    subject = "alice&repo"
    svg = render_card(_make_profile_result(), _make_grade_result(), subject=subject)
    ET.fromstring(svg)
    assert "alice&repo" not in svg
    assert "&amp;" in svg


def test_render_card_xml_escapes_reasoning_bullets():
    """< > & in strength bullet text are XML-escaped."""
    reasoning = [{"text": "Fixed <critical> bug & improved perf", "evidence_refs": ["PR#1"]}]
    gr = _make_grade_result(reasoning=reasoning)
    svg = render_card(_make_profile_result(), gr, subject="alice")
    ET.fromstring(svg)
    assert "<critical>" not in svg
    assert "&lt;critical&gt;" in svg
    assert "bug & improved" not in svg
    assert "bug &amp; improved" in svg


def test_render_card_xml_escapes_verify_url_ampersand():
    """& in verify_url must be XML-escaped."""
    verify_url = "https://example.com?a=1&b=2"
    svg = render_card(_make_profile_result(), _make_grade_result(), subject="alice", verify_url=verify_url)
    ET.fromstring(svg)
    assert "a=1&b=2" not in svg
    assert "a=1&amp;b=2" in svg


def test_render_card_xml_escapes_double_quotes():
    """A double quote injected via subject or bullet must NOT survive raw (it is
    escaped to &quot;) — default xml escape leaves quotes untouched."""
    subject = 'alice"onload="x'
    reasoning = [{"text": 'say "hi" then break', "evidence_refs": ["PR#1"]}]
    svg = render_card(_make_profile_result(), _make_grade_result(reasoning=reasoning), subject=subject)
    ET.fromstring(svg)  # still well-formed
    assert 'alice"onload' not in svg
    assert 'say "hi"' not in svg
    assert "&quot;" in svg


def test_render_card_drops_banned_percentile_bullets():
    """The card enforces the no-percentile/ranking output gate on its OWN output
    (issue #60): a banned-term bullet is dropped even if the GradeResult bypassed
    the rating-time gate, while a clean bullet survives."""
    reasoning = [
        {"text": "Top percentile globally ranked", "evidence_refs": ["PR#1"]},
        {"text": "Shipped a robust auth refactor", "evidence_refs": ["PR#2"]},
    ]
    svg = render_card(_make_profile_result(), _make_grade_result(reasoning=reasoning), subject="alice")
    assert not _BANNED_PERCENTILE_RE.search(svg), "banned ranking lexicon leaked into the card SVG"
    assert "percentile" not in svg and "globally" not in svg
    assert "auth refactor" in svg  # the clean bullet is kept


def test_render_card_strips_banned_lexicon_from_subject_and_url():
    """The no-ranking invariant covers ALL channels, not just bullets: a banned term
    in the subject or verify_url is stripped from the card SVG too (codex IR-005)."""
    svg = render_card(
        _make_profile_result(),
        _make_grade_result(),
        subject="top-percentile-dev",
        verify_url="https://example.test/?rank=1",
    )
    ET.fromstring(svg)
    assert not _BANNED_PERCENTILE_RE.search(svg), "banned lexicon leaked via subject/verify_url"
    assert "percentile" not in svg


# ---------------------------------------------------------------------------
# D. render_card() — self-containment
# ---------------------------------------------------------------------------


def test_render_card_no_script():
    """Returned SVG contains no <script> element."""
    svg = render_card(_make_profile_result(), _make_grade_result(), subject="alice")
    assert "<script" not in svg.lower()


def test_render_card_no_external_image():
    """No external <image> or <link> with http(s) src/href."""
    import re

    svg = render_card(_make_profile_result(), _make_grade_result(), subject="alice")
    svg_lower = svg.lower()
    assert not re.search(r"<image[^>]+href\s*=\s*['\"]https?://", svg_lower)
    assert not re.search(r"<link[^>]+href\s*=\s*['\"]https?://", svg_lower)


def test_render_card_no_import():
    """No @import (external font or style) in the SVG."""
    svg = render_card(_make_profile_result(), _make_grade_result(), subject="alice")
    assert "@import" not in svg


# ---------------------------------------------------------------------------
# E. render_card() — contains grade letter and score
# ---------------------------------------------------------------------------


def test_render_card_contains_grade_letter():
    """Grade letter appears as visible text in the SVG."""
    svg = render_card(
        _make_profile_result(grade="B", score=77.0), _make_grade_result(grade="B", score=77), subject="alice"
    )
    assert "B" in svg


def test_render_card_contains_score():
    """Numeric score appears as visible text in the SVG."""
    svg = render_card(
        _make_profile_result(grade="A", score=88.0), _make_grade_result(grade="A", score=88), subject="alice"
    )
    assert "88" in svg


def test_render_card_grade_s():
    """Grade S is rendered correctly."""
    svg = render_card(
        _make_profile_result(grade="S", score=98.0), _make_grade_result(grade="S", score=98), subject="dev"
    )
    assert "S" in svg
    assert "98" in svg


# ---------------------------------------------------------------------------
# F. render_card() — i18n tagline present for en and ko
# ---------------------------------------------------------------------------


def test_render_card_en_tagline():
    """card_tagline for lang='en' appears in the SVG."""
    svg = render_card(_make_profile_result(), _make_grade_result(), subject="alice", lang="en")
    tagline = LANGS["en"]["card_tagline"]
    assert tagline, "card_tagline for en must be non-empty"
    assert tagline in svg


def test_render_card_ko_tagline():
    """card_tagline for lang='ko' appears in the SVG."""
    svg = render_card(_make_profile_result(), _make_grade_result(), subject="alice", lang="ko")
    tagline = LANGS["ko"]["card_tagline"]
    assert tagline, "card_tagline for ko must be non-empty"
    assert tagline in svg


def test_card_tagline_keys_exist_and_nonempty():
    """Both LANGS['en'] and LANGS['ko'] define card_tagline as a non-empty string."""
    for lang in ("en", "ko"):
        val = LANGS[lang].get("card_tagline")
        assert isinstance(val, str), f"LANGS[{lang!r}]['card_tagline'] is not a str"
        assert val.strip(), f"LANGS[{lang!r}]['card_tagline'] is empty"


# ---------------------------------------------------------------------------
# G. render_card() — no banned percentile/ranking lexicon
# ---------------------------------------------------------------------------


def test_render_card_no_banned_lexicon():
    """SVG body contains none of the BANNED_PERCENTILE_LEXICON words."""
    svg = render_card(_make_profile_result(), _make_grade_result(), subject="alice")
    assert not _BANNED_PERCENTILE_RE.search(svg), "banned percentile/ranking lexicon found in rendered SVG card"


# ---------------------------------------------------------------------------
# H. gist_raw_url() — pure string derivation
# ---------------------------------------------------------------------------


def test_gist_raw_url_basic():
    url = gist_raw_url("https://gist.github.com/user/abc123", "rating.svg")
    assert url == "https://gist.githubusercontent.com/user/abc123/raw/rating.svg"


def test_gist_raw_url_trailing_slash():
    url = gist_raw_url("https://gist.github.com/user/abc123/", "rating.svg")
    assert url == "https://gist.githubusercontent.com/user/abc123/raw/rating.svg"


def test_gist_raw_url_filename_passthrough():
    """The filename is embedded as-is in the raw URL path."""
    url = gist_raw_url("https://gist.github.com/u/id", "rating-alice.svg")
    assert url.endswith("/raw/rating-alice.svg")
    assert "gist.githubusercontent.com" in url


def test_gist_raw_url_deterministic():
    url1 = gist_raw_url("https://gist.github.com/u/id", "f.svg")
    url2 = gist_raw_url("https://gist.github.com/u/id", "f.svg")
    assert url1 == url2


# ---------------------------------------------------------------------------
# I. --out-card flag: writes file; OSError → non-zero + clean stderr
# ---------------------------------------------------------------------------


def test_out_card_writes_svg_file(tmp_path):
    """--out-card <path> writes the rendered SVG to the file and exits 0."""
    card_path = tmp_path / "card.svg"
    code = run(
        _rating_argv(out_card=str(card_path)),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
    )
    assert code == 0
    assert card_path.exists()
    content = card_path.read_text(encoding="utf-8")
    assert "<svg" in content
    assert "<?xml" in content


def test_out_card_content_is_valid_xml(tmp_path):
    """The written card file is valid XML."""
    card_path = tmp_path / "card.svg"
    run(
        _rating_argv(out_card=str(card_path)),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
    )
    ET.parse(str(card_path))  # must not raise


def test_out_card_oserror_nonzero_exit(capsys):
    """Unwritable --out-card path: exits non-zero."""
    bad_path = "/nonexistent_dir_qwerty/card.svg"
    code = run(
        _rating_argv(out_card=bad_path),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
    )
    capsys.readouterr()
    assert code != 0


def test_out_card_oserror_clean_stderr(capsys):
    """Unwritable --out-card path: stderr contains a clean error line (no traceback)."""
    bad_path = "/nonexistent_dir_qwerty/card.svg"
    code = run(
        _rating_argv(out_card=bad_path),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
    )
    captured = capsys.readouterr()
    assert code != 0
    assert "Traceback" not in captured.err
    # At least one error line mentioning the card path or "out-card"
    err_lines = [ln for ln in captured.err.splitlines() if ln.strip()]
    assert any("card" in ln.lower() or bad_path in ln for ln in err_lines)


# ---------------------------------------------------------------------------
# J. Masking parity: private repo name scrubbed from card
# ---------------------------------------------------------------------------

_PRIVATE_REPO = "secret-org/private-svc"


def _private_extractor(*, repo: str, author: str, limit: int = 100) -> list[Evidence]:
    return [
        Evidence(
            kind="pr",
            ref=f"{_PRIVATE_REPO}#1",
            url=f"https://github.com/{_PRIVATE_REPO}/pull/1",
            detail=f"PR in {_PRIVATE_REPO}",
        )
    ]


def _private_visibility_lookup(repo: str) -> bool:
    return True  # all repos are private


def _private_runner(prompt: str) -> str:
    return json.dumps(
        [{"text": f"Feature in {_PRIVATE_REPO}", "evidence_refs": [f"{_PRIVATE_REPO}#1"], "confidence": 0.9}]
    )


class _CapturingSharer(Sharer):
    """Captures publish calls and returns a fake gist URL."""

    def __init__(self):
        self.calls: list[dict] = []

    def publish(self, markdown, *, title, public, extra_files=None):
        self.calls.append({"markdown": markdown, "title": title, "extra_files": extra_files})
        return ShareResult(url="https://gist.github.com/user/abc")


def test_share_card_masks_private_repo_in_body():
    """Under --share, private repo name is scrubbed from the SVG card body."""
    sharer = _CapturingSharer()
    with patch("sys.stdout", new_callable=io.StringIO), patch("sys.stderr", new_callable=io.StringIO):
        code = run(
            [
                "--source-type",
                "github",
                "--source",
                f"https://github.com/{_PRIVATE_REPO}",
                "--author",
                "alice",
                "--share",
            ],
            extractor=_private_extractor,
            runner=_private_runner,
            grader_runner=_fake_grader_runner,
            visibility_lookup=_private_visibility_lookup,
            sharer=sharer,
        )
    assert code == 0
    extra_files = sharer.calls[0]["extra_files"]
    assert extra_files is not None
    svg_body = next(iter(extra_files.values()))
    assert _PRIVATE_REPO not in svg_body, "private repo name leaked in SVG card body"


def test_share_card_masks_private_repo_in_svg_filename():
    """Under --share, private repo name is scrubbed from the .svg extra_files key."""
    sharer = _CapturingSharer()
    with patch("sys.stdout", new_callable=io.StringIO), patch("sys.stderr", new_callable=io.StringIO):
        code = run(
            [
                "--source-type",
                "github",
                "--source",
                f"https://github.com/{_PRIVATE_REPO}",
                "--author",
                "alice",
                "--share",
            ],
            extractor=_private_extractor,
            runner=_private_runner,
            grader_runner=_fake_grader_runner,
            visibility_lookup=_private_visibility_lookup,
            sharer=sharer,
        )
    assert code == 0
    extra_files = sharer.calls[0]["extra_files"]
    svg_key = next(iter(extra_files.keys()))
    assert _PRIVATE_REPO not in svg_key, f"private repo name leaked in .svg filename: {svg_key!r}"


# ---------------------------------------------------------------------------
# K. --share: extra_files carries exactly one .svg entry; badge line printed
# ---------------------------------------------------------------------------


def test_share_extra_files_has_svg_entry(capsys):
    """Under --share, extra_files has exactly one .svg entry and no .md entry."""
    fake_sharer = _CapturingSharer()
    code = run(
        _rating_argv(share=True),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
        sharer=fake_sharer,
    )
    capsys.readouterr()
    assert code == 0
    extra_files = fake_sharer.calls[0]["extra_files"]
    assert extra_files is not None
    svg_keys = [k for k in extra_files if k.endswith(".svg")]
    md_keys = [k for k in extra_files if k.endswith(".md")]
    assert len(svg_keys) == 1, f"expected 1 .svg entry in extra_files, got {svg_keys}"
    assert len(md_keys) == 0, f"no .md entry should be in extra_files, got {md_keys}"


def test_share_markdown_still_primary_argument(capsys):
    """Under --share, the primary Markdown is still the positional publish() arg."""
    fake_sharer = _CapturingSharer()
    code = run(
        _rating_argv(share=True),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
        sharer=fake_sharer,
    )
    capsys.readouterr()
    assert code == 0
    # The markdown arg must contain the rating heading
    assert "# Capability Rating" in fake_sharer.calls[0]["markdown"]


def test_share_badge_snippet_in_stdout(capsys):
    """Under --share, stdout includes a README badge snippet on the last line before EOF."""
    fake_sharer = _CapturingSharer()
    code = run(
        _rating_argv(share=True),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
        sharer=fake_sharer,
    )
    out = capsys.readouterr().out
    assert code == 0
    # Badge is Markdown image syntax with a gist.githubusercontent.com raw URL
    assert "![Capability rating](" in out
    assert "gist.githubusercontent.com" in out


def test_share_badge_uses_gist_raw_url(capsys):
    """Badge URL is gist_raw_url(gist_url, svg_filename)."""
    fake_sharer = _CapturingSharer()
    code = run(
        _rating_argv(share=True),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
        sharer=fake_sharer,
    )
    out = capsys.readouterr().out
    assert code == 0
    # The fake sharer returns "https://gist.github.com/user/abc"
    expected_raw_base = "https://gist.githubusercontent.com/user/abc/raw/"
    assert expected_raw_base in out


def test_share_badge_after_social_links(capsys):
    """Badge snippet appears AFTER the gist URL + social link lines."""
    fake_sharer = _CapturingSharer()
    code = run(
        _rating_argv(share=True),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
        sharer=fake_sharer,
    )
    out = capsys.readouterr().out
    assert code == 0
    gist_pos = out.index("gist.github.com/user/abc")
    linkedin_pos = out.index("linkedin.com")
    badge_pos = out.index("![Capability rating](")
    assert gist_pos < linkedin_pos < badge_pos


# ---------------------------------------------------------------------------
# L. GistSharer multi-file: argv has both files in same tmpdir, no shell=True
# ---------------------------------------------------------------------------


def _make_fake_gh(calls: list):
    def fake_gh(argv: list, stdin_bytes=None) -> str:
        calls.append({"argv": list(argv), "stdin_bytes": stdin_bytes})
        return "https://gist.github.com/fake/abc123\n"

    return fake_gh


def test_gist_sharer_extra_files_argv_has_both_paths():
    """GistSharer.publish with extra_files: argv contains paths for both .md and .svg."""
    calls: list = []
    sharer = GistSharer(gh_runner=_make_fake_gh(calls))
    sharer.publish(
        "# Hello",
        title="my-rating",
        public=False,
        extra_files={"my-rating.svg": "<svg/>"},
    )
    argv = calls[0]["argv"]
    assert isinstance(argv, list)
    assert argv[0] == "gh"
    md_paths = [a for a in argv if a.endswith(".md")]
    svg_paths = [a for a in argv if a.endswith(".svg")]
    assert len(md_paths) == 1
    assert len(svg_paths) == 1


def test_gist_sharer_extra_files_single_tmpdir():
    """Both file paths in argv share the same parent directory (one TemporaryDirectory)."""
    calls: list = []
    sharer = GistSharer(gh_runner=_make_fake_gh(calls))
    sharer.publish(
        "# Hello",
        title="my-rating",
        public=False,
        extra_files={"my-rating.svg": "<svg/>"},
    )
    argv = calls[0]["argv"]
    md_paths = [a for a in argv if a.endswith(".md")]
    svg_paths = [a for a in argv if a.endswith(".svg")]
    assert os.path.dirname(md_paths[0]) == os.path.dirname(svg_paths[0])


def test_gist_sharer_extra_files_no_stdin():
    """Multi-file publish does not pass stdin bytes (files used instead)."""
    calls: list = []
    sharer = GistSharer(gh_runner=_make_fake_gh(calls))
    sharer.publish("md", title="t", public=False, extra_files={"t.svg": "<svg/>"})
    assert calls[0]["stdin_bytes"] is None


def test_gist_sharer_extra_files_no_shell_true():
    """argv is a list (not a string); the fake runner receives a list — no shell=True."""
    calls: list = []
    sharer = GistSharer(gh_runner=_make_fake_gh(calls))
    sharer.publish("md", title="t", public=False, extra_files={"t.svg": "<svg/>"})
    # If shell=True were used, argv would be a string; assert it is a list.
    assert isinstance(calls[0]["argv"], list)


# ---------------------------------------------------------------------------
# M. --out-card .png routing: invokes rasterizer; .svg unchanged (task-031)
# ---------------------------------------------------------------------------


def _fake_rasterizer(svg: str) -> bytes:
    """Deterministic fake rasterizer: returns known bytes embedding the SVG."""
    return b"FAKEPNG:" + svg.encode()


def test_out_card_png_calls_rasterizer_and_writes_bytes(tmp_path):
    """--out-card foo.png invokes the injected rasterizer with the rendered SVG string
    and writes the returned bytes verbatim (binary write, not text)."""
    card_path = tmp_path / "card.png"
    calls: list[str] = []

    def _tracking_rasterizer(svg: str) -> bytes:
        calls.append(svg)
        return b"FAKEPNG:" + svg.encode()

    code = run(
        _rating_argv(out_card=str(card_path)),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
        rasterizer=_tracking_rasterizer,
    )
    assert code == 0
    assert card_path.exists()
    assert len(calls) == 1, "rasterizer must be called exactly once"
    svg_passed = calls[0]
    assert "<svg" in svg_passed, "rasterizer should receive the rendered SVG string"
    written = card_path.read_bytes()
    assert written == b"FAKEPNG:" + svg_passed.encode(), "written bytes must match rasterizer return value verbatim"


def test_out_card_svg_does_not_call_rasterizer(tmp_path):
    """--out-card foo.svg does NOT invoke the rasterizer and writes SVG text."""
    card_path = tmp_path / "card.svg"
    calls: list[str] = []

    def _tracking_rasterizer(svg: str) -> bytes:  # pragma: no cover
        calls.append(svg)
        return b"SHOULD NOT BE CALLED"

    code = run(
        _rating_argv(out_card=str(card_path)),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
        rasterizer=_tracking_rasterizer,
    )
    assert code == 0
    assert len(calls) == 0, "rasterizer must NOT be called for .svg output"
    content = card_path.read_text(encoding="utf-8")
    assert "<svg" in content
    assert "<?xml" in content


def test_out_card_svg_byte_identical_to_render_card(tmp_path):
    """--out-card foo.svg writes bytes identical to render_card(...) for the same inputs."""
    card_path = tmp_path / "card.svg"
    code = run(
        _rating_argv(out_card=str(card_path)),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
    )
    assert code == 0
    written = card_path.read_text(encoding="utf-8")
    # The file should be valid, self-contained SVG (byte-identical to render_card output).
    root = ET.fromstring(written)
    assert root.tag.endswith("svg")


# ---------------------------------------------------------------------------
# N. Missing-extra failure path (task-031)
# ---------------------------------------------------------------------------


def test_out_card_png_missing_extra_nonzero_exit(tmp_path):
    """CardExtraMissingError from rasterizer → non-zero exit."""
    from portfolio.card import CardExtraMissingError

    card_path = tmp_path / "card.png"

    def _missing_rasterizer(svg: str) -> bytes:
        raise CardExtraMissingError("pip install 'portfolio[card]'")

    code = run(
        _rating_argv(out_card=str(card_path)),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
        rasterizer=_missing_rasterizer,
    )
    assert code != 0


def test_out_card_png_missing_extra_hint_in_stderr(tmp_path, capsys):
    """CardExtraMissingError → stderr contains the install hint; no Traceback."""
    from portfolio.card import CardExtraMissingError

    card_path = tmp_path / "card.png"

    def _missing_rasterizer(svg: str) -> bytes:
        raise CardExtraMissingError("pip install 'portfolio[card]'")

    run(
        _rating_argv(out_card=str(card_path)),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
        rasterizer=_missing_rasterizer,
    )
    captured = capsys.readouterr()
    assert "pip install 'portfolio[card]'" in captured.err
    assert "Traceback" not in captured.err


def test_out_card_png_missing_extra_no_file_created(tmp_path):
    """CardExtraMissingError → target .png file is NOT created (no partial file)."""
    from portfolio.card import CardExtraMissingError

    card_path = tmp_path / "card.png"

    def _missing_rasterizer(svg: str) -> bytes:
        raise CardExtraMissingError("pip install 'portfolio[card]'")

    run(
        _rating_argv(out_card=str(card_path)),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
        rasterizer=_missing_rasterizer,
    )
    assert not card_path.exists(), "target PNG must not be created on missing-extra failure"


# ---------------------------------------------------------------------------
# O. OSError on .png write (task-031)
# ---------------------------------------------------------------------------


def test_out_card_png_oserror_nonzero_exit(capsys):
    """OSError on .png write (after rasterizer succeeds) → non-zero exit."""
    bad_path = "/nonexistent_dir_qwerty/card.png"
    code = run(
        _rating_argv(out_card=bad_path),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
        rasterizer=_fake_rasterizer,
    )
    capsys.readouterr()
    assert code != 0


def test_out_card_png_oserror_clean_stderr(capsys):
    """OSError on .png write → stderr has a clean error line; no Traceback."""
    bad_path = "/nonexistent_dir_qwerty/card.png"
    run(
        _rating_argv(out_card=bad_path),
        extractor=_fake_extractor,
        runner=_fake_runner,
        grader_runner=_fake_grader_runner,
        rasterizer=_fake_rasterizer,
    )
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    err_lines = [ln for ln in captured.err.splitlines() if ln.strip()]
    assert any("card" in ln.lower() or bad_path in ln or "out-card" in ln.lower() for ln in err_lines)


# ---------------------------------------------------------------------------
# P. svg_to_png raises CardExtraMissingError when cairosvg absent (task-031)
# ---------------------------------------------------------------------------


def test_svg_to_png_raises_card_extra_missing_when_cairosvg_absent():
    """svg_to_png raises CardExtraMissingError with install-hint when cairosvg is absent.
    Simulated by patching sys.modules to block cairosvg."""
    from portfolio.card import CardExtraMissingError, svg_to_png

    with patch.dict(sys.modules, {"cairosvg": None}):
        with pytest.raises(CardExtraMissingError) as exc_info:
            svg_to_png("<svg/>")

    assert "pip install 'portfolio[card]'" in str(exc_info.value)


def test_svg_to_png_card_extra_missing_is_exception_subclass():
    """CardExtraMissingError is a subclass of Exception."""
    from portfolio.card import CardExtraMissingError

    assert issubclass(CardExtraMissingError, Exception)


# ---------------------------------------------------------------------------
# Q. Real cairosvg happy path — guarded by importorskip (task-031)
# ---------------------------------------------------------------------------


def test_svg_to_png_real_png_signature():
    """With real cairosvg installed, svg_to_png returns non-empty bytes starting with PNG magic.
    Guarded by pytest.importorskip — skipped when cairosvg is not installed."""
    pytest.importorskip("cairosvg")
    from portfolio.card import render_card, svg_to_png

    svg = render_card(_make_profile_result(), _make_grade_result(), subject="alice/repo")
    result = svg_to_png(svg)
    assert isinstance(result, bytes)
    assert len(result) > 0
    assert result[:8] == b"\x89PNG\r\n\x1a\n", "result must start with PNG signature"


# ---------------------------------------------------------------------------
# R. pyproject.toml shape check (task-031)
# ---------------------------------------------------------------------------


def test_pyproject_card_extra_present_and_no_runtime_deps():
    """pyproject.toml has card = ['cairosvg'] under optional-dependencies;
    [project.dependencies] is absent or empty (core install stays dependency-free)."""
    import tomllib

    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with pyproject_path.open("rb") as fh:
        data = tomllib.load(fh)

    project = data["project"]
    assert project.get("dependencies", []) == [], "[project.dependencies] must be absent or empty"
    opt_deps = project.get("optional-dependencies", {})
    assert "card" in opt_deps, "card optional-dependency must be present"
    assert opt_deps["card"] == ["cairosvg"], f"card extra must be ['cairosvg'], got {opt_deps['card']!r}"


# ---------------------------------------------------------------------------
# S. rasterizer parameter signature check (task-031)
# ---------------------------------------------------------------------------


def test_run_rasterizer_param_default_is_svg_to_png():
    """run() has keyword-only rasterizer param whose default is portfolio.card.svg_to_png."""
    import inspect

    from portfolio.card import svg_to_png as card_svg_to_png
    from rating.cli import run as cli_run

    params = inspect.signature(cli_run).parameters
    assert "rasterizer" in params, "run() must have a rasterizer parameter"
    assert params["rasterizer"].default is card_svg_to_png, "rasterizer default must be portfolio.card.svg_to_png"
