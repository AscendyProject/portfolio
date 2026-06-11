"""The grounding gate — the trust boundary of this harness.

A model writes narrative; this checks it. Every Claim must cite at least one
Evidence ref that actually exists in the extracted corpus. A claim citing
nothing, or citing a ref the extractor never produced (a hallucinated PR /
commit / file), is NOT grounded — it must be dropped or sent for human
confirmation, never silently shipped. This is deterministic: it does not ask a
model whether a claim is true, it checks whether the cited evidence is real.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Claim, Evidence


@dataclass(frozen=True)
class GroundingResult:
    grounded: list[Claim]
    rejected: list[Claim]  # cite nothing, or cite a ref not in the evidence set
    needs_confirmation: list[Claim]  # grounded but flagged for a human


def check_claims(claims: list[Claim], evidence: list[Evidence]) -> GroundingResult:
    """Mark each claim grounded iff every ref it cites exists in the evidence set
    AND it cites at least one. Mutates each claim's `grounded` field and partitions
    the claims. Citing a non-existent ref (a hallucination) is a hard reject —
    one bad ref poisons the claim, even if other refs are real."""
    real_refs = {e.ref for e in evidence}
    grounded: list[Claim] = []
    rejected: list[Claim] = []
    needs_confirmation: list[Claim] = []
    for claim in claims:
        refs = claim.evidence_refs
        if not refs or any(r not in real_refs for r in refs):
            claim.grounded = False
            rejected.append(claim)
            continue
        claim.grounded = True
        (needs_confirmation if claim.needs_user_confirmation else grounded).append(claim)
    return GroundingResult(grounded=grounded, rejected=rejected, needs_confirmation=needs_confirmation)
