"""Tie the three layers together: extract (deterministic) → narrate (LLM) →
ground (deterministic). The output Portfolio carries ONLY grounded claims; the
rejected/needs-confirmation claims are returned alongside so nothing un-grounded
is shipped silently."""

from __future__ import annotations

from dataclasses import dataclass, field

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
    relabel: dict[str, str] = field(default_factory=dict)  # private-repo-N map; empty when mask_private=False


def build_from_evidence(
    subject: str,
    evidence: list[Evidence],
    runner: Runner,
    max_claims: int = 12,
    *,
    synthesis_runner: Runner | None = None,
    lang: str = "en",
) -> BuildResult:
    """Narrate over already-extracted evidence, ground the claims, assemble the
    Portfolio. Kept separate from extraction so it's testable with a fake runner.

    synthesis_runner is keyword-only (after max_claims) so positional callers
    passing four args (subject, evidence, runner, max_claims) are unaffected.
    When synthesis_runner is None, or portfolio.claims is empty, synthesis is skipped.
    """
    drafted: list[Claim] = narrate(evidence, runner, max_claims=max_claims, lang=lang)
    grounding = check_claims(drafted, evidence)
    portfolio = Portfolio(subject=subject, evidence=evidence, claims=grounding.grounded)
    synthesis: SynthesisResult | None = None
    if synthesis_runner is not None and portfolio.claims:
        synthesis = synthesize(portfolio, synthesis_runner, lang=lang)
    return BuildResult(portfolio=portfolio, grounding=grounding, synthesis=synthesis)


def resolve_to_build_result(
    resolved,  # ResolvedSource — imported locally to avoid circular import
    subject: str,
    runner: Runner,
    max_claims: int = 12,
    *,
    synthesis_runner: Runner | None = None,
    lang: str = "en",
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
            result_synthesis = synthesize(portfolio, synthesis_runner, lang=lang)
        return BuildResult(portfolio=portfolio, grounding=grounding, synthesis=result_synthesis)
    evidence = resolved.extract()
    return build_from_evidence(
        subject=subject,
        evidence=evidence,
        runner=runner,
        max_claims=max_claims,
        synthesis_runner=synthesis_runner,
        lang=lang,
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
    lang: str = "en",
) -> tuple[BuildResult, int]:
    """Returns (BuildResult, n_masked). n_masked is 0 when mask_private=False.

    When mask_private=True, orders work as:
    extract → assert_maskable → discover → visibility → mask evidence → narrate →
    ground → synthesize (post-scrub). Both the guard AND the relabeling run before
    any model call (runner or synthesis_runner), so a private repo's raw evidence
    (github.com or GHES) is never sent to the model (IR-001).
    """
    if not mask_private:
        result = resolve_to_build_result(
            resolved,
            subject=subject,
            runner=runner,
            max_claims=max_claims,
            synthesis_runner=synthesis_runner,
            lang=lang,
        )
        return result, 0

    # Import masking functions here to avoid circular imports
    from .mask import (
        _build_relabel_map,
        _gh_visibility_lookup,
        _rewrite_text,
        assert_maskable,
        extract_repo_names,
        mask_portfolio,
        private_repos,
    )

    # IR-001 invariant: BOTH assert_maskable AND the actual relabeling run BEFORE
    # any narrate/synthesis model call, so a private repo's raw evidence (github.com
    # OR GHES) is never placed in a model prompt. assert_maskable only fails closed
    # on a malformed identity — it does not relabel — so masking the evidence ahead
    # of narrate is what actually keeps raw private names out of the prompt.
    lk = visibility_lookup if visibility_lookup is not None else _gh_visibility_lookup
    _prebuilt = getattr(resolved, "prebuilt", None)

    if _prebuilt is not None:
        # Prebuilt 'portfolio' source: the build is deterministic (check_claims, no
        # narrate runner), so no model call ever sees the evidence. Guard, build,
        # then mask the whole portfolio (evidence + claims).
        assert_maskable(Portfolio(subject=subject, evidence=list(_prebuilt.evidence), claims=[]))
        no_synth_result = resolve_to_build_result(
            resolved,
            subject=subject,
            runner=runner,
            max_claims=max_claims,
            synthesis_runner=None,
            lang=lang,
        )
        repos = extract_repo_names(no_synth_result.portfolio)
        priv = private_repos(repos, visibility_lookup=lk)
        relabel = _build_relabel_map(priv)
        masked_portfolio = mask_portfolio(no_synth_result.portfolio, priv)
    else:
        # Live extraction → the narrate runner WILL receive the evidence, so the
        # evidence must be masked BEFORE build_from_evidence. Discover + relabel on
        # the raw evidence, mask it, then narrate over the masked evidence; the
        # grounded claims therefore reference only the masked identities.
        _pre_evidence = resolved.extract()
        _guard = Portfolio(subject=subject, evidence=_pre_evidence, claims=[])
        assert_maskable(_guard)
        repos = extract_repo_names(_guard)
        priv = private_repos(repos, visibility_lookup=lk)
        relabel = _build_relabel_map(priv)
        masked_evidence = mask_portfolio(_guard, priv).evidence
        no_synth_result = build_from_evidence(
            subject=subject,
            evidence=masked_evidence,
            runner=runner,
            max_claims=max_claims,
            synthesis_runner=None,
            lang=lang,
        )
        # Defense in depth: the narrate model saw only masked evidence, but re-apply
        # masking to the narrated portfolio so any private name the model emitted on
        # its own (claim text/refs) is scrubbed too. Evidence is already masked, so
        # this is idempotent for it; the post-narrate pass only touches the claims.
        masked_portfolio = mask_portfolio(no_synth_result.portfolio, priv)

    # Run synthesis on the masked portfolio (if requested)
    synthesis: SynthesisResult | None = None
    if synthesis_runner is not None and masked_portfolio.claims:
        raw_synthesis = synthesize(masked_portfolio, synthesis_runner, lang=lang)
        # Post-synthesis scrub: replace any private owner/repo the model emitted in
        # text/refs, using the collision-safe (longest-first) rewrite so `org/repo`
        # never partially masks `org/repo-tools` (IR-002).
        if relabel and raw_synthesis is not None:
            new_headline = (
                _rewrite_text(raw_synthesis.headline, relabel) if raw_synthesis.headline is not None else None
            )
            new_headline_refs = [_rewrite_text(r, relabel) for r in raw_synthesis.headline_refs]
            new_highlights = [
                HighlightBullet(
                    text=_rewrite_text(hl.text, relabel),
                    evidence_refs=[_rewrite_text(r, relabel) for r in hl.evidence_refs],
                )
                for hl in raw_synthesis.highlights
            ]
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
            relabel=relabel,
        ),
        len(priv),
    )
