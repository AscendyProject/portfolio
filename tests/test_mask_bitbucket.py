"""End-to-end masking of the NEW Bitbucket extractor's evidence.

These tests build Evidence by running ``extract_merged_prs_bitbucket`` (the new
Bitbucket extractor) against a fake fetcher, then assert the masking layer scrubs
the private ``workspace/repo`` everywhere. They depend on the new extractor, so they
fail against pre-change product code (codex task-036 IR-001 — new tests must be
failure-driving, not validate already-shipped masking behavior).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.extract_bitbucket import extract_merged_prs_bitbucket  # noqa: E402
from portfolio.mask import (  # noqa: E402
    assert_maskable,
    extract_repo_names,
    mask_portfolio,
    private_repos,
)
from portfolio.model import Portfolio  # noqa: E402

_WS = "acme"
_REPO = "secret-widgets"
_PRIVATE_KEY = f"bitbucket.org/{_WS}/{_REPO}"

_PR_LIST_PAGE = {
    "values": [
        {
            "id": 7,
            "title": "Fix login bug",
            "state": "MERGED",
            "links": {"html": {"href": f"https://bitbucket.org/{_WS}/{_REPO}/pull-requests/7"}},
        },
    ],
}

_DIFFSTAT_PAGE = {
    "values": [
        {
            "status": "modified",
            "lines_added": 10,
            "lines_removed": 3,
            "new": {"path": "src/auth.py"},
            "old": {"path": "src/auth.py"},
        },
    ],
}


def _fake_fetcher(url, *, auth):
    if "/diffstat" in url:
        return _DIFFSTAT_PAGE
    return _PR_LIST_PAGE


def _raises(_repo):
    # Production fail-safe path: a visibility lookup that cannot resolve the host
    # raises, so private_repos treats the repo as private (mask).
    raise RuntimeError("visibility lookup unavailable")


def _extract_evidence():
    with patch.dict(os.environ, {"BITBUCKET_TOKEN": "tok"}, clear=False):
        return extract_merged_prs_bitbucket(_WS, _REPO, "alice", fetcher=_fake_fetcher)


def test_bitbucket_extractor_evidence_passes_assert_maskable():
    """The new extractor's Bitbucket PR/file evidence does not trip assert_maskable."""
    portfolio = Portfolio(subject="alice", evidence=_extract_evidence(), claims=[])
    assert_maskable(portfolio)  # must not raise


def test_bitbucket_extractor_private_repo_discovered():
    """The host-qualified Bitbucket key is discovered from the extractor's PR evidence."""
    portfolio = Portfolio(subject="alice", evidence=_extract_evidence(), claims=[])
    assert _PRIVATE_KEY in extract_repo_names(portfolio)


def test_bitbucket_extractor_private_repo_masked_end_to_end():
    """Masking the extractor's evidence leaves no raw workspace/repo in any field
    (fail-safe: visibility lookup raises -> treated as private -> relabeled)."""
    portfolio = Portfolio(subject="alice", evidence=_extract_evidence(), claims=[])
    priv = private_repos(extract_repo_names(portfolio), visibility_lookup=_raises)
    masked = mask_portfolio(portfolio, priv)
    raw = f"{_WS}/{_REPO}"
    for ev in masked.evidence:
        assert raw not in (ev.ref or ""), f"workspace/repo leaked in ref: {ev.ref!r}"
        assert raw not in (ev.url or ""), f"workspace/repo leaked in url: {ev.url!r}"
        assert raw not in (ev.detail or ""), f"workspace/repo leaked in detail: {ev.detail!r}"
