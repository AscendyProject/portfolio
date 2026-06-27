"""Tests for GHES (GitHub Enterprise Server) masking support in portfolio/mask.py.

Covers host-qualified identity discovery, visibility-lookup argv, case
normalization, relabeling, mixed-host portfolios, fail-closed behaviour when the
visibility lookup raises, the relaxed assert_maskable contract (task-028 IR-004),
and the task-026 ordering invariant with GHES evidence.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.mask import (  # noqa: E402
    MaskingError,
    _gh_visibility_lookup,
    _rewrite_text,
    assert_maskable,
    extract_repo_names,
    mask_portfolio,
    private_repos,
)
from portfolio.model import Claim, Evidence, Portfolio  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GHES_HOST = "ghe.example.com"


def _ghes_portfolio(
    *,
    ref: str = f"{GHES_HOST}/acme/svc#5",
    url: str = f"https://{GHES_HOST}/acme/svc/pull/5",
    detail: str = "",
    context: str = "",
    claim_text: str = "did something",
) -> Portfolio:
    ev = Evidence(kind="pr", ref=ref, url=url, detail=detail, context=context)
    cl = Claim(
        text=claim_text,
        evidence_refs=[ref],
        confidence=0.9,
        grounded=True,
    )
    return Portfolio(subject="alice", evidence=[ev], claims=[cl])


def _always_private(repo: str) -> bool:
    return True


def _always_public(repo: str) -> bool:
    return False


# ---------------------------------------------------------------------------
# Part A — extract_repo_names: GHES discovery
# ---------------------------------------------------------------------------


def test_extract_ghes_ref_pr_form():
    """evidence.ref of form host/owner/repo#<n> yields 'host/owner/repo' key."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref=f"{GHES_HOST}/acme/svc#5")],
        claims=[],
    )
    assert extract_repo_names(p) == {f"{GHES_HOST}/acme/svc"}


def test_extract_ghes_ref_file_form():
    """evidence.ref of form host/owner/repo:<path> yields 'host/owner/repo' key."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="file", ref=f"{GHES_HOST}/acme/svc:src/auth.py")],
        claims=[],
    )
    assert extract_repo_names(p) == {f"{GHES_HOST}/acme/svc"}


def test_extract_ghes_url():
    """evidence.url with a non-github.com host yields 'host/owner/repo' key."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="PR#5", url=f"https://{GHES_HOST}/acme/svc/pull/5")],
        claims=[],
    )
    assert extract_repo_names(p) == {f"{GHES_HOST}/acme/svc"}


def test_extract_ghes_url_extra_segments():
    """GHES URL with extra path segments yields only host/owner/repo, not deeper pair."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="PR#1", url=f"https://{GHES_HOST}/acme/svc/pull/1")],
        claims=[],
    )
    result = extract_repo_names(p)
    assert result == {f"{GHES_HOST}/acme/svc"}
    assert f"{GHES_HOST}/svc/pull" not in result


def test_extract_ghes_claim_evidence_refs():
    """claim.evidence_refs entry of form host/owner/repo#<n> yields host-qualified key."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="PR#5")],
        claims=[Claim(text="x", evidence_refs=[f"{GHES_HOST}/acme/svc#5"], confidence=0.9)],
    )
    assert extract_repo_names(p) == {f"{GHES_HOST}/acme/svc"}


# ---------------------------------------------------------------------------
# Part A — case normalization
# ---------------------------------------------------------------------------


def test_extract_case_normalization_github():
    """github.com owner/repo keys are lowercased: ACME/SVC and acme/svc map to one key."""
    p = Portfolio(
        subject="alice",
        evidence=[
            Evidence(kind="pr", ref="ACME/SVC#1"),
            Evidence(kind="pr", ref="acme/svc#2"),
        ],
        claims=[],
    )
    result = extract_repo_names(p)
    assert result == {"acme/svc"}


def test_extract_case_normalization_ghes():
    """GHES host/owner/repo keys are lowercased: mixed-case ref collapses to one key."""
    p = Portfolio(
        subject="alice",
        evidence=[
            Evidence(kind="pr", ref=f"{GHES_HOST}/Acme/Svc#1"),
            Evidence(kind="pr", ref=f"{GHES_HOST}/acme/svc#2"),
        ],
        claims=[],
    )
    result = extract_repo_names(p)
    assert result == {f"{GHES_HOST}/acme/svc"}


def test_extract_case_normalization_ghes_url():
    """GHES URL host/owner/repo is lowercased: duplicate mixed-case URLs collapse."""
    p = Portfolio(
        subject="alice",
        evidence=[
            Evidence(kind="pr", ref="PR#1", url=f"https://{GHES_HOST}/Acme/Svc/pull/1"),
            Evidence(kind="pr", ref="PR#2", url=f"https://{GHES_HOST}/acme/svc/pull/2"),
        ],
        claims=[],
    )
    result = extract_repo_names(p)
    assert result == {f"{GHES_HOST}/acme/svc"}


# ---------------------------------------------------------------------------
# Part B — _gh_visibility_lookup: argv shape and integration
#
# These tests go through the full extract_repo_names → private_repos chain so
# they exercise NEW behaviour (old extract_repo_names returned an empty set for
# GHES portfolios, so private_repos never received a GHES key).
# ---------------------------------------------------------------------------


def test_ghes_key_passed_to_visibility_lookup_from_extract():
    """When extract_repo_names returns a GHES key, private_repos passes the full
    host/owner/repo string to the visibility lookup — not a bare owner/repo.
    This tests the integration of extraction → lookup that did NOT exist pre-task-028."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref=f"{GHES_HOST}/acme/svc#5")],
        claims=[],
    )
    called_with: list[str] = []

    def tracking_lookup(repo: str) -> bool:
        called_with.append(repo)
        return True

    repos = extract_repo_names(p)
    private_repos(repos, visibility_lookup=tracking_lookup)
    # Lookup must receive the full GHES key — not a bare owner/repo
    assert called_with == [f"{GHES_HOST}/acme/svc"]


def test_github_key_stays_bare_through_extract_chain():
    """github.com keys extracted from a portfolio are bare 'owner/repo' (not host-prefixed)
    when passed to the visibility lookup — existing behaviour preserved."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="acme/svc#5")],
        claims=[],
    )
    called_with: list[str] = []

    def tracking_lookup(repo: str) -> bool:
        called_with.append(repo)
        return False

    repos = extract_repo_names(p)
    private_repos(repos, visibility_lookup=tracking_lookup)
    assert called_with == ["acme/svc"]
    assert not any("/" in k and k.count("/") > 1 for k in called_with), "github.com key must not be host-prefixed"


def test_gh_visibility_lookup_ghes_subprocess_argv():
    """_gh_visibility_lookup with a GHES key calls subprocess with the full
    host/owner/repo string (not shell=True, not split)."""
    ghes_key = f"{GHES_HOST}/acme/svc"
    mock_proc = type("P", (), {"returncode": 0, "stdout": json.dumps({"isPrivate": True}), "stderr": ""})()
    with patch("portfolio.mask.subprocess.run", return_value=mock_proc) as mock_run:
        result = _gh_visibility_lookup(ghes_key)
        assert result is True
        cmd = mock_run.call_args[0][0]
        assert isinstance(cmd, list), "gh invocation must be an argv list, not shell=True"
        assert ghes_key in cmd, f"GHES key {ghes_key!r} must appear verbatim in argv"
        assert mock_run.call_args[1].get("shell") is not True


def test_fail_safe_through_extract_chain_on_exception():
    """End-to-end: GHES key discovered by extract_repo_names + raising lookup →
    treated as private (fail-safe). Fails against old code because old
    extract_repo_names returned an empty set for GHES portfolios."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref=f"{GHES_HOST}/acme/svc#5")],
        claims=[],
    )

    def boom(repo: str) -> bool:
        raise RuntimeError("GHES unreachable")

    repos = extract_repo_names(p)  # NEW: returns {"ghe.example.com/acme/svc"}
    result = private_repos(repos, visibility_lookup=boom)
    # Fails against old code: old extract returned {} → private_repos returned {} → assertion fails
    assert f"{GHES_HOST}/acme/svc" in result


def test_fail_safe_through_extract_chain_on_nonzero():
    """End-to-end: GHES key discovered by extract_repo_names + non-zero gh exit →
    treated as private (fail-safe). Fails against old code (empty extract result)."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref=f"{GHES_HOST}/acme/svc#5")],
        claims=[],
    )
    mock_proc = type("P", (), {"returncode": 1, "stdout": "", "stderr": "not found"})()
    with patch("portfolio.mask.subprocess.run", return_value=mock_proc):
        repos = extract_repo_names(p)  # NEW: returns {"ghe.example.com/acme/svc"}
        result = private_repos(repos, visibility_lookup=_gh_visibility_lookup)
    # Fails against old code: old extract returned {} → empty result
    assert f"{GHES_HOST}/acme/svc" in result


# ---------------------------------------------------------------------------
# Part C — mask_portfolio: GHES relabeling
# ---------------------------------------------------------------------------


def test_mask_ghes_ref_pr_rewrite():
    """A GHES PR ref host/owner/repo#<n> is rewritten to private-repo-N#<n>."""
    ghes_key = f"{GHES_HOST}/acme/svc"
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref=f"{ghes_key}#5")],
        claims=[Claim(text="x", evidence_refs=[f"{ghes_key}#5"], confidence=0.9)],
    )
    masked = mask_portfolio(p, {ghes_key})
    assert masked.evidence[0].ref == "private-repo-1#5"
    assert masked.claims[0].evidence_refs == ["private-repo-1#5"]


def test_mask_ghes_ref_file_rewrite():
    """A GHES file ref host/owner/repo:<path> is rewritten, path bytes preserved."""
    ghes_key = f"{GHES_HOST}/acme/svc"
    ref = f"{ghes_key}:src/auth.py"
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="file", ref=ref)],
        claims=[Claim(text="x", evidence_refs=[ref], confidence=0.9)],
    )
    masked = mask_portfolio(p, {ghes_key})
    assert masked.evidence[0].ref == "private-repo-1:src/auth.py"


def test_mask_ghes_url_scrub():
    """GHES URL containing host/owner/repo is scrubbed (no original hostname/repo)."""
    ghes_key = f"{GHES_HOST}/acme/svc"
    url = f"https://{GHES_HOST}/acme/svc/pull/5"
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref=f"{ghes_key}#5", url=url)],
        claims=[Claim(text="x", evidence_refs=[f"{ghes_key}#5"], confidence=0.9)],
    )
    masked = mask_portfolio(p, {ghes_key})
    assert "acme/svc" not in masked.evidence[0].url
    assert GHES_HOST not in masked.evidence[0].url


def test_mask_ghes_detail_context_scrub():
    """detail and context containing GHES identity are replaced."""
    ghes_key = f"{GHES_HOST}/acme/svc"
    p = Portfolio(
        subject="alice",
        evidence=[
            Evidence(
                kind="pr",
                ref=f"{ghes_key}#5",
                detail=f"Changed in {GHES_HOST}/acme/svc to fix bug",
                context=f"See {GHES_HOST}/acme/svc:src/main.py",
            )
        ],
        claims=[Claim(text="x", evidence_refs=[f"{ghes_key}#5"], confidence=0.9)],
    )
    masked = mask_portfolio(p, {ghes_key})
    assert "acme/svc" not in masked.evidence[0].detail
    assert GHES_HOST not in masked.evidence[0].detail
    assert "private-repo-1" in masked.evidence[0].detail
    assert "acme/svc" not in masked.evidence[0].context
    assert "private-repo-1" in masked.evidence[0].context


def test_mask_ghes_claim_text_scrub():
    """claim.text containing GHES identity is replaced."""
    ghes_key = f"{GHES_HOST}/acme/svc"
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref=f"{ghes_key}#5")],
        claims=[
            Claim(
                text=f"Improved {GHES_HOST}/acme/svc performance",
                evidence_refs=[f"{ghes_key}#5"],
                confidence=0.9,
            )
        ],
    )
    masked = mask_portfolio(p, {ghes_key})
    assert "acme/svc" not in masked.claims[0].text
    assert GHES_HOST not in masked.claims[0].text
    assert "private-repo-1" in masked.claims[0].text


def test_mask_ghes_bare_owner_repo_in_text_also_scrubbed():
    """Free text containing only the bare owner/repo (without host prefix) is also
    scrubbed for GHES private repos — the relabel map includes a bare alias."""
    ghes_key = f"{GHES_HOST}/acme/svc"
    # Text only has bare owner/repo, not the full host prefix
    text = "Work done on acme/svc feature"
    result = _rewrite_text(text, {ghes_key: "private-repo-1", "acme/svc": "private-repo-1"})
    assert "acme/svc" not in result
    assert "private-repo-1" in result


def test_mask_ghes_case_insensitive_rewrite():
    """Rewriting is case-insensitive: mixed-case occurrence in text is replaced."""
    ghes_key = f"{GHES_HOST}/acme/svc"
    text = f"Work in {GHES_HOST.upper()}/ACME/SVC was shipped"
    result = _rewrite_text(text, {ghes_key: "private-repo-1"})
    assert "acme/svc" not in result.lower()
    assert "private-repo-1" in result


# ---------------------------------------------------------------------------
# Mixed github.com + GHES portfolio
# ---------------------------------------------------------------------------


def test_mask_mixed_github_ghes_deterministic_labels():
    """Mixed github.com + GHES portfolio gets stable, collision-free labels."""
    gh_key = "acme/svc"
    ghes_key = f"{GHES_HOST}/acme/api"

    p = Portfolio(
        subject="alice",
        evidence=[
            Evidence(kind="pr", ref=f"{gh_key}#1"),
            Evidence(kind="pr", ref=f"{ghes_key}#2"),
        ],
        claims=[
            Claim(text=f"Work in {gh_key} and {GHES_HOST}/acme/api", evidence_refs=[f"{gh_key}#1"], confidence=0.9),
        ],
    )
    masked = mask_portfolio(p, {gh_key, ghes_key})

    # Both refs must be relabeled
    refs = {ev.ref for ev in masked.evidence}
    assert all("acme/" not in r for r in refs)
    assert all(r.startswith("private-repo-") for r in refs)

    # Two distinct labels
    labels = {r.split("#")[0] for r in refs}
    assert len(labels) == 2

    # Claim text must not contain either private name
    assert "acme/svc" not in masked.claims[0].text
    assert GHES_HOST not in masked.claims[0].text


def test_mask_mixed_no_cross_host_collision():
    """org/repo (github.com) and host/org/repo-tools (GHES) both private:
    longest-first replacement prevents partial corruption of the longer key."""
    gh_key = "acme/svc"
    ghes_key = f"{GHES_HOST}/acme/svc-tools"

    p = Portfolio(
        subject="alice",
        evidence=[
            Evidence(kind="pr", ref=f"{gh_key}#1"),
            Evidence(kind="pr", ref=f"{ghes_key}#2"),
        ],
        claims=[
            Claim(
                text=f"shipped {gh_key} and {GHES_HOST}/acme/svc-tools",
                evidence_refs=[f"{gh_key}#1", f"{ghes_key}#2"],
                confidence=0.9,
            )
        ],
    )
    masked = mask_portfolio(p, {gh_key, ghes_key})
    txt = masked.claims[0].text

    # Neither original name should appear
    assert "acme/svc" not in txt
    assert GHES_HOST not in txt
    # No partial-corrupt suffix like "private-repo-N-tools"
    assert "-tools" not in txt, f"partial-mask corruption: {txt!r}"
    # Two distinct masked labels in refs
    labels = {r.split("#")[0] for r in masked.claims[0].evidence_refs}
    assert len(labels) == 2


# ---------------------------------------------------------------------------
# Fail-closed: GHES identity completely absent from masked output
# ---------------------------------------------------------------------------


def test_mask_ghes_fail_closed_no_identity_in_output():
    """When GHES visibility lookup raises, private_repos treats it as private.
    mask_portfolio then removes ALL occurrences of the identity from output."""
    ghes_key = f"{GHES_HOST}/acme/svc"

    def raising_lookup(repo: str) -> bool:
        raise RuntimeError("GHES unreachable")

    p = Portfolio(
        subject="alice",
        evidence=[
            Evidence(
                kind="pr",
                ref=f"{ghes_key}#5",
                url=f"https://{GHES_HOST}/acme/svc/pull/5",
                detail=f"Changed {GHES_HOST}/acme/svc",
                context=f"Context {GHES_HOST}/acme/svc:src/x.py",
            )
        ],
        claims=[
            Claim(
                text=f"Built {GHES_HOST}/acme/svc feature",
                evidence_refs=[f"{ghes_key}#5"],
                confidence=0.9,
            )
        ],
    )

    # Fail-safe: raising lookup → treated as private
    private = private_repos(extract_repo_names(p), visibility_lookup=raising_lookup)
    assert ghes_key in private

    masked = mask_portfolio(p, private)

    # Every field must be free of the identity (both host and owner/repo)
    for ev in masked.evidence:
        for field in (ev.ref, ev.url, ev.detail, ev.context):
            assert "acme/svc" not in field.lower(), f"identity leaked in {field!r}"
            assert GHES_HOST not in field.lower(), f"host leaked in {field!r}"
    for claim in masked.claims:
        assert "acme/svc" not in claim.text.lower(), f"identity leaked in claim: {claim.text!r}"
        assert GHES_HOST not in claim.text.lower(), f"host leaked in claim: {claim.text!r}"
        for ref in claim.evidence_refs:
            assert "acme/svc" not in ref.lower(), f"identity leaked in ref: {ref!r}"
            assert GHES_HOST not in ref.lower(), f"host leaked in ref: {ref!r}"


# ---------------------------------------------------------------------------
# assert_maskable: relaxed contract (task-028 IR-004)
# Well-formed GHES identities must be ACCEPTED; malformed must be REFUSED.
# These tests exercise new behavior that fails against old mask.py.
# ---------------------------------------------------------------------------


def test_assert_maskable_accepts_well_formed_ghes_url():
    """assert_maskable accepts a well-formed GHES URL (task-028: no longer refuses
    non-github.com hosts with valid owner/repo in path)."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="PR#1", url=f"https://{GHES_HOST}/owner/repo/pull/1")],
        claims=[],
    )
    assert_maskable(p)  # must not raise — old code raised MaskingError here


def test_assert_maskable_accepts_well_formed_ghes_ref():
    """assert_maskable accepts a well-formed GHES ref (host/owner/repo#n) with empty url
    (task-028: host-qualified refs are now maskable)."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref=f"{GHES_HOST}/owner/repo#1", url="")],
        claims=[],
    )
    assert_maskable(p)  # must not raise — old code raised MaskingError here


def test_assert_maskable_accepts_ghes_even_when_visibility_raises():
    """Visibility-lookup failure for a well-formed GHES identity is NOT a refusal —
    that is private_repos' job. assert_maskable must pass so the pipeline proceeds
    to masking (fail-safe: treat as private, relabel)."""
    p = _ghes_portfolio()
    # assert_maskable must not inspect whether the host is reachable
    assert_maskable(p)  # must not raise — old code raised MaskingError here


def test_assert_maskable_refuses_malformed_url_no_owner_repo():
    """assert_maskable REFUSES a URL whose path has no recognizable owner/repo
    (single-segment path → cannot decompose into host/owner/repo → refuse)."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="PR#1", url="https://example.com/just-a-page")],
        claims=[],
    )
    with pytest.raises(MaskingError):
        assert_maskable(p)


def test_assert_maskable_refuses_malformed_url_empty_path():
    """assert_maskable REFUSES a URL with no path segments (no owner/repo possible)."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="PR#1", url="https://example.com/")],
        claims=[],
    )
    with pytest.raises(MaskingError):
        assert_maskable(p)


def test_assert_maskable_refuses_malformed_ghes_ref_pathlike_extension():
    """assert_maskable REFUSES a host-prefixed ref whose repo segment looks like a
    file path (path-like extension on the repo segment — not a valid repo name)."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref=f"{GHES_HOST}/owner/repo.py#1", url="")],
        claims=[],
    )
    with pytest.raises(MaskingError):
        assert_maskable(p)


# ---------------------------------------------------------------------------
# Task-026 ordering invariant: assert_maskable runs before any model call,
# masking completes before synthesis. Verified with a runner spy.
# ---------------------------------------------------------------------------


def test_task026_ordering_ghes_pipeline(monkeypatch):
    """IR-001 invariant for a GHES private portfolio: assert_maskable passes (GHES is
    maskable, not refused), and the evidence is MASKED BEFORE the narrate runner is
    called — so the raw GHES host/owner/repo never appears in the model prompt. The
    final portfolio is also free of the raw GHES identity. Verified via fake runner."""

    from portfolio.pipeline import resolve_and_optionally_mask
    from portfolio.sources import ResolvedSource

    ghes_key = f"{GHES_HOST}/acme/svc"
    runner_calls: list[str] = []

    def fake_runner(prompt: str) -> str:
        runner_calls.append(prompt)
        # The runner receives ALREADY-MASKED evidence: the raw GHES identity must not
        # be anywhere in its prompt. It cites the masked ref the prompt actually shows.
        assert GHES_HOST not in prompt, f"raw GHES host leaked into the narrate prompt: {prompt!r}"
        assert "acme/svc" not in prompt, f"raw owner/repo leaked into the narrate prompt: {prompt!r}"
        return '[{"text": "did work", "evidence_refs": ["private-repo-1#5"], "confidence": 0.9}]'

    def fake_extract():
        return [
            Evidence(
                kind="pr",
                ref=f"{ghes_key}#5",
                url=f"https://{GHES_HOST}/acme/svc/pull/5",
                detail=f"Work on {GHES_HOST}/acme/svc",
            )
        ]

    resolved = ResolvedSource(subject="alice", extract=fake_extract)

    result, n_masked = resolve_and_optionally_mask(
        resolved,
        subject="alice",
        runner=fake_runner,
        mask_private=True,
        visibility_lookup=_always_private,
    )

    # The runner WAS called (assert_maskable passed, masking succeeds) — and its prompt
    # was raw-GHES-free (asserted inside fake_runner above).
    assert len(runner_calls) >= 1, "runner should be called (GHES is now maskable, not refused)"
    # The final portfolio must not contain the raw GHES identity anywhere.
    assert n_masked >= 1, "at least one private repo must have been masked"
    for ev in result.portfolio.evidence:
        assert GHES_HOST not in ev.detail, f"GHES host leaked in detail: {ev.detail!r}"
        assert GHES_HOST not in ev.ref and GHES_HOST not in (ev.url or ""), "GHES leaked in ref/url"
    for cl in result.portfolio.claims:
        assert GHES_HOST not in cl.text and "acme/svc" not in cl.text, "GHES leaked in claim text"
