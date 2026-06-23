"""Serialize/deserialize a Portfolio to/from JSON.

Uses stdlib json + explicit field mapping only. No unsafe deserialization
functions anywhere in this module.
"""

from __future__ import annotations

import json
import re

from portfolio.model import Claim, Evidence, Portfolio

SCHEMA_VERSION = 1


class PortfolioStoreError(Exception):
    """Raised when a Portfolio JSON fails validation."""


def portfolio_to_dict(p: Portfolio) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "subject": p.subject,
        "evidence": [
            {
                "kind": e.kind,
                "ref": e.ref,
                "url": e.url,
                "detail": e.detail,
                "context": e.context,
                "additions": e.additions,
                "deletions": e.deletions,
            }
            for e in p.evidence
        ],
        "claims": [
            {
                "text": c.text,
                "evidence_refs": list(c.evidence_refs),
                "confidence": c.confidence,
                "needs_user_confirmation": c.needs_user_confirmation,
                "grounded": c.grounded,
            }
            for c in p.claims
        ],
    }


def portfolio_to_json(p: Portfolio) -> str:
    return json.dumps(portfolio_to_dict(p), ensure_ascii=False)


def portfolio_from_dict(data: object) -> Portfolio:
    if not isinstance(data, dict):
        raise PortfolioStoreError(f"expected a JSON object at root, got {type(data).__name__}")

    # schema_version check
    if "schema_version" not in data:
        raise PortfolioStoreError("missing required root key: schema_version")
    sv = data["schema_version"]
    # bool is a subclass of int in Python, so `True`/`False` would otherwise pass
    # the int check (and `True == 1`); reject bool explicitly.
    if not isinstance(sv, int) or isinstance(sv, bool):
        raise PortfolioStoreError(f"schema_version must be an int, got {type(sv).__name__}")
    if sv != SCHEMA_VERSION:
        raise PortfolioStoreError(f"unsupported schema_version {sv!r}; expected {SCHEMA_VERSION}")

    # required root keys
    for key in ("subject", "evidence", "claims"):
        if key not in data:
            raise PortfolioStoreError(f"missing required root key: {key!r}")

    subject = data["subject"]
    if not isinstance(subject, str):
        raise PortfolioStoreError(f"subject must be a str, got {type(subject).__name__}")

    evidence_list = data["evidence"]
    if not isinstance(evidence_list, list):
        raise PortfolioStoreError(f"evidence must be a list, got {type(evidence_list).__name__}")

    evidence: list[Evidence] = []
    for i, item in enumerate(evidence_list):
        if not isinstance(item, dict):
            raise PortfolioStoreError(f"evidence[{i}] must be a dict")
        for field in ("kind", "ref", "url", "detail", "context"):
            if field not in item:
                raise PortfolioStoreError(f"evidence[{i}] missing required field: {field!r}")
            if not isinstance(item[field], str):
                raise PortfolioStoreError(f"evidence[{i}].{field} must be a str, got {type(item[field]).__name__}")
        # additions/deletions are optional for backward compatibility with
        # portfolios written before the change-scale field existed; default 0.
        # bool is an int subclass, so reject it explicitly (matches schema_version).
        line_counts: dict[str, int] = {}
        for field in ("additions", "deletions"):
            val = item.get(field, 0)
            if not isinstance(val, int) or isinstance(val, bool):
                raise PortfolioStoreError(f"evidence[{i}].{field} must be an int, got {type(val).__name__}")
            if val < 0:
                raise PortfolioStoreError(f"evidence[{i}].{field} must be non-negative, got {val}")
            line_counts[field] = val
        evidence.append(
            Evidence(
                kind=item["kind"],
                ref=item["ref"],
                url=item["url"],
                detail=item["detail"],
                context=item["context"],
                additions=line_counts["additions"],
                deletions=line_counts["deletions"],
            )
        )

    claims_list = data["claims"]
    if not isinstance(claims_list, list):
        raise PortfolioStoreError(f"claims must be a list, got {type(claims_list).__name__}")

    claims: list[Claim] = []
    for i, item in enumerate(claims_list):
        if not isinstance(item, dict):
            raise PortfolioStoreError(f"claims[{i}] must be a dict")
        for field in ("text", "evidence_refs", "confidence", "needs_user_confirmation", "grounded"):
            if field not in item:
                raise PortfolioStoreError(f"claims[{i}] missing required field: {field!r}")
        c = item
        if not isinstance(c["text"], str):
            raise PortfolioStoreError(f"claims[{i}].text must be a str")
        if not isinstance(c["evidence_refs"], list):
            raise PortfolioStoreError(f"claims[{i}].evidence_refs must be a list")
        for j, r in enumerate(c["evidence_refs"]):
            if not isinstance(r, str):
                raise PortfolioStoreError(f"claims[{i}].evidence_refs[{j}] must be a str")
        if not isinstance(c["confidence"], (int, float)) or isinstance(c["confidence"], bool):
            raise PortfolioStoreError(f"claims[{i}].confidence must be a number")
        if not isinstance(c["needs_user_confirmation"], bool):
            raise PortfolioStoreError(f"claims[{i}].needs_user_confirmation must be a bool")
        grounded_val = c["grounded"]
        if grounded_val is not None and not isinstance(grounded_val, bool):
            raise PortfolioStoreError(f"claims[{i}].grounded must be bool or null")
        claims.append(
            Claim(
                text=c["text"],
                evidence_refs=list(c["evidence_refs"]),
                confidence=float(c["confidence"]),
                needs_user_confirmation=c["needs_user_confirmation"],
                grounded=grounded_val,
            )
        )

    return Portfolio(subject=subject, evidence=evidence, claims=claims)


def portfolio_from_json(text: str) -> Portfolio:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PortfolioStoreError(f"invalid JSON: {exc}") from exc
    return portfolio_from_dict(data)


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

# Bare PR ref pattern: "PR#<digits>" with no owner/repo prefix.
_BARE_PR_RE = re.compile(r"^PR#\d+$")


def _check_bare_refs(portfolio: Portfolio, label: str) -> None:
    """Raise PortfolioStoreError if portfolio has any bare (non-repo-qualified) evidence ref.

    Two single-repo portfolios could each carry a "PR#1" meaning different PRs;
    silently collapsing them would destroy grounding. Rejection is the committed
    strategy (PR-002): no namespacing, no ref rewriting.
    """
    for e in portfolio.evidence:
        if e.kind == "pr" and _BARE_PR_RE.match(e.ref):
            raise PortfolioStoreError(
                f"input portfolio {label} contains bare PR ref {e.ref!r}; "
                "merge inputs must use repo-qualified refs (e.g. 'owner/repo#1')"
            )
        if e.kind == "file" and ":" not in e.ref:
            raise PortfolioStoreError(
                f"input portfolio {label} contains bare file ref {e.ref!r}; "
                "merge inputs must use repo-qualified file refs (e.g. 'owner/repo:path/to/file')"
            )


def merge_portfolios(portfolios: list[Portfolio], *, subject: str) -> Portfolio:
    """Merge two or more Portfolio objects into a single grounded Portfolio.

    The ``subject`` argument is authoritative: it becomes the merged portfolio's
    subject regardless of the subjects of the input portfolios (the multi-account
    case, e.g. alice-corp + alice-personal → "Alice Smith").

    Evidence is deduped on (kind, ref); first-seen entry wins.  Claims from all
    inputs are unioned; the grounding gate is re-applied against the merged
    evidence set and any claim whose cited ref is absent is dropped.

    Raises PortfolioStoreError when:
    - ``portfolios`` is empty
    - ``subject`` is empty or whitespace-only
    - any input portfolio contains a bare (non-repo-qualified) evidence ref
    """
    if not subject or not subject.strip():
        raise PortfolioStoreError("subject must be a non-empty, non-whitespace string")
    if not portfolios:
        raise PortfolioStoreError("portfolios must be a non-empty list")

    # Guard: all inputs must use repo-qualified refs before any merge starts
    for i, p in enumerate(portfolios):
        _check_bare_refs(p, str(i))

    # Union evidence by (kind, ref), preserving first-seen order
    seen_keys: set[tuple[str, str]] = set()
    merged_evidence: list[Evidence] = []
    for p in portfolios:
        for e in p.evidence:
            key = (e.kind, e.ref)
            if key not in seen_keys:
                seen_keys.add(key)
                merged_evidence.append(e)

    # Collect all claims; copy to avoid mutating the caller's Portfolio objects
    all_claims: list[Claim] = [
        Claim(
            text=c.text,
            evidence_refs=list(c.evidence_refs),
            confidence=c.confidence,
            needs_user_confirmation=c.needs_user_confirmation,
            grounded=c.grounded,
        )
        for p in portfolios
        for c in p.claims
    ]

    # Re-run the grounding gate; drop any claim whose refs aren't in merged evidence
    from portfolio.grounding import check_claims  # deferred — grounding imports model, not store

    result = check_claims(all_claims, merged_evidence)
    final_claims = result.grounded + result.needs_confirmation

    return Portfolio(subject=subject, evidence=merged_evidence, claims=final_claims)
