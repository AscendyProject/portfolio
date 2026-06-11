"""Data model for grounded portfolio generation.

The whole point of this harness is that **every claim is grounded** — a portfolio
statement must trace to real evidence (a PR, commit, file, review) pulled
deterministically from `gh`, never invented by a model. These dataclasses carry
that contract: a Claim without surviving Evidence is not shippable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Evidence kinds the extractor can produce. A claim may only cite these.
EVIDENCE_KINDS = ("pr", "commit", "issue", "review", "file", "release")


@dataclass(frozen=True)
class Evidence:
    """A single, verifiable artifact pulled from `gh` — the ground truth a claim
    points at. `ref` is the stable identifier (e.g. "PR#128", "abc1234",
    "app/auth_service.py") used to check a claim against the extracted set."""

    kind: str  # one of EVIDENCE_KINDS
    ref: str  # stable id, e.g. "PR#128" / "abc1234" / "app/auth.py"
    url: str = ""  # optional link
    detail: str = ""  # optional one-line context


@dataclass
class Claim:
    """A portfolio statement plus the evidence refs it rests on. `confidence` and
    `needs_user_confirmation` mirror the trust-gate contract; `grounded` is set by
    the grounding check (never trust a self-reported value)."""

    text: str
    evidence_refs: list[str] = field(default_factory=list)  # refs into the Evidence set
    confidence: float = 0.0
    needs_user_confirmation: bool = False
    grounded: bool | None = None  # set by grounding.check_claims; None = unchecked


@dataclass
class Portfolio:
    """The output: who it's for, the evidence corpus, and the grounded claims."""

    subject: str  # github handle / name
    evidence: list[Evidence] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
