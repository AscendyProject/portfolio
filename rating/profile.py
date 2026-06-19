"""Deterministic profiler: Portfolio → metrics + bands + overall grade + score band.

Pure function — no model, no subprocess, no file I/O.
Same grounded portfolio always yields identical metrics, bands, grade, and score band.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from portfolio.model import Portfolio

# Fixed extension → language table (pinned in code; a model NEVER contributes to this).
# An extension not in this table maps to the literal string "other" — never guessed.
_EXT_TO_LANG: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".jsx": "JavaScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".rb": "Ruby",
    ".cpp": "C++",
    ".cc": "C++",
    ".c": "C",
    ".h": "C",
    ".cs": "C#",
    ".php": "PHP",
    ".swift": "Swift",
    ".scala": "Scala",
    ".sh": "Shell",
    ".bash": "Shell",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".html": "HTML",
    ".css": "CSS",
    ".sql": "SQL",
    ".tf": "Terraform",
    ".md": "Markdown",
    ".r": "R",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".hs": "Haskell",
    ".clj": "Clojure",
    ".lua": "Lua",
    ".dart": "Dart",
}

# Public alias — callers outside this module should use EXT_TO_LANG.
# The underscore name is retained so existing imports keep working.
EXT_TO_LANG = _EXT_TO_LANG


def language_for_ref(ref: str) -> str:
    """Return the language name for a given file ref using the fixed extension table.

    Returns 'other' for refs whose extension is not in the table (e.g. Makefile,
    PR#1, unknown extensions).  Never guesses — a model never contributes here.
    """
    ext = _file_ext(ref)
    return EXT_TO_LANG.get(ext, "other")


# Grade → score band (fixed rubric, shown in the rendered scorecard).
GRADE_BANDS: dict[str, tuple[int, int]] = {
    "S": (96, 100),
    "A": (85, 95),
    "B": (70, 84),
    "C": (55, 69),
    "D": (0, 54),
}

# Per-dimension bands: (name, minimum_value_inclusive, points).
# Listed from highest to lowest so _band_for() returns the first match.
_VOLUME_BANDS: list[tuple[str, int, int]] = [
    ("High", 20, 2),  # 20+ PRs → 2 pts
    ("Steady", 5, 1),  # 5–19 PRs → 1 pt
    ("Low", 0, 0),  # 0–4 PRs → 0 pts
]

_BREADTH_BANDS: list[tuple[str, int, int]] = [
    ("Wide", 30, 2),  # 30+ distinct file refs → 2 pts
    ("Moderate", 10, 1),  # 10–29 → 1 pt
    ("Narrow", 0, 0),  # 0–9 → 0 pts
]

_DIVERSITY_BANDS: list[tuple[str, int, int]] = [
    ("Polyglot", 4, 2),  # 4+ distinct languages → 2 pts
    ("Versatile", 2, 1),  # 2–3 → 1 pt
    ("Focused", 0, 0),  # 0–1 → 0 pts
]

# Points total → grade (highest threshold first).
_POINTS_TO_GRADE: list[tuple[int, str]] = [
    (6, "S"),
    (4, "A"),
    (2, "B"),
    (1, "C"),
    (0, "D"),
]


def _band_for(value: int, bands: list[tuple[str, int, int]]) -> tuple[str, int]:
    """Return (band_name, points) for `value` against ordered bands (high → low)."""
    for name, threshold, pts in bands:
        if value >= threshold:
            return name, pts
    # Unreachable when bands contains a 0-threshold entry, but kept as safety.
    return bands[-1][0], bands[-1][2]


def _file_ext(ref: str) -> str:
    """Extract the normalised file extension from a ref (e.g. 'app/auth.py' → '.py').

    Returns '' for refs with no dot in the final path segment (e.g. 'Makefile', 'PR#1').
    """
    basename = ref.rsplit("/", 1)[-1]
    if "." not in basename:
        return ""
    return "." + basename.rsplit(".", 1)[-1].lower()


@dataclass
class DimensionResult:
    name: str
    value: int  # raw metric value
    band: str  # e.g. "Low", "Steady", "High"
    points: int  # contribution to grade total
    evidence_refs: list[str] = field(default_factory=list)


@dataclass
class ProfileResult:
    dimensions: dict[str, DimensionResult]  # "volume", "breadth", "stack_diversity"
    grade: str  # S / A / B / C / D
    score_min: int
    score_max: int


def profile(portfolio: Portfolio) -> ProfileResult:
    """Pure deterministic profiler over a grounded Portfolio.

    Returns metrics (volume, breadth, stack_diversity), per-dimension bands,
    overall grade ∈ {S,A,B,C,D}, and a (min,max) score band.

    Makes NO subprocess, open, or network call — stdlib only.
    Unknown file extensions map to the literal string "other" (never guessed by a model).
    Recency is NOT computed (Evidence carries no date field).
    """
    # --- Volume: count of Evidence(kind="pr") ---
    pr_refs = [e.ref for e in portfolio.evidence if e.kind == "pr"]
    volume_count = len(pr_refs)
    vol_band, vol_pts = _band_for(volume_count, _VOLUME_BANDS)

    # --- Breadth: count of DISTINCT Evidence(kind="file") refs ---
    file_refs_set = {e.ref for e in portfolio.evidence if e.kind == "file"}
    file_refs = sorted(file_refs_set)  # sorted for determinism
    breadth_count = len(file_refs)
    brd_band, brd_pts = _band_for(breadth_count, _BREADTH_BANDS)

    # --- Stack diversity: distinct languages via the FIXED extension→language table ---
    langs: set[str] = set()
    for ref in file_refs:
        ext = _file_ext(ref)
        langs.add(_EXT_TO_LANG.get(ext, "other"))
    diversity_count = len(langs)
    div_band, div_pts = _band_for(diversity_count, _DIVERSITY_BANDS)

    # --- Overall grade from total points ---
    total_pts = vol_pts + brd_pts + div_pts
    grade = "D"
    for threshold, g in _POINTS_TO_GRADE:
        if total_pts >= threshold:
            grade = g
            break

    score_min, score_max = GRADE_BANDS[grade]

    dimensions: dict[str, DimensionResult] = {
        "volume": DimensionResult(
            name="volume",
            value=volume_count,
            band=vol_band,
            points=vol_pts,
            evidence_refs=pr_refs,
        ),
        "breadth": DimensionResult(
            name="breadth",
            value=breadth_count,
            band=brd_band,
            points=brd_pts,
            evidence_refs=file_refs,
        ),
        "stack_diversity": DimensionResult(
            name="stack_diversity",
            value=diversity_count,
            band=div_band,
            points=div_pts,
            evidence_refs=file_refs,  # the file refs used to derive language diversity
        ),
    }

    return ProfileResult(
        dimensions=dimensions,
        grade=grade,
        score_min=score_min,
        score_max=score_max,
    )
