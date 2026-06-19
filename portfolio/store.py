"""Serialize/deserialize a Portfolio to/from JSON.

Uses stdlib json + explicit field mapping only. No unsafe deserialization
functions anywhere in this module.
"""

from __future__ import annotations

import json

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
    if not isinstance(sv, int):
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
        evidence.append(
            Evidence(
                kind=item["kind"],
                ref=item["ref"],
                url=item["url"],
                detail=item["detail"],
                context=item["context"],
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
        if not isinstance(c["confidence"], (int, float)):
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
