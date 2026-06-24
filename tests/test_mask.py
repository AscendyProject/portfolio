"""Tests for portfolio/mask.py and --mask-private integration.

Covers:
- extract_repo_names: structured-field-only discovery
- private_repos: fail-safe, deduplication, default lookup behavior
- mask_portfolio: rewrite / no-mutation / determinism / grounding invariant
- resolve_and_optionally_mask: pre-synthesis ordering + post-synthesis scrub
- All five CLIs: --mask-private flag, stderr summary, no private name in output
- --source-type portfolio: masking on prebuilt JSON
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.mask import (  # noqa: E402
    MaskingError,
    _gh_visibility_lookup,
    assert_maskable,
    extract_repo_names,
    mask_portfolio,
    private_repos,
)
from portfolio.model import Claim, Evidence, Portfolio  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_portfolio(
    ref: str = "acme/svc#5",
    url: str = "",
    detail: str = "",
    context: str = "",
    claim_text: str = "did something",
    claim_refs: list[str] | None = None,
) -> Portfolio:
    ev = Evidence(kind="pr", ref=ref, url=url, detail=detail, context=context)
    cl = Claim(
        text=claim_text,
        evidence_refs=claim_refs if claim_refs is not None else [ref],
        confidence=0.9,
        grounded=True,
    )
    return Portfolio(subject="alice", evidence=[ev], claims=[cl])


def _private_lookup(repo: str) -> bool:
    """Always returns True (private)."""
    return True


def _public_lookup(repo: str) -> bool:
    """Always returns False (public)."""
    return False


# ---------------------------------------------------------------------------
# Discovery — structured sources only
# ---------------------------------------------------------------------------


def test_extract_ref_pr_form():
    """evidence.ref of form owner/repo#<n> yields owner/repo."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="acme/svc#5")],
        claims=[],
    )
    assert extract_repo_names(p) == {"acme/svc"}


def test_extract_ref_file_form():
    """evidence.ref of form owner/repo:<path> yields owner/repo."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="file", ref="acme/svc:src/x.py")],
        claims=[],
    )
    assert extract_repo_names(p) == {"acme/svc"}


def test_extract_url_github():
    """evidence.url with github.com host yields owner/repo (first two path segments)."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="PR#5", url="https://github.com/acme/svc/pull/5")],
        claims=[],
    )
    assert extract_repo_names(p) == {"acme/svc"}


def test_extract_claim_evidence_refs():
    """claim.evidence_refs entry of form owner/repo#<n> yields owner/repo."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="PR#5")],
        claims=[Claim(text="did x", evidence_refs=["acme/svc#5"], confidence=0.9)],
    )
    assert extract_repo_names(p) == {"acme/svc"}


def test_extract_bare_pr_ref_yields_nothing():
    """Bare PR ref like 'PR#5' yields no candidate."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="PR#5")],
        claims=[],
    )
    assert extract_repo_names(p) == set()


def test_extract_bare_file_path_yields_nothing():
    """Bare file path like 'app/auth.py' yields no candidate (no owner/repo prefix)."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="file", ref="app/auth.py")],
        claims=[],
    )
    assert extract_repo_names(p) == set()


def test_extract_url_extra_segments_yields_owner_repo_only():
    """URL with extra path segments yields exactly owner/repo, not any other pair."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="PR#5", url="https://github.com/acme/svc/pull/5")],
        claims=[],
    )
    result = extract_repo_names(p)
    assert result == {"acme/svc"}
    assert "svc/pull" not in result
    assert "github.com/acme" not in result


def test_detail_context_claimtext_not_discovery_sources():
    """detail/context/claim.text are NOT discovery sources — only substitution targets."""
    p = Portfolio(
        subject="alice",
        evidence=[
            Evidence(
                kind="pr",
                ref="PR#5",  # bare ref, no owner/repo
                url="",
                detail="changed in acme/svc#5",
                context="see acme/svc:src/auth.py for details",
            )
        ],
        claims=[
            Claim(
                text="Improved acme/svc performance",
                evidence_refs=["PR#5"],  # bare ref
                confidence=0.9,
            )
        ],
    )
    # detail/context/claim.text should NOT cause discovery
    assert extract_repo_names(p) == set()


# ---------------------------------------------------------------------------
# Discovery — various field combinations
# ---------------------------------------------------------------------------


def test_extract_claim_evidence_refs_file_form():
    """claim.evidence_refs entry of form owner/repo:<path> yields owner/repo."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="file", ref="acme/svc:src/auth.py")],
        claims=[Claim(text="did x", evidence_refs=["acme/svc:src/auth.py"], confidence=0.9)],
    )
    assert extract_repo_names(p) == {"acme/svc"}


def test_extract_non_github_url_yields_nothing():
    """Non-github.com URL yields no candidate."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="PR#5", url="https://gitlab.com/acme/svc/pull/5")],
        claims=[],
    )
    assert extract_repo_names(p) == set()


def test_extract_multiple_repos():
    """Multiple distinct repos across evidence and claims are all discovered."""
    p = Portfolio(
        subject="alice",
        evidence=[
            Evidence(kind="pr", ref="acme/svc#1", url="https://github.com/acme/other/pull/1"),
        ],
        claims=[Claim(text="x", evidence_refs=["acme/third#2"], confidence=0.9)],
    )
    assert extract_repo_names(p) == {"acme/svc", "acme/other", "acme/third"}


# ---------------------------------------------------------------------------
# Visibility lookup — private_repos
# ---------------------------------------------------------------------------


def test_private_repos_calls_lookup_once_per_distinct_repo():
    """Multiple evidence items from the same repo → lookup called exactly once."""
    calls: list[str] = []

    def counting_lookup(repo: str) -> bool:
        calls.append(repo)
        return True

    # Simulate 3 evidence items all referencing acme/svc
    repos = {"acme/svc"}
    result = private_repos(repos, visibility_lookup=counting_lookup)
    assert calls.count("acme/svc") == 1
    assert "acme/svc" in result


def test_private_repos_fail_safe_on_exception():
    """If lookup raises RuntimeError, the repo is treated as private."""

    def boom(repo: str) -> bool:
        raise RuntimeError("network failure")

    result = private_repos({"acme/svc"}, visibility_lookup=boom)
    assert "acme/svc" in result


def test_private_repos_public_excluded():
    """Repos for which lookup returns False are NOT in the returned set."""
    result = private_repos({"acme/pub"}, visibility_lookup=_public_lookup)
    assert "acme/pub" not in result


def test_private_repos_mixed():
    """Only private repos appear in returned set."""

    def mixed(repo: str) -> bool:
        return repo == "acme/private"

    result = private_repos({"acme/private", "acme/public"}, visibility_lookup=mixed)
    assert result == {"acme/private"}


# ---------------------------------------------------------------------------
# Default lookup (_gh_visibility_lookup) — subprocess behavior
# ---------------------------------------------------------------------------


def test_default_lookup_no_shell_true():
    """Default lookup calls subprocess.run with an argv list, not shell=True."""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = json.dumps({"isPrivate": True})

    with patch("portfolio.mask.subprocess.run", return_value=mock_proc) as mock_run:
        result = _gh_visibility_lookup("acme/svc")
        assert result is True
        call_kwargs = mock_run.call_args
        # First positional arg must be a list (argv), not a string
        cmd = call_kwargs[0][0]
        assert isinstance(cmd, list)
        # shell must not be True
        assert call_kwargs[1].get("shell") is not True


def test_default_lookup_raises_on_nonzero_exit():
    """Default lookup raises if subprocess returns non-zero exit code."""
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.stdout = ""
    mock_proc.stderr = "repository not found"

    with patch("portfolio.mask.subprocess.run", return_value=mock_proc):
        with pytest.raises(Exception):
            _gh_visibility_lookup("acme/svc")


def test_default_lookup_raises_on_invalid_json():
    """Default lookup raises if stdout is not valid JSON."""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "not json at all"

    with patch("portfolio.mask.subprocess.run", return_value=mock_proc):
        with pytest.raises(Exception):
            _gh_visibility_lookup("acme/svc")


def test_default_lookup_raises_on_missing_is_private_key():
    """Default lookup raises if JSON doesn't have 'isPrivate' key."""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = json.dumps({})

    with patch("portfolio.mask.subprocess.run", return_value=mock_proc):
        with pytest.raises(Exception):
            _gh_visibility_lookup("acme/svc")


def test_default_lookup_raises_on_non_bool_is_private():
    """Default lookup raises if isPrivate is not a bool (e.g. string "true")."""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = json.dumps({"isPrivate": "true"})

    with patch("portfolio.mask.subprocess.run", return_value=mock_proc):
        with pytest.raises(Exception):
            _gh_visibility_lookup("acme/svc")


def test_default_lookup_returns_false_when_public():
    """Default lookup returns False for a public repo."""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = json.dumps({"isPrivate": False})

    with patch("portfolio.mask.subprocess.run", return_value=mock_proc):
        result = _gh_visibility_lookup("acme/svc")
        assert result is False


# ---------------------------------------------------------------------------
# mask_portfolio — core rewrites
# ---------------------------------------------------------------------------


def test_mask_determinism():
    """Calling mask_portfolio twice with same args produces identical results."""
    p = _make_portfolio()
    priv = {"acme/svc"}
    r1 = mask_portfolio(p, priv)
    r2 = mask_portfolio(p, priv)
    assert r1.evidence[0].ref == r2.evidence[0].ref
    assert r1.claims[0].text == r2.claims[0].text
    assert r1.claims[0].evidence_refs == r2.claims[0].evidence_refs


def test_mask_no_mutation():
    """Input portfolio is unchanged after mask_portfolio returns."""
    p = _make_portfolio(
        ref="acme/svc#5",
        detail="see acme/svc for details",
        context="acme/svc context",
        claim_text="acme/svc did something",
    )
    original = copy.deepcopy(p)
    mask_portfolio(p, {"acme/svc"})
    # evidence unchanged
    assert p.evidence[0].ref == original.evidence[0].ref
    assert p.evidence[0].detail == original.evidence[0].detail
    assert p.evidence[0].context == original.evidence[0].context
    # claims unchanged
    assert p.claims[0].text == original.claims[0].text
    assert p.claims[0].evidence_refs == original.claims[0].evidence_refs


def test_mask_ref_pr_rewrite():
    """evidence.ref of form owner/repo#<n> is rewritten to private-repo-N#<n>."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="acme/svc#5")],
        claims=[Claim(text="x", evidence_refs=["acme/svc#5"], confidence=0.9)],
    )
    masked = mask_portfolio(p, {"acme/svc"})
    assert masked.evidence[0].ref == "private-repo-1#5"


def test_mask_ref_file_rewrite():
    """evidence.ref of form owner/repo:<path> is rewritten with path byte-identical."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="file", ref="acme/svc:src/auth.py")],
        claims=[Claim(text="x", evidence_refs=["acme/svc:src/auth.py"], confidence=0.9)],
    )
    masked = mask_portfolio(p, {"acme/svc"})
    assert masked.evidence[0].ref == "private-repo-1:src/auth.py"
    # path and extension byte-identical
    assert masked.evidence[0].ref.endswith("src/auth.py")


def test_mask_url_scrub():
    """evidence.url containing private owner/repo is scrubbed (no original owner/repo)."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="acme/svc#5", url="https://github.com/acme/svc/pull/5")],
        claims=[Claim(text="x", evidence_refs=["acme/svc#5"], confidence=0.9)],
    )
    masked = mask_portfolio(p, {"acme/svc"})
    assert "acme/svc" not in masked.evidence[0].url


def test_mask_detail_context_scrub():
    """evidence.detail and evidence.context containing private owner/repo are replaced."""
    p = Portfolio(
        subject="alice",
        evidence=[
            Evidence(
                kind="pr",
                ref="acme/svc#5",
                detail="Changed in acme/svc to fix bug",
                context="See acme/svc:src/main.py",
            )
        ],
        claims=[Claim(text="x", evidence_refs=["acme/svc#5"], confidence=0.9)],
    )
    masked = mask_portfolio(p, {"acme/svc"})
    assert "acme/svc" not in masked.evidence[0].detail
    assert "acme/svc" not in masked.evidence[0].context
    assert "private-repo-1" in masked.evidence[0].detail
    assert "private-repo-1" in masked.evidence[0].context


def test_mask_claim_text_scrub():
    """claim.text containing private owner/repo is replaced."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="acme/svc#5")],
        claims=[Claim(text="Improved acme/svc performance", evidence_refs=["acme/svc#5"], confidence=0.9)],
    )
    masked = mask_portfolio(p, {"acme/svc"})
    assert "acme/svc" not in masked.claims[0].text
    assert "private-repo-1" in masked.claims[0].text


def test_mask_claim_evidence_refs_rewrite():
    """claim.evidence_refs entries are rewritten using the same map."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="acme/svc#5")],
        claims=[Claim(text="x", evidence_refs=["acme/svc#5"], confidence=0.9)],
    )
    masked = mask_portfolio(p, {"acme/svc"})
    assert masked.claims[0].evidence_refs == ["private-repo-1#5"]


def test_mask_public_passthrough():
    """Public-repo refs pass through mask_portfolio byte-identical."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="acme/svc#5", url="https://github.com/acme/svc/pull/5")],
        claims=[Claim(text="Improved acme/svc", evidence_refs=["acme/svc#5"], confidence=0.9)],
    )
    # No private repos
    masked = mask_portfolio(p, set())
    assert masked.evidence[0].ref == "acme/svc#5"
    assert masked.evidence[0].url == "https://github.com/acme/svc/pull/5"
    assert masked.claims[0].text == "Improved acme/svc"
    assert masked.claims[0].evidence_refs == ["acme/svc#5"]


def test_mask_sorted_relabel():
    """Labels are assigned in sorted() order of private repo names."""
    p = Portfolio(
        subject="alice",
        evidence=[
            Evidence(kind="pr", ref="z-org/repo#1"),
            Evidence(kind="pr", ref="a-org/repo#2"),
        ],
        claims=[
            Claim(text="x", evidence_refs=["z-org/repo#1"], confidence=0.9),
            Claim(text="y", evidence_refs=["a-org/repo#2"], confidence=0.9),
        ],
    )
    masked = mask_portfolio(p, {"z-org/repo", "a-org/repo"})
    # a-org/repo sorts before z-org/repo
    assert masked.evidence[1].ref == "private-repo-1#2"  # a-org/repo → private-repo-1
    assert masked.evidence[0].ref == "private-repo-2#1"  # z-org/repo → private-repo-2


def test_grounding_invariant():
    """After masking, check_claims yields same grounded count as before."""
    from portfolio.grounding import check_claims

    p = Portfolio(
        subject="alice",
        evidence=[
            Evidence(kind="pr", ref="acme/svc#1"),
            Evidence(kind="pr", ref="acme/svc#2"),
        ],
        claims=[
            Claim(text="claim 1", evidence_refs=["acme/svc#1"], confidence=0.9),
            Claim(text="claim 2", evidence_refs=["acme/svc#2"], confidence=0.9),
        ],
    )
    # Ground the original
    original_grounding = check_claims(list(p.claims), p.evidence)

    # Re-create (claims were mutated by check_claims)
    p2 = Portfolio(
        subject="alice",
        evidence=[
            Evidence(kind="pr", ref="acme/svc#1"),
            Evidence(kind="pr", ref="acme/svc#2"),
        ],
        claims=[
            Claim(text="claim 1", evidence_refs=["acme/svc#1"], confidence=0.9),
            Claim(text="claim 2", evidence_refs=["acme/svc#2"], confidence=0.9),
        ],
    )
    masked = mask_portfolio(p2, {"acme/svc"})
    masked_grounding = check_claims(list(masked.claims), masked.evidence)

    assert len(masked_grounding.grounded) == len(original_grounding.grounded)
    assert len(masked_grounding.rejected) == len(original_grounding.rejected)
    assert len(masked_grounding.needs_confirmation) == len(original_grounding.needs_confirmation)


# ---------------------------------------------------------------------------
# Pipeline — resolve_and_optionally_mask + post-synthesis scrub
# ---------------------------------------------------------------------------


def test_pre_synthesis_ordering_and_post_scrub():
    """Synthesis runs on the masked portfolio; post-scrub removes private name from output."""
    from portfolio.pipeline import resolve_and_optionally_mask
    from portfolio.sources import ResolvedSource

    # Fake extractor: returns evidence with private repo
    def fake_extract():
        return [Evidence(kind="pr", ref="acme/svc#1", url="https://github.com/acme/svc/pull/1")]

    resolved = ResolvedSource(subject="alice", extract=fake_extract)

    # Fake narration runner: returns a claim grounded on the private repo ref
    def fake_runner(prompt: str) -> str:
        return json.dumps([{"text": "Built acme/svc feature", "evidence_refs": ["acme/svc#1"], "confidence": 0.9}])

    # Fake synthesis runner: returns output TEXT literally containing "acme/svc"
    # The synthesis runner here receives masked portfolio, so refs are "private-repo-1#1"
    # But the model EMITS the private name in headline text (untrusted output)
    def fake_synthesis_runner(prompt: str) -> str:
        # The allowed refs in the masked portfolio will be "private-repo-1#1"
        return json.dumps(
            {
                "headline": "acme/svc developer who does great work",
                "headline_refs": ["private-repo-1#1"],
                "highlights": [{"text": "Improved acme/svc codebase", "evidence_refs": ["private-repo-1#1"]}],
            }
        )

    result, n_masked = resolve_and_optionally_mask(
        resolved,
        subject="alice",
        runner=fake_runner,
        mask_private=True,
        synthesis_runner=fake_synthesis_runner,
        visibility_lookup=_private_lookup,
    )

    assert n_masked == 1
    assert result.synthesis is not None
    # headline must not contain private name
    assert "acme/svc" not in (result.synthesis.headline or "")
    # highlights must not contain private name
    for hl in result.synthesis.highlights:
        assert "acme/svc" not in hl.text


def test_resolve_no_mask_unchanged():
    """Without mask_private, resolve_and_optionally_mask returns original portfolio."""
    from portfolio.pipeline import resolve_and_optionally_mask
    from portfolio.sources import ResolvedSource

    def fake_extract():
        return [Evidence(kind="pr", ref="acme/svc#1")]

    resolved = ResolvedSource(subject="alice", extract=fake_extract)

    def fake_runner(prompt: str) -> str:
        return json.dumps([{"text": "Built thing in acme/svc", "evidence_refs": ["acme/svc#1"], "confidence": 0.9}])

    result, n_masked = resolve_and_optionally_mask(
        resolved,
        subject="alice",
        runner=fake_runner,
        mask_private=False,
    )

    assert n_masked == 0
    # No masking: private name appears in output
    assert result.portfolio.claims[0].text == "Built thing in acme/svc"


# ---------------------------------------------------------------------------
# CLI tests — portfolio/cli.py
# ---------------------------------------------------------------------------


def _fake_github_extractor(*, repo: str, author: str, limit: int = 100) -> list[Evidence]:
    return [Evidence(kind="pr", ref="acme/svc#1", url="https://github.com/acme/svc/pull/1", detail="Add feature")]


def _fake_runner_for_private(prompt: str) -> str:
    return json.dumps([{"text": "Built feature in acme/svc", "evidence_refs": ["acme/svc#1"], "confidence": 0.9}])


def test_portfolio_cli_mask_private(capsys):
    """portfolio CLI with --mask-private: no private name in stdout, masked N in stderr."""
    from portfolio.cli import run

    code = run(
        ["--source-type", "github", "--source", "https://github.com/owner/repo", "--author", "alice", "--mask-private"],
        extractor=_fake_github_extractor,
        runner=_fake_runner_for_private,
        visibility_lookup=_private_lookup,
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "acme/svc" not in captured.out
    assert "masked 1 private repo(s)" in captured.err
    # The masked line must contain no '/'
    masked_lines = [ln for ln in captured.err.splitlines() if ln.startswith("masked ")]
    assert len(masked_lines) == 1
    assert "/" not in masked_lines[0]


def test_portfolio_cli_no_mask_private_unchanged(capsys):
    """portfolio CLI without --mask-private: private name appears, no masked line."""
    from portfolio.cli import run

    code = run(
        ["--source-type", "github", "--source", "https://github.com/owner/repo", "--author", "alice"],
        extractor=_fake_github_extractor,
        runner=_fake_runner_for_private,
        visibility_lookup=_private_lookup,
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "acme/svc" in captured.out
    assert "masked" not in captured.err


# ---------------------------------------------------------------------------
# CLI tests — resume/cli.py
# ---------------------------------------------------------------------------


def test_resume_cli_mask_private(tmp_path, capsys):
    """resume CLI with --mask-private: no private name in stdout, masked N in stderr."""
    from resume.cli import run

    jd = tmp_path / "jd.txt"
    jd.write_text("backend engineer python", encoding="utf-8")

    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/owner/repo",
            "--author",
            "alice",
            "--jd",
            str(jd),
            "--mask-private",
        ],
        extractor=_fake_github_extractor,
        runner=_fake_runner_for_private,
        visibility_lookup=_private_lookup,
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "acme/svc" not in captured.out
    assert "masked 1 private repo(s)" in captured.err


def test_resume_cli_no_mask_private_unchanged(tmp_path, capsys):
    """resume CLI without --mask-private: no masked line on stderr, exit 0."""
    from resume.cli import run

    jd = tmp_path / "jd.txt"
    jd.write_text("backend engineer python", encoding="utf-8")

    code = run(
        ["--source-type", "github", "--source", "https://github.com/owner/repo", "--author", "alice", "--jd", str(jd)],
        extractor=_fake_github_extractor,
        runner=_fake_runner_for_private,
        visibility_lookup=_private_lookup,
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "masked" not in captured.err


# ---------------------------------------------------------------------------
# CLI tests — fit/cli.py
# ---------------------------------------------------------------------------


def _fake_grader_runner(prompt: str, temperature: int = 0) -> str:
    """Returns a minimal bounded grade JSON."""
    return json.dumps({"score": 75, "reasoning": [{"text": "Good fit", "evidence_refs": ["acme/svc#1"]}]})


def test_fit_cli_mask_private(tmp_path, capsys):
    """fit CLI with --mask-private: no private name in stdout, masked N in stderr."""
    from fit.cli import run

    jd = tmp_path / "jd.txt"
    jd.write_text("backend engineer python", encoding="utf-8")

    def fit_grader(prompt: str, temperature: int = 0) -> str:
        return json.dumps({"score": 75, "reasoning": [{"text": "Good", "evidence_refs": ["private-repo-1#1"]}]})

    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/owner/repo",
            "--author",
            "alice",
            "--jd",
            str(jd),
            "--mask-private",
        ],
        extractor=_fake_github_extractor,
        runner=_fake_runner_for_private,
        grader_runner=fit_grader,
        visibility_lookup=_private_lookup,
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "acme/svc" not in captured.out
    assert "masked 1 private repo(s)" in captured.err


def test_fit_cli_no_mask_private_unchanged(tmp_path, capsys):
    """fit CLI without --mask-private: private name appears (with --show-refs), no masked line."""
    from fit.cli import run

    jd = tmp_path / "jd.txt"
    jd.write_text("backend engineer python", encoding="utf-8")

    def fit_grader(prompt: str, temperature: int = 0) -> str:
        return json.dumps({"score": 75, "reasoning": [{"text": "Good", "evidence_refs": ["acme/svc#1"]}]})

    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/owner/repo",
            "--author",
            "alice",
            "--jd",
            str(jd),
            "--show-refs",
        ],
        extractor=_fake_github_extractor,
        runner=_fake_runner_for_private,
        grader_runner=fit_grader,
        visibility_lookup=_private_lookup,
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "acme/svc" in captured.out
    assert "masked" not in captured.err


# ---------------------------------------------------------------------------
# CLI tests — rating/cli.py
# ---------------------------------------------------------------------------


def test_rating_cli_mask_private(capsys):
    """rating CLI with --mask-private: no private name in stdout, masked N in stderr."""
    from rating.cli import run

    def rating_grader(prompt: str, temperature: int = 0) -> str:
        return json.dumps({"score": 70, "reasoning": [{"text": "Good work", "evidence_refs": ["private-repo-1#1"]}]})

    code = run(
        ["--source-type", "github", "--source", "https://github.com/owner/repo", "--author", "alice", "--mask-private"],
        extractor=_fake_github_extractor,
        runner=_fake_runner_for_private,
        grader_runner=rating_grader,
        visibility_lookup=_private_lookup,
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "acme/svc" not in captured.out
    assert "masked 1 private repo(s)" in captured.err


def test_rating_cli_no_mask_private_unchanged(capsys):
    """rating CLI without --mask-private: private name appears (with --show-refs), no masked line."""
    from rating.cli import run

    def rating_grader(prompt: str, temperature: int = 0) -> str:
        return json.dumps({"score": 70, "reasoning": [{"text": "Good work", "evidence_refs": ["acme/svc#1"]}]})

    code = run(
        ["--source-type", "github", "--source", "https://github.com/owner/repo", "--author", "alice", "--show-refs"],
        extractor=_fake_github_extractor,
        runner=_fake_runner_for_private,
        grader_runner=rating_grader,
        visibility_lookup=_private_lookup,
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "acme/svc" in captured.out
    assert "masked" not in captured.err


# ---------------------------------------------------------------------------
# CLI tests — reference_check/cli.py
# ---------------------------------------------------------------------------


def _fake_letter_runner(prompt: str) -> str:
    """Fake runner that returns a narration claim OR a letter structure."""
    # If the prompt looks like a narration prompt, return claim JSON
    if "evidence" in prompt.lower() and "claim" in prompt.lower():
        return json.dumps([{"text": "Built feature in acme/svc", "evidence_refs": ["acme/svc#1"], "confidence": 0.9}])
    # Otherwise return letter paragraphs
    return json.dumps([{"text": "This developer improved acme/svc significantly.", "evidence_refs": ["acme/svc#1"]}])


def test_reference_check_cli_mask_private(capsys):
    """reference_check CLI with --mask-private: no private name in stdout, masked N in stderr."""
    from reference_check.cli import run

    def rc_runner(prompt: str) -> str:
        # Narration phase: return claim
        if '"evidence_refs"' not in prompt and "claim" in prompt.lower():
            return json.dumps(
                [{"text": "Built feature in acme/svc", "evidence_refs": ["acme/svc#1"], "confidence": 0.9}]
            )
        # Second call (letter building): return paragraphs with masked ref
        return json.dumps([{"text": "Developer improved performance.", "evidence_refs": ["private-repo-1#1"]}])

    code = run(
        ["--source-type", "github", "--source", "https://github.com/owner/repo", "--author", "alice", "--mask-private"],
        extractor=_fake_github_extractor,
        runner=rc_runner,
        visibility_lookup=_private_lookup,
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "acme/svc" not in captured.out
    assert "masked 1 private repo(s)" in captured.err


def test_reference_check_cli_no_mask_private_unchanged(capsys):
    """reference_check CLI without --mask-private: private name appears, no masked line."""
    from reference_check.cli import run

    call_count = [0]

    def rc_runner(prompt: str) -> str:
        call_count[0] += 1
        if call_count[0] == 1:
            return json.dumps(
                [{"text": "Built feature in acme/svc", "evidence_refs": ["acme/svc#1"], "confidence": 0.9}]
            )
        return json.dumps([{"text": "Developer improved acme/svc.", "evidence_refs": ["acme/svc#1"]}])

    code = run(
        ["--source-type", "github", "--source", "https://github.com/owner/repo", "--author", "alice"],
        extractor=_fake_github_extractor,
        runner=rc_runner,
        visibility_lookup=_private_lookup,
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "masked" not in captured.err


# ---------------------------------------------------------------------------
# --source-type portfolio masking
# ---------------------------------------------------------------------------


def test_portfolio_source_type_masking(tmp_path, capsys):
    """--source-type portfolio with --mask-private: private name masked in output."""
    from portfolio.cli import run
    from portfolio.store import portfolio_to_json

    # Build a portfolio JSON with a private repo ref
    p = Portfolio(
        subject="alice",
        evidence=[
            Evidence(
                kind="pr", ref="acme/svc#1", url="https://github.com/acme/svc/pull/1", detail="Added acme/svc feature"
            )
        ],
        claims=[Claim(text="Built acme/svc feature", evidence_refs=["acme/svc#1"], confidence=0.9, grounded=True)],
    )
    portfolio_file = tmp_path / "portfolio.json"
    portfolio_file.write_text(portfolio_to_json(p), encoding="utf-8")

    code = run(
        ["--source-type", "portfolio", "--source", str(portfolio_file), "--mask-private"],
        visibility_lookup=_private_lookup,
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "acme/svc" not in captured.out
    assert "masked 1 private repo(s)" in captured.err


# ---------------------------------------------------------------------------
# IR-002 / IR-004: overlapping repo names + downstream adversarial scrub
# ---------------------------------------------------------------------------


def test_parse_ref_rejects_pathlike_with_pr_or_file_suffix():
    """`app/auth.py#5` and `app/auth.py:42` must NOT be discovered as the repo
    `app/auth.py` — a file path with a #n or :path suffix is still a path, not a
    canonical repository ref (codex review: ambiguous-form false positives)."""
    from portfolio.mask import _parse_ref

    assert _parse_ref("app/auth.py#5") is None
    assert _parse_ref("app/auth.py:42") is None
    assert _parse_ref("src/main.go#1") is None
    assert _parse_ref("lib/util.ts:src/x") is None
    # genuine repo refs still parse
    assert _parse_ref("acme/svc#5") == "acme/svc"
    assert _parse_ref("acme/svc:src/auth.py") == "acme/svc"


def test_extract_pathlike_pr_ref_yields_no_candidate():
    """A Portfolio whose ref is a path-with-suffix yields no repo candidate."""
    p = Portfolio(
        subject="x",
        evidence=[Evidence(kind="file", ref="app/auth.py:42")],
        claims=[Claim(text="t", evidence_refs=["app/auth.py:42"], confidence=0.9, grounded=True)],
    )
    assert extract_repo_names(p) == set()


def test_mask_overlapping_repo_names_no_partial_corruption():
    """`org/repo` and `org/repo-tools` both private: mask_portfolio rewrites
    longest-first, so `org/repo-tools` is never partially masked to
    `private-repo-N-tools` (IR-002, portfolio substitution)."""
    p = Portfolio(
        subject="x",
        evidence=[Evidence(kind="pr", ref="org/repo#1"), Evidence(kind="pr", ref="org/repo-tools#2")],
        claims=[
            Claim(
                text="shipped org/repo and org/repo-tools",
                evidence_refs=["org/repo#1", "org/repo-tools#2"],
                confidence=0.9,
                grounded=True,
            )
        ],
    )
    masked = mask_portfolio(p, {"org/repo", "org/repo-tools"})
    txt = masked.claims[0].text
    assert "org/repo" not in txt
    assert "-tools" not in txt, "partial-mask corruption (private-repo-N-tools)"
    refs = {e.ref for e in masked.evidence}
    assert all("org/" not in r for r in refs)
    assert len({r.split("#")[0] for r in refs}) == 2  # two distinct labels


def test_post_synthesis_scrub_overlap():
    """A synthesis runner that emits `org/repo-tools` (both repos private) is
    scrubbed longest-first, not corrupted to `private-repo-N-tools` (IR-002,
    post-synthesis scrubbing)."""
    from portfolio.pipeline import resolve_and_optionally_mask
    from portfolio.sources import ResolvedSource

    def fake_extract():
        return [Evidence(kind="pr", ref="org/repo#1"), Evidence(kind="pr", ref="org/repo-tools#2")]

    resolved = ResolvedSource(subject="x", extract=fake_extract)

    def fake_runner(prompt: str) -> str:
        return json.dumps(
            [
                {
                    "text": "Built org/repo and org/repo-tools",
                    "evidence_refs": ["org/repo#1", "org/repo-tools#2"],
                    "confidence": 0.9,
                }
            ]
        )

    def fake_synthesis_runner(prompt: str) -> str:
        return json.dumps(
            {"headline": "worked on org/repo-tools heavily", "headline_refs": ["private-repo-1#1"], "highlights": []}
        )

    result, n_masked = resolve_and_optionally_mask(
        resolved,
        subject="x",
        runner=fake_runner,
        mask_private=True,
        synthesis_runner=fake_synthesis_runner,
        visibility_lookup=_private_lookup,
    )
    assert n_masked == 2
    hl = result.synthesis.headline or ""
    assert "org/repo" not in hl
    assert "-tools" not in hl, "partial-mask corruption in post-synthesis scrub"


def test_reference_check_downstream_letter_scrub_adversarial(tmp_path, capsys):
    """reference_check --mask-private: the letter runner leaks the private repo
    name in PROSE while citing a valid masked ref; the post-model scrub removes
    it from the rendered letter (IR-004 downstream adversarial)."""
    from reference_check.cli import run
    from portfolio.store import portfolio_to_json

    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="acme/svc#1", url="https://github.com/acme/svc/pull/1", detail="x")],
        claims=[Claim(text="Built a feature", evidence_refs=["acme/svc#1"], confidence=0.9, grounded=True)],
    )
    pf = tmp_path / "p.json"
    pf.write_text(portfolio_to_json(p), encoding="utf-8")

    def leaky_letter_runner(prompt: str) -> str:
        # Cites the valid masked ref but leaks the real private name in prose.
        return json.dumps([{"text": "alice shipped acme/svc end to end", "evidence_refs": ["private-repo-1#1"]}])

    code = run(
        ["--source-type", "portfolio", "--source", str(pf), "--mask-private"],
        runner=leaky_letter_runner,
        visibility_lookup=_private_lookup,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "acme/svc" not in out, "private name leaked through the letter prose (scrub missing)"


# ---------------------------------------------------------------------------
# --show-refs --mask-private composition tests (one per CLI)
# ---------------------------------------------------------------------------


def test_portfolio_cli_show_refs_and_mask_private(capsys):
    """portfolio CLI: --show-refs --mask-private shows refs in masked form; no raw private name."""
    from portfolio.cli import run

    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/owner/repo",
            "--author",
            "alice",
            "--show-refs",
            "--mask-private",
        ],
        extractor=_fake_github_extractor,
        runner=_fake_runner_for_private,
        visibility_lookup=_private_lookup,
    )
    captured = capsys.readouterr()
    assert code == 0
    # Masked form must appear (ref displayed)
    assert "private-repo-1" in captured.out
    # Raw private name must NOT appear
    assert "acme/svc" not in captured.out


def test_resume_cli_show_refs_and_mask_private(tmp_path, capsys):
    """resume CLI: --show-refs --mask-private shows refs in masked form; no raw private name."""
    from resume.cli import run

    jd = tmp_path / "jd.txt"
    jd.write_text("backend engineer python", encoding="utf-8")

    def backend_runner_for_private(prompt: str) -> str:
        # Claim text matches JD keywords (backend, python) and cites the private ref
        return json.dumps(
            [{"text": "Built backend python service", "evidence_refs": ["acme/svc#1"], "confidence": 0.9}]
        )

    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/owner/repo",
            "--author",
            "alice",
            "--jd",
            str(jd),
            "--show-refs",
            "--mask-private",
        ],
        extractor=_fake_github_extractor,
        runner=backend_runner_for_private,
        visibility_lookup=_private_lookup,
    )
    captured = capsys.readouterr()
    assert code == 0
    # Masked ref must appear in output (inline refs via --show-refs)
    assert "private-repo-1" in captured.out
    # Raw private name must NOT appear
    assert "acme/svc" not in captured.out


def test_fit_cli_show_refs_and_mask_private(tmp_path, capsys):
    """fit CLI: --show-refs --mask-private shows refs in masked form; no raw private name."""
    from fit.cli import run

    jd = tmp_path / "jd.txt"
    jd.write_text("backend engineer python", encoding="utf-8")

    def fit_grader(prompt: str, temperature: int = 0) -> str:
        return json.dumps({"score": 75, "reasoning": [{"text": "Good work", "evidence_refs": ["private-repo-1#1"]}]})

    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/owner/repo",
            "--author",
            "alice",
            "--jd",
            str(jd),
            "--show-refs",
            "--mask-private",
        ],
        extractor=_fake_github_extractor,
        runner=_fake_runner_for_private,
        grader_runner=fit_grader,
        visibility_lookup=_private_lookup,
    )
    captured = capsys.readouterr()
    assert code == 0
    # Masked ref must appear in output (reasoning _(refs: private-repo-1#1)_)
    assert "private-repo-1" in captured.out
    # Raw private name must NOT appear
    assert "acme/svc" not in captured.out


def test_rating_cli_show_refs_and_mask_private(capsys):
    """rating CLI: --show-refs --mask-private shows refs in masked form; no raw private name."""
    from rating.cli import run

    def rating_grader(prompt: str, temperature: int = 0) -> str:
        return json.dumps({"score": 70, "reasoning": [{"text": "Good work", "evidence_refs": ["private-repo-1#1"]}]})

    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/owner/repo",
            "--author",
            "alice",
            "--show-refs",
            "--mask-private",
        ],
        extractor=_fake_github_extractor,
        runner=_fake_runner_for_private,
        grader_runner=rating_grader,
        visibility_lookup=_private_lookup,
    )
    captured = capsys.readouterr()
    assert code == 0
    # Masked ref must appear in output (Evidence refs: private-repo-1#1)
    assert "private-repo-1" in captured.out
    # Raw private name must NOT appear
    assert "acme/svc" not in captured.out


def test_reference_check_cli_show_refs_and_mask_private(capsys):
    """reference_check CLI: --show-refs --mask-private shows refs in masked form; no raw private name."""
    from reference_check.cli import run

    call_count = [0]

    def rc_runner(prompt: str) -> str:
        call_count[0] += 1
        if call_count[0] == 1:
            # Narration phase: return claim citing the private ref (will be masked)
            return json.dumps(
                [{"text": "Built feature in acme/svc", "evidence_refs": ["acme/svc#1"], "confidence": 0.9}]
            )
        # Letter phase: cite the already-masked ref
        return json.dumps([{"text": "Developer improved performance.", "evidence_refs": ["private-repo-1#1"]}])

    code = run(
        [
            "--source-type",
            "github",
            "--source",
            "https://github.com/owner/repo",
            "--author",
            "alice",
            "--show-refs",
            "--mask-private",
        ],
        extractor=_fake_github_extractor,
        runner=rc_runner,
        visibility_lookup=_private_lookup,
    )
    captured = capsys.readouterr()
    assert code == 0
    # Masked ref must appear (rendered via *[private-repo-1#1]*)
    assert "private-repo-1" in captured.out
    # Raw private name must NOT appear
    assert "acme/svc" not in captured.out


# ---------------------------------------------------------------------------
# Fail closed: --mask-private refuses non-github.com (GHES) hosts it can't mask
# (codex review IR-001)
# ---------------------------------------------------------------------------


def test_assert_maskable_raises_for_ghes_host():
    """A GitHub Enterprise Server evidence URL makes masking refuse (fail closed)."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="PR#1", url="https://ghe.example.com/owner/repo/pull/1")],
        claims=[],
    )
    with pytest.raises(MaskingError, match="ghe.example.com"):
        assert_maskable(p)


def test_www_github_url_is_discovered_and_masked():
    """www.github.com is in the maskable set, so discovery must also handle it —
    a bare-ref portfolio with a www.github.com URL is discovered and masked, not
    silently leaked (codex IR-002: guard and discovery must agree on hosts)."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="PR#1", url="https://www.github.com/acme/secret/pull/1")],
        claims=[],
    )
    assert extract_repo_names(p) == {"acme/secret"}  # discovered despite the www. prefix
    masked = mask_portfolio(p, private={"acme/secret"})
    assert "acme/secret" not in masked.evidence[0].url


def test_assert_maskable_allows_web_article_evidence():
    """`--source-type web` article evidence has an arbitrary public content URL,
    not a repo to mask — a non-github.com article host must NOT trip the guard
    (regression: the GHES fail-closed check broke web + --mask-private)."""
    p = Portfolio(
        subject="alice",
        evidence=[
            Evidence(
                kind="article",
                ref="https://blog.example.com/post",
                url="https://blog.example.com/post",
                detail="My Post",
            )
        ],
        claims=[],
    )
    assert_maskable(p)  # must not raise — nothing to mask in a public article


def test_assert_maskable_allows_github_com_and_bare_refs():
    """github.com URLs, empty URLs, and bare refs do not trip the guard."""
    p = Portfolio(
        subject="alice",
        evidence=[
            Evidence(kind="pr", ref="acme/svc#1", url="https://github.com/acme/svc/pull/1"),
            Evidence(kind="pr", ref="PR#2", url=""),  # no URL → nothing to mask
            Evidence(kind="file", ref="acme/svc:app/main.py"),
        ],
        claims=[],
    )
    assert_maskable(p)  # must not raise


def test_rating_cli_mask_private_fails_closed_on_ghes(tmp_path, capsys):
    """End-to-end: --mask-private over a portfolio with a GHES URL exits non-zero
    with a clear error, and never emits the GHES repo unmasked."""
    from portfolio.store import portfolio_to_json
    from rating.cli import run

    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="PR#1", url="https://ghe.example.com/acme/secret/pull/1", detail="work")],
        claims=[Claim(text="did work", evidence_refs=["PR#1"], confidence=0.9, grounded=True)],
    )
    portfolio_file = tmp_path / "p.json"
    portfolio_file.write_text(portfolio_to_json(p), encoding="utf-8")

    code = run(
        ["--source-type", "portfolio", "--source", str(portfolio_file), "--mask-private"],
        visibility_lookup=lambda repo: True,
    )
    captured = capsys.readouterr()
    assert code != 0  # refused, not a silent "masked 0"
    assert "ghe.example.com" in captured.err  # clear reason on stderr
    assert "acme/secret" not in captured.out  # never emitted unmasked


# ---------------------------------------------------------------------------
# IR-001: assert_maskable runs BEFORE any model call (counting runner proof)
# ---------------------------------------------------------------------------


def test_mask_private_runner_not_called_when_assert_maskable_raises():
    """When assert_maskable raises on the mask_private=True path, neither runner
    nor synthesis_runner is ever called — proven by counting fakes.
    Call-count must be 0 for both (IR-001 ordering guarantee)."""
    from portfolio.pipeline import resolve_and_optionally_mask
    from portfolio.sources import ResolvedSource

    runner_calls = [0]
    synthesis_runner_calls = [0]

    def counting_runner(prompt: str) -> str:
        runner_calls[0] += 1
        return "[]"

    def counting_synthesis_runner(prompt: str) -> str:
        synthesis_runner_calls[0] += 1
        return "{}"

    def fake_extract():
        # Evidence with a GHES URL — assert_maskable must refuse this
        return [Evidence(kind="pr", ref="PR#1", url="https://ghe.example.com/owner/repo/pull/1")]

    resolved = ResolvedSource(subject="alice", extract=fake_extract)

    with pytest.raises(MaskingError):
        resolve_and_optionally_mask(
            resolved,
            subject="alice",
            runner=counting_runner,
            mask_private=True,
            synthesis_runner=counting_synthesis_runner,
        )

    assert runner_calls[0] == 0, "runner was called before the masking guard raised (IR-001)"
    assert synthesis_runner_calls[0] == 0, "synthesis_runner was called before the masking guard raised (IR-001)"


# ---------------------------------------------------------------------------
# IR-003: assert_maskable checks ref-encoded host (url-less GHES refs)
# ---------------------------------------------------------------------------


def test_assert_maskable_raises_for_ghes_ref_without_url():
    """A GHES-style ref (host/owner/repo#n) with empty url still trips the
    masking guard (IR-003: url-less GHES ref bypass is closed)."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="ghe.example.com/owner/repo#1", url="")],
        claims=[],
    )
    with pytest.raises(MaskingError, match="ghe.example.com"):
        assert_maskable(p)


def test_assert_maskable_allows_bare_owner_repo_ref_without_url():
    """A bare owner/repo#n ref with empty url is github.com-origin and must NOT
    trip the guard (two-segment prefix → no host label)."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="owner/repo#1", url="")],
        claims=[],
    )
    assert_maskable(p)  # must not raise


def test_assert_maskable_allows_article_with_non_github_ref():
    """article evidence whose ref is a non-github.com URL must NOT trip the guard
    (web-article exemption is preserved even for the new ref-host check)."""
    p = Portfolio(
        subject="alice",
        evidence=[
            Evidence(
                kind="article",
                ref="blog.example.com/owner/repo#post",
                url="https://blog.example.com/owner/repo/post",
                detail="Some post",
            )
        ],
        claims=[],
    )
    assert_maskable(p)  # must not raise — article is public content, not a repo
