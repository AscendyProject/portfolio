"""Tests for portfolio/store.py — round-trip, defensive parse, hygiene, forward-compat.

Each test traces to a Done-when item in outcome.md via its docstring.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.model import Claim, Evidence, Portfolio  # noqa: E402
from portfolio.store import (  # noqa: E402
    PortfolioStoreError,
    portfolio_from_dict,
    portfolio_from_json,
    portfolio_to_dict,
    portfolio_to_json,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


def _make_portfolio() -> Portfolio:
    """Portfolio with ≥2 Evidence and ≥2 Claims (one needs_user_confirmation, one grounded=False)."""
    evidence = [
        Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1", detail="Add thing", context="ctx1"),
        Evidence(kind="commit", ref="abc123", url="", detail="Fix bug", context="ctx2"),
    ]
    claims = [
        Claim(
            text="Built the thing", evidence_refs=["PR#1"], confidence=0.9, needs_user_confirmation=False, grounded=True
        ),
        Claim(
            text="Unconfirmed claim",
            evidence_refs=["abc123"],
            confidence=0.5,
            needs_user_confirmation=True,
            grounded=True,
        ),
        Claim(
            text="Ungrounded claim",
            evidence_refs=["PR#1"],
            confidence=0.3,
            needs_user_confirmation=False,
            grounded=False,
        ),
    ]
    return Portfolio(subject="alice", evidence=evidence, claims=claims)


# ---------------------------------------------------------------------------
# Done-when: round-trip
# ---------------------------------------------------------------------------


def test_round_trip():
    """'portfolio_from_json(portfolio_to_json(p)) == p' for a Portfolio carrying ≥2 Evidence
    entries and ≥2 Claim entries (one with needs_user_confirmation=True, one with grounded=False)."""
    p = _make_portfolio()
    result = portfolio_from_json(portfolio_to_json(p))
    assert result == p


# ---------------------------------------------------------------------------
# Done-when: top-level schema
# ---------------------------------------------------------------------------


def test_to_dict_schema_version():
    """'dict from portfolio_to_dict has schema_version: 1 and the required keys.'"""
    p = _make_portfolio()
    d = portfolio_to_dict(p)
    assert d["schema_version"] == 1
    assert "subject" in d
    assert "evidence" in d
    assert "claims" in d


def test_to_dict_evidence_fields():
    """All Evidence fields (kind, ref, url, detail, context) are serialized."""
    p = _make_portfolio()
    d = portfolio_to_dict(p)
    e0 = d["evidence"][0]
    assert e0["kind"] == "pr"
    assert e0["ref"] == "PR#1"
    assert e0["url"] == "https://github.com/o/r/pull/1"
    assert e0["detail"] == "Add thing"
    assert e0["context"] == "ctx1"


def test_to_dict_claim_fields():
    """All Claim fields (text, evidence_refs, confidence, needs_user_confirmation, grounded) are serialized."""
    p = _make_portfolio()
    d = portfolio_to_dict(p)
    c0 = d["claims"][0]
    assert c0["text"] == "Built the thing"
    assert c0["evidence_refs"] == ["PR#1"]
    assert c0["confidence"] == 0.9
    assert c0["needs_user_confirmation"] is False
    assert c0["grounded"] is True


# ---------------------------------------------------------------------------
# Done-when: defensive parse
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_data,match",
    [
        # missing schema_version
        ({"subject": "a", "evidence": [], "claims": []}, "schema_version"),
        # schema_version != 1 (zero)
        ({"schema_version": 0, "subject": "a", "evidence": [], "claims": []}, "schema_version"),
        # schema_version != 1 (two)
        ({"schema_version": 2, "subject": "a", "evidence": [], "claims": []}, "schema_version"),
        # missing required root key (subject)
        ({"schema_version": 1, "evidence": [], "claims": []}, "subject"),
        # missing required root key (evidence)
        ({"schema_version": 1, "subject": "a", "claims": []}, "evidence"),
        # missing required root key (claims)
        ({"schema_version": 1, "subject": "a", "evidence": []}, "claims"),
    ],
)
def test_defensive_parse_dict_errors(bad_data, match):
    """Missing or wrong schema_version / missing required root key → PortfolioStoreError."""
    with pytest.raises(PortfolioStoreError, match=match):
        portfolio_from_dict(bad_data)


@pytest.mark.parametrize(
    "root",
    [
        [],  # list
        "string",  # str
        42,  # number
        None,  # null
    ],
)
def test_defensive_parse_non_dict_root(root):
    """Non-dict root (list / str / number / null) → PortfolioStoreError."""
    with pytest.raises(PortfolioStoreError):
        portfolio_from_dict(root)


def test_defensive_parse_missing_evidence_field():
    """Missing required field inside an Evidence → PortfolioStoreError."""
    data = {
        "schema_version": 1,
        "subject": "alice",
        "evidence": [{"kind": "pr", "ref": "PR#1", "url": "", "detail": "x"}],  # missing context
        "claims": [],
    }
    with pytest.raises(PortfolioStoreError, match="context"):
        portfolio_from_dict(data)


def test_defensive_parse_missing_claim_field():
    """Missing required field inside a Claim → PortfolioStoreError."""
    data = {
        "schema_version": 1,
        "subject": "alice",
        "evidence": [],
        "claims": [
            {"text": "x", "evidence_refs": [], "confidence": 0.5, "needs_user_confirmation": False}
        ],  # missing grounded
    }
    with pytest.raises(PortfolioStoreError, match="grounded"):
        portfolio_from_dict(data)


def test_defensive_parse_wrong_type_subject():
    """Wrong type for subject → PortfolioStoreError."""
    data = {"schema_version": 1, "subject": 123, "evidence": [], "claims": []}
    with pytest.raises(PortfolioStoreError):
        portfolio_from_dict(data)


def test_defensive_parse_wrong_type_confidence():
    """Wrong type for confidence (string) → PortfolioStoreError."""
    data = {
        "schema_version": 1,
        "subject": "alice",
        "evidence": [],
        "claims": [
            {
                "text": "x",
                "evidence_refs": [],
                "confidence": "high",
                "needs_user_confirmation": False,
                "grounded": True,
            }
        ],
    }
    with pytest.raises(PortfolioStoreError):
        portfolio_from_dict(data)


def test_defensive_parse_invalid_json():
    """Invalid JSON string → PortfolioStoreError (not a raw json.JSONDecodeError)."""
    with pytest.raises(PortfolioStoreError):
        portfolio_from_json("not json at all {{{")


# ---------------------------------------------------------------------------
# Done-when: untrusted-input hygiene
# ---------------------------------------------------------------------------


def test_no_dangerous_functions_in_store():
    """store.py contains no eval(, exec(, pickle, marshal, __reduce__, shelve."""
    store_path = _REPO_ROOT / "portfolio" / "store.py"
    content = store_path.read_text(encoding="utf-8")
    for forbidden in ("eval(", "exec(", "pickle", "marshal", "__reduce__", "shelve"):
        assert forbidden not in content, f"store.py must not contain {forbidden!r}"


# ---------------------------------------------------------------------------
# Done-when: unknown-key tolerance
# ---------------------------------------------------------------------------


def test_unknown_root_keys_ignored():
    """Extra unknown keys at root are ignored (forward-compat)."""
    data = {
        "schema_version": 1,
        "subject": "alice",
        "evidence": [],
        "claims": [],
        "unknown_future_key": "some value",
    }
    p = portfolio_from_dict(data)
    assert p.subject == "alice"


def test_unknown_evidence_keys_ignored():
    """Extra unknown keys inside Evidence are ignored (forward-compat)."""
    data = {
        "schema_version": 1,
        "subject": "alice",
        "evidence": [
            {
                "kind": "pr",
                "ref": "PR#1",
                "url": "",
                "detail": "",
                "context": "",
                "future_field": "ignored",
            }
        ],
        "claims": [],
    }
    p = portfolio_from_dict(data)
    assert len(p.evidence) == 1
    assert p.evidence[0].ref == "PR#1"


def test_unknown_claim_keys_ignored():
    """Extra unknown keys inside Claim are ignored (forward-compat)."""
    data = {
        "schema_version": 1,
        "subject": "alice",
        "evidence": [{"kind": "pr", "ref": "PR#1", "url": "", "detail": "", "context": ""}],
        "claims": [
            {
                "text": "Built thing",
                "evidence_refs": ["PR#1"],
                "confidence": 0.9,
                "needs_user_confirmation": False,
                "grounded": True,
                "future_claim_field": "ignored",
            }
        ],
    }
    p = portfolio_from_dict(data)
    assert len(p.claims) == 1
    assert p.claims[0].text == "Built thing"
