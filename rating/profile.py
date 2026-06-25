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
    # Additional common languages (codex IR-006 — stop dropping real work to "other").
    # Extension-precedence only (no content detection): ambiguous extensions are
    # pinned to their most common language — `.m`→Objective-C (not MATLAB),
    # `.fs`→F# (not Forth), `.pl`→Perl (not Prolog), `.ml`→OCaml (not Standard ML).
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".m": "Objective-C",
    ".mm": "Objective-C",
    ".fs": "F#",
    ".fsx": "F#",
    ".sol": "Solidity",
    ".zig": "Zig",
    ".jl": "Julia",
    ".pl": "Perl",
    ".pm": "Perl",
    ".groovy": "Groovy",
    ".erl": "Erlang",
    ".nim": "Nim",
    ".ml": "OCaml",
    ".mli": "OCaml",
    ".elm": "Elm",
    ".cr": "Crystal",
    # C/C++ headers: mapped for display only; EXCLUDED from the diversity count
    # via _HEADER_EXTS (a header follows its companion C/C++ source).
    ".hpp": "C++",
    ".hh": "C++",
    ".hxx": "C++",
}

# Public alias — callers outside this module should use EXT_TO_LANG.
# The underscore name is retained so existing imports keep working.
EXT_TO_LANG = _EXT_TO_LANG

# Languages that are configuration, data, markup, or documentation rather than
# programming work. These are EXCLUDED from the stack-diversity metric: a
# README (.md), CI/manifest config (.yaml/.yml/.json), and web markup/styling
# (.html/.css) appear in nearly every repository regardless of the developer's
# actual coding range, so counting them as distinct "languages" inflates
# diversity for free (a `.py + .yaml + .json + .md` repo would otherwise score
# as a 4-language polyglot). They still resolve via EXT_TO_LANG for display and
# `language_for_ref`; only the diversity COUNT ignores them.
_NON_CODE_LANGS: frozenset[str] = frozenset({"YAML", "JSON", "Markdown", "HTML", "CSS"})

# Header extensions resolve to a display language (C / C++) but are EXCLUDED from
# the stack-diversity COUNT: a header follows whatever C/C++ source sits beside it,
# so `.cpp` + `.h` is C++ (one language), not C + C++ (codex IR-006). `.h` stays
# mapped to C in _EXT_TO_LANG for `language_for_ref` display.
_HEADER_EXTS: frozenset[str] = frozenset({".h", ".hpp", ".hh", ".hxx"})


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

# Change scale: median code lines changed per PR (additions + deletions, code
# files only — config/data/markup/docs and generated/vendored files are excluded
# upstream by the extractor). Reflects typical change size, not raw volume.
_SCALE_BANDS: list[tuple[str, int, int]] = [
    ("Large", 150, 2),  # median 150+ changed lines/PR → 2 pts
    ("Medium", 30, 1),  # 30–149 → 1 pt
    ("Small", 0, 0),  # 0–29 → 0 pts
]


def _median(values: list[int]) -> int:
    """Median of a list of ints, rounded down to an int (0 for an empty list).
    Pure; used for the change-scale metric."""
    if not values:
        return 0
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) // 2


# --- Capability score (0–100) → grade -----------------------------------------
# The grade is the GRADE_BANDS interval the score falls in (score is primary; the
# letter is derived). Each metric is mapped through a piecewise curve toward
# absolute, product-defined anchors (a = entry, b = strong, c = exceptional),
# weighted, and mapped to 0–100. Designed and validated on real portfolios so that
# STRONG developers spread out across the range (the prior design pinned them all
# near one number) while S stays rare. Criterion-referenced: anchors are absolute
# "this much grounded work" judgments, never a population/percentile.
#   (dimension, a, b, c, weight)
_CAPABILITY_CURVES: tuple[tuple[str, int, int, int, float], ...] = (
    ("volume", 100, 300, 800, 0.35),
    ("breadth", 400, 1200, 3000, 0.30),
    ("scale", 10, 80, 220, 0.25),
    ("stack_diversity", 2, 5, 8, 0.10),
)


def _curve(value: int, a: int, b: int, c: int) -> float:
    """Piecewise map of a raw metric to [0, 1]. Concave below the entry anchor `a`
    (so small-but-real work registers), near-linear `a→b`, slow `b→c`, flat at 1.0
    beyond `c`. Unlike a log curve it keeps LARGE values separated, which is what
    lets strong developers differ instead of all pinning at the top."""
    if value <= 0:
        return 0.0
    if value < a:
        return 0.55 * (value / a) ** 0.40
    if value < b:
        return 0.55 + 0.40 * (value - a) / (b - a)
    if value < c:
        return 0.95 + 0.05 * (value - b) / (c - b)
    return 1.0


def _substance_cap(scale: int) -> float:
    """Trivial typical change size caps the score (continuous, no cliff): a body of
    work whose median PR is tiny (config-only / rubber-stamp / bot) cannot reach a
    top grade on raw volume + breadth alone. Fully released (no cap) at median ≥ 10
    code lines/PR; floors at 40 for a median of 0."""
    return 40.0 + 60.0 * min(1.0, scale / 10.0)


def _meets_s_guard(volume: int, breadth: int, scale: int, diversity: int) -> bool:
    """S is reachable ONLY for a genuinely exceptional, all-around-substantial body
    of work — never high volume/breadth alone (that would re-saturate the top, the
    original '98 for everyone' bug). Requires substance on every axis plus one
    axis well beyond the strong-developer envelope."""
    return (
        volume >= 250
        and breadth >= 900
        and diversity >= 4
        and scale >= 40
        and (volume >= 400 or breadth >= 1600 or scale >= 120)
    )


_NON_S_CAP = 95.0  # non-exceptional work tops out at the A-band max; only the S guard lifts above it


def _capability_score(metrics: dict[str, int]) -> float:
    """Deterministic capability score in [0, 100] (one decimal) from the metric
    values. Pure function — the model never picks it, so it cannot cluster."""
    q = sum(weight * _curve(metrics[key], a, b, c) for key, a, b, c, weight in _CAPABILITY_CURVES)
    base = (85.0 / 0.55) * q if q < 0.55 else 85.0 + 11.0 * (q - 0.55) / 0.40
    base = min(100.0, max(0.0, min(base, _substance_cap(metrics["scale"]))))
    # S is reachable ONLY when the S guard is met; otherwise the score is capped at
    # the A-band max so a non-exceptional body of work can never reach S.
    if not _meets_s_guard(metrics["volume"], metrics["breadth"], metrics["scale"], metrics["stack_diversity"]):
        base = min(base, _NON_S_CAP)
    return round(base, 1)


def _grade_for_score(score: float) -> str:
    """The letter grade is the GRADE_BANDS interval the score falls in (highest
    band whose minimum the score meets)."""
    for g in ("S", "A", "B", "C", "D"):
        if score >= GRADE_BANDS[g][0]:
            return g
    return "D"


# Sub-tier suffixes within a grade, ordered bottom → top. The deterministic
# score's position inside its band selects one: bottom third → "-", middle → ""
# (flat), top third → "+". Refines the letter grade WITHOUT changing it — a "B+"
# sits above a "B-", but both are grade B. The grade letter is the authoritative
# tier; the suffix just shows where in the band the developer falls.
_SUB_TIER_SYMBOLS: tuple[str, str, str] = ("-", "", "+")


def _sub_tier(score: float, score_min: int, score_max: int) -> str:
    """Sub-tier suffix ("+", "" or "-") from the score's position within its band:
    top third → "+", middle → "" (flat), bottom → "-". A zero-width band (not
    produced by the real rubric) maps to flat."""
    span = score_max - score_min
    if span <= 0:
        return ""
    fraction = (score - score_min) / span
    index = min(2, max(0, int(fraction * 3)))
    return _SUB_TIER_SYMBOLS[index]


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
    band: str  # qualitative tier for display, e.g. "Low"/"Steady"/"High"
    evidence_refs: list[str] = field(default_factory=list)


@dataclass
class ProfileResult:
    dimensions: dict[str, DimensionResult]  # "volume", "breadth", "stack_diversity", "scale"
    grade: str  # S / A / B / C / D — derived from `score` (its GRADE_BANDS interval)
    score_min: int  # the grade band's min (for display + sub-tier position)
    score_max: int  # the grade band's max
    # Deterministic capability score in [0, 100] (one decimal), computed from the
    # dimension metrics; the grade is the GRADE_BANDS interval this score falls in.
    # Default 0 so hand-built instances in tests stay valid.
    score: float = 0.0
    # Sub-tier suffix within the grade ("+", "" flat, or "-") from the score's
    # band position; "" for hand-built instances that don't compute it (renders
    # as the bare letter, indistinguishable from a flat mid-band tier).
    sub_tier: str = ""


def profile(portfolio: Portfolio) -> ProfileResult:
    """Pure deterministic profiler over a grounded Portfolio.

    Returns metrics (volume, breadth, stack_diversity, scale), a per-dimension
    display band, a deterministic capability score ∈ [0,100], the overall grade
    ∈ {S,A,B,C,D} (the GRADE_BANDS interval that score falls in), the (min,max) of
    that band, and a sub-tier suffix (+/flat/-).

    Makes NO subprocess, open, or network call — stdlib only.
    Unknown file extensions map to the literal string "other" (never guessed by a model).
    Recency is NOT computed (Evidence carries no date field).
    """
    # --- Volume: count of Evidence(kind="pr") ---
    pr_refs = [e.ref for e in portfolio.evidence if e.kind == "pr"]
    volume_count = len(pr_refs)
    vol_band, _ = _band_for(volume_count, _VOLUME_BANDS)

    # --- Breadth: count of DISTINCT Evidence(kind="file") refs ---
    file_refs_set = {e.ref for e in portfolio.evidence if e.kind == "file"}
    file_refs = sorted(file_refs_set)  # sorted for determinism
    breadth_count = len(file_refs)
    brd_band, _ = _band_for(breadth_count, _BREADTH_BANDS)

    # --- Stack diversity: distinct PROGRAMMING languages via the FIXED table ---
    # Two exclusions so the count reflects real coding range, not file spread:
    #   1. Config/data/markup/documentation languages (_NON_CODE_LANGS).
    #   2. Unmapped extensions — `.toml`/`.ini`/`Dockerfile`/`.lock`/etc. (and any
    #      truly-unknown extension) all collapse to the literal "other"; counting
    #      that single catch-all as a "language" let config/junk files inflate
    #      diversity for free. We do NOT credit what we cannot name.
    # code_file_refs are the refs that actually contributed a counted language.
    langs: set[str] = set()
    code_file_refs: list[str] = []
    for ref in file_refs:
        ext = _file_ext(ref)
        if ext in _HEADER_EXTS:
            continue  # headers follow their companion C/C++ source; not an independent language
        lang = _EXT_TO_LANG.get(ext)  # None for an unmapped extension (was "other")
        if lang is None or lang in _NON_CODE_LANGS:
            continue
        langs.add(lang)
        code_file_refs.append(ref)
    diversity_count = len(langs)
    div_band, _ = _band_for(diversity_count, _DIVERSITY_BANDS)

    # --- Change scale: median (additions + deletions) over the PR evidence ---
    pr_evidence = [e for e in portfolio.evidence if e.kind == "pr"]
    scale_value = _median([e.additions + e.deletions for e in pr_evidence])
    scl_band, _ = _band_for(scale_value, _SCALE_BANDS)

    # --- Capability score → grade (score is primary; the letter is its band) ---
    metrics = {
        "volume": volume_count,
        "breadth": breadth_count,
        "scale": scale_value,
        "stack_diversity": diversity_count,
    }
    score = _capability_score(metrics)
    grade = _grade_for_score(score)
    score_min, score_max = GRADE_BANDS[grade]
    # GRADE_BANDS has integer maxima with one-unit gaps between bands (…54|55…,
    # 69|70, 84|85, 95|96); a one-decimal score can land in a gap (e.g. 69.3 → grade
    # C, but C's max is 69). Clamp to the derived grade's band max so the score
    # never exceeds the band shown for its grade. Grade is unaffected (clamping
    # toward the band min keeps it in the same band).
    score = round(min(score, float(score_max)), 1)

    dimensions: dict[str, DimensionResult] = {
        "volume": DimensionResult(name="volume", value=volume_count, band=vol_band, evidence_refs=pr_refs),
        "breadth": DimensionResult(name="breadth", value=breadth_count, band=brd_band, evidence_refs=file_refs),
        "stack_diversity": DimensionResult(
            name="stack_diversity",
            value=diversity_count,
            band=div_band,
            evidence_refs=code_file_refs,  # only refs that contributed a counted (code) language
        ),
        "scale": DimensionResult(
            name="scale",
            value=scale_value,
            band=scl_band,
            evidence_refs=pr_refs,  # the PRs whose change sizes the median was taken over
        ),
    }

    sub_tier = _sub_tier(score, score_min, score_max)

    return ProfileResult(
        dimensions=dimensions,
        grade=grade,
        score_min=score_min,
        score_max=score_max,
        score=score,
        sub_tier=sub_tier,
    )


# Dimension key → its band table, for the gap-to-next-band analysis.
_DIMENSION_BANDS: dict[str, list[tuple[str, int, int]]] = {
    "volume": _VOLUME_BANDS,
    "breadth": _BREADTH_BANDS,
    "stack_diversity": _DIVERSITY_BANDS,
    "scale": _SCALE_BANDS,
}


@dataclass
class ImprovementHint:
    """Deterministic gap-to-next-band for one dimension: where it stands and what
    would raise it. `at_top` means the dimension is already in its highest band
    (no action); otherwise `next_band`/`threshold`/`delta` describe the cheapest
    move that earns the next point. Pure rubric arithmetic — no model, no
    population comparison."""

    dimension: str  # dimension key (e.g. "scale")
    value: int  # current raw metric value
    current_band: str  # current band label
    at_top: bool  # already in the highest band?
    next_band: str  # next band label up ("" if at_top)
    threshold: int  # raw value needed to reach next_band (0 if at_top)
    delta: int  # threshold - value, i.e. how much more is needed (0 if at_top)


def improvement_hints(profile_result: ProfileResult) -> list[ImprovementHint]:
    """For each present dimension, the gap to the next band (deterministic, pure).

    Iterates the dimensions actually present on `profile_result` (robust to a
    partial result), mapping each to its band table. A dimension already at its
    top band is returned with `at_top=True` and no delta. Compares only against
    the fixed rubric thresholds — never against other people."""
    hints: list[ImprovementHint] = []
    for key, dim in profile_result.dimensions.items():
        bands = _DIMENSION_BANDS.get(key)
        if bands is None:
            continue
        ascending = sorted(bands, key=lambda b: b[1])  # low → high threshold
        top_threshold = ascending[-1][1]
        if dim.value >= top_threshold:
            hints.append(ImprovementHint(key, dim.value, dim.band, True, "", 0, 0))
            continue
        nxt = next(b for b in ascending if b[1] > dim.value)  # lowest band above current value
        hints.append(ImprovementHint(key, dim.value, dim.band, False, nxt[0], nxt[1], nxt[1] - dim.value))
    return hints
