"""Tie the three layers together: extract (deterministic) → narrate (LLM) →
ground (deterministic). The output Portfolio carries ONLY grounded claims; the
rejected/needs-confirmation claims are returned alongside so nothing un-grounded
is shipped silently."""

from __future__ import annotations

from dataclasses import dataclass

from .extract import extract_merged_prs
from .grounding import GroundingResult, check_claims
from .model import Claim, Evidence, Portfolio
from .narrative import Runner, narrate, run_claude


@dataclass
class BuildResult:
    portfolio: Portfolio  # subject + evidence + grounded claims only
    grounding: GroundingResult  # full partition (grounded / rejected / needs_confirmation)


def build_from_evidence(subject: str, evidence: list[Evidence], runner: Runner, max_claims: int = 12) -> BuildResult:
    """Narrate over already-extracted evidence, ground the claims, assemble the
    Portfolio. Kept separate from extraction so it's testable with a fake runner."""
    drafted: list[Claim] = narrate(evidence, runner, max_claims=max_claims)
    grounding = check_claims(drafted, evidence)
    portfolio = Portfolio(subject=subject, evidence=evidence, claims=grounding.grounded)
    return BuildResult(portfolio=portfolio, grounding=grounding)


def build_portfolio(repo: str, author: str, runner: Runner = run_claude, max_claims: int = 12) -> BuildResult:
    """Full pipeline against a live repo: gh extract → model narrate → ground."""
    evidence = extract_merged_prs(repo=repo, author=author)
    return build_from_evidence(subject=author, evidence=evidence, runner=runner, max_claims=max_claims)
