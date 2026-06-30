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

# ── JD meta-line patterns (Part A.1) ─────────────────────────────────────────
# Compiled regexes that match whole preamble/header lines to strip before
# tokenizing. Each pattern matches the full line (after strip).
JD_META_LINE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Matches the harness-style preamble:
    #   "Extracted job description for resume/fit keyword matching"
    re.compile(
        r"^extracted\s+job\s+description\s+for\s+resume\s*/\s*fit\s+keyword\s+matching$",
        re.IGNORECASE,
    ),
    # Matches a generic <label>: header line (label only, nothing else on the line)
    re.compile(
        r"^(job\s+description|keywords?|resume|portfolio)\s*:\s*$",
        re.IGNORECASE,
    ),
)

# ── JD meta-token stopwords (Part A.2) ────────────────────────────────────────
# Tokens to drop even when they appear mid-sentence in a requirement line.
# Importable from resume.select.
JD_META_STOPWORDS: frozenset[str] = frozenset(
    {
        "job",
        "description",
        "keywords",
        "keyword",
        "resume",
        "portfolio",
        "fit",
        "com",
        "extracted",
        "matching",
    }
)

# ── Tech synonym / alias table ────────────────────────────────────────────────
# Pinned, high-precision single-token aliases: alias → canonical (both lowercase ASCII).
# Applied after the stopword/len/digit filters and before _stem, so both the JD side
# and the claim side (which routes through jd_keywords) collapse to the same token.
# v1 is single-token only; phrase aliases (e.g. "google cloud" ↔ "gcp") and
# embedding-based semantic matching are explicit non-goals (tracked under issue #37).
# Ambiguous/risky keys (c, r, go, ml, ai) are intentionally omitted.
TECH_ALIASES: dict[str, str] = {
    "k8s": "kubernetes",  # Kubernetes shorthand used widely in ops/infra JDs
    "js": "javascript",  # JavaScript canonical name
    "ts": "typescript",  # TypeScript canonical name
    "py": "python",  # Python script/file shorthand
    "postgres": "postgresql",  # PostgreSQL common alias
    "pg": "postgresql",  # PostgreSQL ultra-short alias
    "golang": "go",  # Go programming language full name
    "ror": "rails",  # Ruby on Rails abbreviation
    "tf": "terraform",  # Terraform IaC tool shorthand
}


# ── Private helpers ───────────────────────────────────────────────────────────


def _alias(token: str) -> str:
    """Return the canonical form of a tech alias; passthrough if not in TECH_ALIASES."""
    return TECH_ALIASES.get(token, token)


def _strip_meta_lines(text: str) -> str:
    """Drop lines matching any JD_META_LINE_PATTERNS; join survivors with newline."""
    survivors = []
    for line in text.splitlines():
        stripped = line.strip()
        if any(pat.match(stripped) for pat in JD_META_LINE_PATTERNS):
            continue
        survivors.append(line)
    return "\n".join(survivors)


def _stem(token: str) -> str:
    """Deterministic ASCII suffix stemmer.

    Non-ASCII tokens (e.g. Korean Hangul) are returned unchanged.
    Only handles the specific suffix pairs named in the brief.
    Pure, stdlib-only, no third-party dependencies.
    """
    # Pass through non-ASCII tokens unchanged
    if not token.isascii():
        return token

    t = token.lower()

    # Ordered from longest to shortest suffix to avoid over-stripping.
    # -ing → base (deploying → deploy, orchestrating → orchestrat)
    if t.endswith("ing"):
        stem = t[:-3]
        if len(stem) >= 3:
            return stem
        return t

    # -ed → base (deployed → deploy, orchestrated → orchestrat)
    if t.endswith("ed"):
        stem = t[:-2]
        if len(stem) >= 3:
            return stem
        return t

    # -ate → base (orchestrate → orchestrat)
    # Strip trailing 'e' from '-ate' endings so that "orchestrate" / "orchestrated"
    # / "orchestrating" all collapse to the same stem.
    if t.endswith("ate"):
        stem = t[:-1]  # strip the 'e', keep 'at'
        if len(stem) >= 4:
            return stem
        return t

    # -s → base (migrations → migration, containers → container, services → service,
    #             deploys → deploy)
    # Block: words ending in '-tes' are typically loan words / proper nouns (e.g.
    # "kubernetes"), not English plurals — skip the strip to preserve them intact.
    if t.endswith("s") and not t.endswith("ss") and not t.endswith("tes"):
        stem = t[:-1]
        if len(stem) >= 3:
            return stem
        return t

    return t


# ── Tokenizer ─────────────────────────────────────────────────────────────────
def jd_keywords(jd_text: str) -> set[str]:
    """Tokenize a plain-text job description into a normalised keyword set.

    Tokenization rule: split on any character that is not a Unicode letter
    (unicodedata.category L*) and not a Unicode digit (category N*).
    Uses re.findall(r"[^\\W_]+", text, re.UNICODE) which matches Unicode word
    chars minus underscores (i.e. letters and digits only). Lowercases via
    str.lower() (Latin letters are case-folded; Korean is caseless and passes
    through unchanged). Drops tokens in STOPWORDS; drops empty tokens.

    Part A.1: strips meta/preamble lines before tokenizing.
    Part A.2: drops JD_META_STOPWORDS tokens, len<2 tokens, pure-digit tokens.
    Part B: applies _stem to each surviving token.

    Behaviour on pure-ASCII English input is byte-identical to the prior
    implementation (re.split(r"[^a-z0-9]+", text.lower())).
    """
    text = _strip_meta_lines(jd_text)
    tokens = re.findall(r"[^\W_]+", text, re.UNICODE)
    result = set()
    for t in tokens:
        low = t.lower()
        # Drop STOPWORDS
        if low in STOPWORDS:
            continue
        # Drop JD_META_STOPWORDS
        if low in JD_META_STOPWORDS:
            continue
        # Drop len < 2
        if len(low) < 2:
            continue
        # Drop pure-digit tokens
        if low.isdigit():
            continue
        # Apply alias canonicalization (passthrough on miss) then stemming
        result.add(_stem(_alias(low)))
    return result


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
