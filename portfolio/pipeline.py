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
from .synthesis import HighlightBullet, SynthesisResult, synthesize


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


def resolve_and_optionally_mask(
    resolved,
    subject: str,
    runner: Runner,
    max_claims: int = 12,
    *,
    mask_private: bool = False,
    synthesis_runner: Runner | None = None,
    visibility_lookup=None,
) -> tuple[BuildResult, int]:
    """Returns (BuildResult, n_masked). n_masked is 0 when mask_private=False.

    When mask_private=True, orders work as:
    extract → narrate → ground → mask → synthesize (post-scrub).
    """
    if not mask_private:
        result = resolve_to_build_result(
            resolved,
            subject=subject,
            runner=runner,
            max_claims=max_claims,
            synthesis_runner=synthesis_runner,
        )
        return result, 0

    # mask_private=True: run pipeline WITHOUT synthesis first
    no_synth_result = resolve_to_build_result(
        resolved,
        subject=subject,
        runner=runner,
        max_claims=max_claims,
        synthesis_runner=None,
    )

    # Import masking functions here to avoid circular imports
    from .mask import (
        _build_relabel_map,
        _gh_visibility_lookup,
        extract_repo_names,
        mask_portfolio,
        private_repos,
    )

    lk = visibility_lookup if visibility_lookup is not None else _gh_visibility_lookup
    repos = extract_repo_names(no_synth_result.portfolio)
    priv = private_repos(repos, visibility_lookup=lk)
    masked_portfolio = mask_portfolio(no_synth_result.portfolio, priv)

    # Run synthesis on the masked portfolio (if requested)
    synthesis: SynthesisResult | None = None
    if synthesis_runner is not None and masked_portfolio.claims:
        raw_synthesis = synthesize(masked_portfolio, synthesis_runner)
        # Post-synthesis scrub: replace private owner/repo in text fields
        relabel = _build_relabel_map(priv)
        if relabel and raw_synthesis is not None:
            # Scrub headline
            new_headline = raw_synthesis.headline
            if new_headline is not None:
                for repo, label in relabel.items():
                    new_headline = new_headline.replace(repo, label)
            # Scrub headline_refs
            new_headline_refs = (
                [
                    ref.replace(repo, label)
                    for ref in raw_synthesis.headline_refs
                    for repo, label in [(repo, relabel[repo]) for repo in relabel]
                ]
                if raw_synthesis.headline_refs
                else []
            )
            # Rebuild headline_refs properly (multiple repos)
            new_headline_refs = list(raw_synthesis.headline_refs)
            for repo, label in relabel.items():
                new_headline_refs = [r.replace(repo, label) for r in new_headline_refs]
            # Scrub highlights
            new_highlights = []
            for hl in raw_synthesis.highlights:
                scrubbed_text = hl.text
                for repo, label in relabel.items():
                    scrubbed_text = scrubbed_text.replace(repo, label)
                scrubbed_refs = list(hl.evidence_refs)
                for repo, label in relabel.items():
                    scrubbed_refs = [r.replace(repo, label) for r in scrubbed_refs]
                new_highlights.append(HighlightBullet(text=scrubbed_text, evidence_refs=scrubbed_refs))
            synthesis = SynthesisResult(
                headline=new_headline,
                headline_refs=new_headline_refs,
                highlights=new_highlights,
            )
        else:
            synthesis = raw_synthesis

    return (
        BuildResult(
            portfolio=masked_portfolio,
            grounding=no_synth_result.grounding,
            synthesis=synthesis,
        ),
        len(priv),
    )
