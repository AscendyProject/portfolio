"""JD-aware deterministic selection of grounded portfolio claims into a resume draft.

Stdlib-only: no model calls, no network, no subprocess, no file I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from portfolio.model import Claim, Evidence, Portfolio

# ── Stopwords ─────────────────────────────────────────────────────────────────
# Small, pinned set. Tests import this constant directly to verify coverage.
STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "can",
        "did",
        "do",
        "for",
        "from",
        "had",
        "has",
        "have",
        "i",
        "in",
        "is",
        "it",
        "its",
        "not",
        "of",
        "on",
        "or",
        "our",
        "that",
        "the",
        "this",
        "to",
        "was",
        "we",
        "were",
        "will",
        "with",
    }
)


# ── Tokenizer ─────────────────────────────────────────────────────────────────
def jd_keywords(jd_text: str) -> set[str]:
    """Tokenize a plain-text job description into a normalised keyword set.

    Tokenization rule: split on any character that is not a Unicode letter
    (unicodedata.category L*) and not a Unicode digit (category N*).
    Uses re.findall(r"[^\\W_]+", text, re.UNICODE) which matches Unicode word
    chars minus underscores (i.e. letters and digits only). Lowercases via
    str.lower() (Latin letters are case-folded; Korean is caseless and passes
    through unchanged). Drops tokens in STOPWORDS; drops empty tokens.

    Behaviour on pure-ASCII English input is byte-identical to the prior
    implementation (re.split(r"[^a-z0-9]+", text.lower())).
    """
    tokens = re.findall(r"[^\W_]+", jd_text, re.UNICODE)
    return {t.lower() for t in tokens if t.lower() not in STOPWORDS}


def _claim_tokens(claim: Claim) -> set[str]:
    """Derive tokens from a claim's text + evidence_refs using the same rule as jd_keywords."""
    combined = claim.text + " " + " ".join(claim.evidence_refs)
    return jd_keywords(combined)


# ── Dataclasses ───────────────────────────────────────────────────────────────
@dataclass
class ScoredClaim:
    """A portfolio Claim paired with its JD-overlap score and matched keywords.

    `claim` is held by reference — its `evidence_refs` are never mutated or stripped.
    """

    claim: Claim
    score: int
    matched_keywords: set[str] = field(default_factory=set)


@dataclass
class ResumeDraft:
    """The output of the resume-selection pass.

    `selected` is ordered highest-score first (ties stable by original portfolio order).
    `jd_keywords_matched` is the union of matched keywords across all surviving selected claims.
    """

    subject: str
    selected: list[ScoredClaim] = field(default_factory=list)
    jd_keywords_matched: set[str] = field(default_factory=set)
    jd_keywords_total: int = 0
    evidence_by_ref: dict[str, Evidence] = field(default_factory=dict)


# ── Selection ─────────────────────────────────────────────────────────────────
def select_claims(portfolio: Portfolio, jd_kw: set[str], top_n: int) -> list[ScoredClaim]:
    """Rank portfolio.claims by integer overlap with jd_kw, highest first.

    Ties broken by original order (stable sort). Claims with score 0 excluded.
    Result capped at top_n. Pure function: no I/O, no mutation of inputs.
    """
    scored: list[ScoredClaim] = []
    for claim in portfolio.claims:
        tokens = _claim_tokens(claim)
        matched = jd_kw & tokens
        score = len(matched)
        if score > 0:
            scored.append(ScoredClaim(claim=claim, score=score, matched_keywords=matched))
    # Python sort is stable: equal scores preserve original insertion order.
    scored.sort(key=lambda sc: sc.score, reverse=True)
    return scored[:top_n]


# ── Honesty re-check ─────────────────────────────────────────────────────────
def enforce_grounding(scored: list[ScoredClaim], portfolio: Portfolio) -> list[ScoredClaim]:
    """Drop any ScoredClaim failing the grounding contract.

    Dropped if:
    - The Claim object is not in portfolio.claims (by object identity).
    - The claim's evidence_refs are empty (a claim citing no evidence is ungrounded).
    - The claim's evidence_refs are not a subset of the portfolio's evidence ref set.
    Fail-closed: a failing claim is silently dropped, never returned.
    """
    real_claim_ids = {id(c) for c in portfolio.claims}
    real_refs = {e.ref for e in portfolio.evidence}
    result: list[ScoredClaim] = []
    for sc in scored:
        if id(sc.claim) not in real_claim_ids:
            continue
        if not sc.claim.evidence_refs:  # empty refs — no evidence cited, reject
            continue
        if not set(sc.claim.evidence_refs) <= real_refs:
            continue
        result.append(sc)
    return result


# ── Public entry point ────────────────────────────────────────────────────────
def build_resume(portfolio: Portfolio, jd_text: str, top_n: int) -> ResumeDraft:
    """Compose jd_keywords → select_claims → enforce_grounding into a ResumeDraft.

    Deterministic: same portfolio + jd_text + top_n always produce identical output.
    Calls no model, no network, no subprocess.
    """
    kw = jd_keywords(jd_text)
    scored = select_claims(portfolio, kw, top_n)
    verified = enforce_grounding(scored, portfolio)
    matched: set[str] = set()
    for sc in verified:
        matched |= sc.matched_keywords
    return ResumeDraft(
        subject=portfolio.subject,
        selected=verified,
        jd_keywords_matched=matched,
        jd_keywords_total=len(kw),
        evidence_by_ref={e.ref: e for e in portfolio.evidence},
    )
