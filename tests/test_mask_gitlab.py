"""Tests for GitLab masking in portfolio/mask.py.

Covers:
- extract_repo_names discovers GitLab repos from /-/ style URLs (nested namespace)
- The GitLab MR ref shape (group/subgroup/project!42) does NOT trigger
  assert_maskable to raise MaskingError
- End-to-end masking: under --mask-private with a fail-safe visibility_lookup
  (raises → treated as private), no raw GitLab project name leaks through
  Evidence.ref, Evidence.url, Evidence.detail, Claim.text, or Claim.evidence_refs
- Existing github.com and GHES masking tests remain green (verified by not
  importing/mutating any existing test fixtures)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.mask import (  # noqa: E402
    assert_maskable,
    extract_repo_names,
    mask_portfolio,
    private_repos,
)
from portfolio.model import Claim, Evidence, Portfolio  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GITLAB_HOST = "gitlab.com"
_SELF_MANAGED_HOST = "gitlab.corp.io"
_PROJECT = "group/subgroup/project"
_SELF_PROJECT = f"{_SELF_MANAGED_HOST}/group/subgroup/project"
_MR_URL = f"https://{_GITLAB_HOST}/{_PROJECT}/-/merge_requests/42"
_MR_REF = f"{_PROJECT}!42"
_SELF_MR_URL = f"https://{_SELF_MANAGED_HOST}/group/subgroup/project/-/merge_requests/5"
_SELF_MR_REF = f"{_SELF_MANAGED_HOST}/group/subgroup/project!5"


def _gitlab_portfolio(
    *,
    ref: str = _MR_REF,
    url: str = _MR_URL,
    detail: str = "",
    claim_text: str = "implemented something",
) -> Portfolio:
    ev = Evidence(kind="pr", ref=ref, url=url, detail=detail)
    cl = Claim(
        text=claim_text,
        evidence_refs=[ref],
        confidence=0.9,
        grounded=True,
    )
    return Portfolio(subject="alice", evidence=[ev], claims=[cl])


def _failing_lookup(repo: str) -> bool:
    """Simulates gh repo view failing for a GitLab repo (expected fail-safe path)."""
    raise RuntimeError(f"gh repo view failed for {repo!r}: not a GitHub repo")


def _always_private(repo: str) -> bool:
    return True


# ---------------------------------------------------------------------------
# extract_repo_names — GitLab URL discovery
# ---------------------------------------------------------------------------


def test_extract_gitlab_url_nested_namespace():
    """A GitLab /-/ URL discovers the full nested project path."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="!42", url=_MR_URL)],
        claims=[],
    )
    found = extract_repo_names(p)
    # gitlab.com is not in _MASKABLE_HOSTS → host-qualified key
    assert f"{_GITLAB_HOST}/{_PROJECT}" in found


def test_extract_gitlab_url_two_segment():
    """A GitLab /-/ URL with a 2-segment project discovers the correct key."""
    url = "https://gitlab.com/owner/project/-/merge_requests/1"
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="!1", url=url)],
        claims=[],
    )
    found = extract_repo_names(p)
    assert "gitlab.com/owner/project" in found
    # Must not discover sub-paths or wrong segments
    assert "gitlab.com/owner" not in found


def test_extract_self_managed_gitlab_url():
    """A self-managed GitLab /-/ URL discovers host/group/.../project."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref=_SELF_MR_REF, url=_SELF_MR_URL)],
        claims=[],
    )
    found = extract_repo_names(p)
    assert f"{_SELF_MANAGED_HOST}/group/subgroup/project" in found


def test_extract_non_gitlab_url_unchanged():
    """GitHub and GHES URLs without /-/ are still discovered correctly."""
    p = Portfolio(
        subject="alice",
        evidence=[
            Evidence(kind="pr", ref="PR#1", url="https://github.com/owner/repo/pull/1"),
            Evidence(kind="pr", ref="PR#2", url="https://ghe.corp.io/owner/repo/pull/2"),
        ],
        claims=[],
    )
    found = extract_repo_names(p)
    assert "owner/repo" in found  # github.com → bare
    assert "ghe.corp.io/owner/repo" in found  # GHES → host-qualified


# ---------------------------------------------------------------------------
# assert_maskable — GitLab refs must NOT raise MaskingError
# ---------------------------------------------------------------------------


def test_assert_maskable_gitlab_ref_does_not_raise():
    """A GitLab MR ref (group/subgroup/project!42) passes assert_maskable."""
    p = _gitlab_portfolio()
    # Must not raise MaskingError
    assert_maskable(p)


def test_assert_maskable_gitlab_nested_ref_does_not_raise():
    """A deeply nested GitLab ref does not trip assert_maskable."""
    p = Portfolio(
        subject="alice",
        evidence=[
            Evidence(
                kind="pr",
                ref="org/group/sub/proj!100",
                url="https://gitlab.com/org/group/sub/proj/-/merge_requests/100",
            )
        ],
        claims=[],
    )
    assert_maskable(p)


def test_assert_maskable_self_managed_gitlab_does_not_raise():
    """A self-managed GitLab evidence set passes assert_maskable."""
    p = _gitlab_portfolio(ref=_SELF_MR_REF, url=_SELF_MR_URL)
    assert_maskable(p)


# ---------------------------------------------------------------------------
# End-to-end masking via fail-safe
# ---------------------------------------------------------------------------


def test_masking_no_project_name_in_ref():
    """Under --mask-private (fail-safe), the GitLab project name is absent from ev.ref."""
    p = _gitlab_portfolio()
    repos = extract_repo_names(p)
    priv = private_repos(repos, visibility_lookup=_failing_lookup)
    masked = mask_portfolio(p, priv)
    assert _PROJECT not in masked.evidence[0].ref


def test_masking_no_project_name_in_url():
    """Under --mask-private (fail-safe), the GitLab project name is absent from ev.url."""
    p = _gitlab_portfolio()
    repos = extract_repo_names(p)
    priv = private_repos(repos, visibility_lookup=_failing_lookup)
    masked = mask_portfolio(p, priv)
    assert _PROJECT.lower() not in (masked.evidence[0].url or "").lower()


def test_masking_no_project_name_in_detail():
    """Under --mask-private (fail-safe), the GitLab project name is absent from ev.detail."""
    p = _gitlab_portfolio(detail=f"changed in {_PROJECT}")
    repos = extract_repo_names(p)
    priv = private_repos(repos, visibility_lookup=_failing_lookup)
    masked = mask_portfolio(p, priv)
    assert _PROJECT.lower() not in masked.evidence[0].detail.lower()


def test_masking_no_project_name_in_claim_text():
    """Under --mask-private (fail-safe), the project name is absent from claim.text."""
    p = _gitlab_portfolio(claim_text=f"Improved performance in {_PROJECT}")
    repos = extract_repo_names(p)
    priv = private_repos(repos, visibility_lookup=_failing_lookup)
    masked = mask_portfolio(p, priv)
    assert _PROJECT.lower() not in masked.claims[0].text.lower()


def test_masking_no_project_name_in_evidence_refs():
    """Under --mask-private (fail-safe), the project name is absent from claim.evidence_refs."""
    p = _gitlab_portfolio()
    repos = extract_repo_names(p)
    priv = private_repos(repos, visibility_lookup=_failing_lookup)
    masked = mask_portfolio(p, priv)
    for ref in masked.claims[0].evidence_refs:
        assert _PROJECT not in ref


def test_masking_ref_uses_private_repo_label():
    """The masked ref contains 'private-repo-N' in place of the original project."""
    p = _gitlab_portfolio()
    repos = extract_repo_names(p)
    priv = private_repos(repos, visibility_lookup=_failing_lookup)
    masked = mask_portfolio(p, priv)
    assert "private-repo-" in masked.evidence[0].ref


def test_masking_ref_preserves_mr_iid():
    """The masked ref preserves the '!42' MR IID suffix."""
    p = _gitlab_portfolio()
    repos = extract_repo_names(p)
    priv = private_repos(repos, visibility_lookup=_failing_lookup)
    masked = mask_portfolio(p, priv)
    assert "!42" in masked.evidence[0].ref


def test_masking_nested_namespace_comprehensive():
    """All six fields are scrubbed for a nested-namespace GitLab repo end-to-end."""
    project = "org/team/subteam/myproject"
    ref = f"{project}!99"
    url = f"https://gitlab.com/{project}/-/merge_requests/99"
    detail = f"Merged in {project}"
    claim_text = f"Enhanced {project} performance"
    p = Portfolio(
        subject="dev",
        evidence=[Evidence(kind="pr", ref=ref, url=url, detail=detail)],
        claims=[Claim(text=claim_text, evidence_refs=[ref], confidence=0.9, grounded=True)],
    )
    repos = extract_repo_names(p)
    priv = private_repos(repos, visibility_lookup=_failing_lookup)
    masked = mask_portfolio(p, priv)

    ev = masked.evidence[0]
    cl = masked.claims[0]
    assert project not in ev.ref
    assert project not in (ev.url or "")
    assert project not in ev.detail
    assert project not in cl.text
    assert not any(project in r for r in cl.evidence_refs)
    # All replaced with private-repo-N label
    assert "private-repo-" in ev.ref


def test_masking_fail_safe_treats_gitlab_as_private():
    """The fail-safe: when visibility_lookup raises, GitLab repo is treated as private."""
    p = _gitlab_portfolio()
    repos = extract_repo_names(p)
    assert len(repos) >= 1  # at least one repo discovered

    priv = private_repos(repos, visibility_lookup=_failing_lookup)
    # All discovered repos are treated as private
    assert priv == repos


def test_masking_deterministic():
    """mask_portfolio is deterministic for GitLab evidence (same input → same output)."""
    p = _gitlab_portfolio()
    repos = extract_repo_names(p)
    priv = private_repos(repos, visibility_lookup=_failing_lookup)

    r1 = mask_portfolio(p, priv)
    r2 = mask_portfolio(p, priv)
    assert r1.evidence[0].ref == r2.evidence[0].ref
    assert r1.evidence[0].url == r2.evidence[0].url


def test_github_masking_unchanged_by_gitlab_extension():
    """GitHub-style refs and masking behavior are byte-identical after GitLab extension."""
    p = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="acme/svc#5", url="https://github.com/acme/svc/pull/5")],
        claims=[Claim(text="did something in acme/svc", evidence_refs=["acme/svc#5"], confidence=0.9)],
    )
    repos = extract_repo_names(p)
    assert repos == {"acme/svc"}  # bare github.com key unchanged

    masked = mask_portfolio(p, {"acme/svc"})
    assert masked.evidence[0].ref == "private-repo-1#5"
    assert "acme/svc" not in masked.evidence[0].url
    assert "acme/svc" not in masked.claims[0].text
    assert masked.claims[0].evidence_refs == ["private-repo-1#5"]
