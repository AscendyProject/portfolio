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
from .synthesis import SynthesisResult, synthesize


@dataclass
class BuildResult:
    portfolio: Portfolio  # subject + evidence + grounded claims only
    grounding: GroundingResult  # full partition (grounded / rejected / needs_confirmation)
    synthesis: SynthesisResult | None = None  # grounded headline + highlights; None when skipped


def build_from_evidence(
    subject: str,
    evidence: list[Evidence],
    runner: Runner,
    max_claims: int = 12,
    *,
    synthesis_runner: Runner | None = None,
) -> BuildResult:
    """Narrate over already-extracted evidence, ground the claims, assemble the
    Portfolio. Kept separate from extraction so it's testable with a fake runner.

    synthesis_runner is keyword-only (after max_claims) so positional callers
    passing four args (subject, evidence, runner, max_claims) are unaffected.
    When synthesis_runner is None, or portfolio.claims is empty, synthesis is skipped.
    """
    drafted: list[Claim] = narrate(evidence, runner, max_claims=max_claims)
    grounding = check_claims(drafted, evidence)
    portfolio = Portfolio(subject=subject, evidence=evidence, claims=grounding.grounded)
    synthesis: SynthesisResult | None = None
    if synthesis_runner is not None and portfolio.claims:
        synthesis = synthesize(portfolio, synthesis_runner)
    return BuildResult(portfolio=portfolio, grounding=grounding, synthesis=synthesis)


def resolve_to_build_result(
    resolved,  # ResolvedSource — imported locally to avoid circular import
    subject: str,
    runner: Runner,
    max_claims: int = 12,
    *,
    synthesis_runner: Runner | None = None,
) -> BuildResult:
    """Shared helper used by all five CLIs.

    If the resolved source has a prebuilt Portfolio (the 'portfolio' source type),
    re-apply the grounding gate and return a BuildResult directly — skipping
    extraction and narration. Otherwise extract + narrate + ground as normal.
    """
    if getattr(resolved, "prebuilt", None) is not None:
        grounding = check_claims(list(resolved.prebuilt.claims), resolved.prebuilt.evidence)
        portfolio = Portfolio(
            subject=resolved.prebuilt.subject,
            evidence=resolved.prebuilt.evidence,
            claims=grounding.grounded,
        )
        result_synthesis: SynthesisResult | None = None
        if synthesis_runner is not None and portfolio.claims:
            result_synthesis = synthesize(portfolio, synthesis_runner)
        return BuildResult(portfolio=portfolio, grounding=grounding, synthesis=result_synthesis)
    evidence = resolved.extract()
    return build_from_evidence(
        subject=subject,
        evidence=evidence,
        runner=runner,
        max_claims=max_claims,
        synthesis_runner=synthesis_runner,
    )


def build_portfolio(repo: str, author: str, runner: Runner = run_claude, max_claims: int = 12) -> BuildResult:
    """Full pipeline against a live repo: gh extract → model narrate → ground."""
    evidence = extract_merged_prs(repo=repo, author=author)
    return build_from_evidence(subject=author, evidence=evidence, runner=runner, max_claims=max_claims)
