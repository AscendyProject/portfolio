"""resume — JD-aware deterministic selection of grounded portfolio claims.

Public API re-exported here for convenience.
"""

from .select import (
    STOPWORDS,
    ResumeDraft,
    ScoredClaim,
    build_resume,
    enforce_grounding,
    jd_keywords,
    select_claims,
)

__all__ = [
    "STOPWORDS",
    "ResumeDraft",
    "ScoredClaim",
    "build_resume",
    "enforce_grounding",
    "jd_keywords",
    "select_claims",
]
