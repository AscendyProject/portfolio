"""Criterion-referenced regression tests — lock the #48 calibration spike exit-(a)
("the bars discriminate sanely") as permanent machine-verifiable regression guards,
and verify criterion-referenced framing in code, README, and CHANGELOG.

All fixtures are built from explicit metric facts using Evidence(...) and Portfolio(...).
No live gh, no network, no model call, no subprocess.

Each test docstring quotes the Done-when item it traces to.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.model import Evidence, Portfolio  # noqa: E402
from rating.profile import GRADE_BANDS, profile  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Fixture builder helpers
# ---------------------------------------------------------------------------

# Fixed code extensions indexed 0..7 — used to assign distinct code languages.
_CODE_EXTS = [".py", ".js", ".go", ".rs", ".rb", ".kt", ".java", ".ts"]
# A non-code extension (YAML ∈ _NON_CODE_LANGS) — gives file breadth without diversity.
_NON_CODE_EXT = ".yaml"


def _portfolio(volume: int, breadth: int, scale: int, diversity: int) -> Portfolio:
    """Build a Portfolio whose profiler metrics equal exactly the given values.

    - volume: number of Evidence(kind="pr") items
    - breadth: number of distinct Evidence(kind="file") refs
    - scale: additions per PR (deletions=0) so median(additions+deletions)==scale
      for any volume>=1; 0 when volume==0 (empty median)
    - diversity: number of distinct code programming languages; achieved by cycling
      _CODE_EXTS[:diversity]; when diversity==0 all file refs use _NON_CODE_EXT
      (YAML is in _NON_CODE_LANGS and excluded from the diversity count).
      Requires breadth >= diversity for all languages to appear in the file set.
    """
    prs = [Evidence(kind="pr", ref=f"PR{i}", additions=scale, deletions=0) for i in range(volume)]
    files = [
        Evidence(kind="file", ref=f"f{j}{_CODE_EXTS[j % diversity] if diversity > 0 else _NON_CODE_EXT}")
        for j in range(breadth)
    ]
    return Portfolio(subject="test", evidence=prs + files, claims=[])


# ---------------------------------------------------------------------------
# Part A — criterion-referenced regression guards (Done-when items 3–5)
# ---------------------------------------------------------------------------


def test_monotonicity():
    """Done-when item 3 — monotonicity: on multiple distinct fixed baselines, increasing
    exactly one of {volume, breadth, scale, stack_diversity} along an ascending sweep —
    with the other three held constant by explicit metric-fact construction — produces a
    non-decreasing sequence of profile(...).score values on every axis.

    Two baselines used per axis sweep.
    Verified by: python -m pytest tests/test_rating_calibration.py -k monoton
    """
    vol_sweep = [5, 20, 50, 100, 250, 500]
    brd_sweep = [10, 100, 400, 900, 1500, 2500]
    scl_sweep = [0, 10, 30, 80, 150, 220]
    div_sweep = [0, 1, 2, 3, 4, 6]

    # Two distinct fixed baselines: (volume_base, breadth_base, scale_base, diversity_base)
    baselines = [
        (30, 200, 40, 2),  # low-medium
        (100, 600, 80, 3),  # medium-high
    ]

    for vol_b, brd_b, scl_b, div_b in baselines:
        # volume axis: breadth/scale/diversity held at baseline
        scores = [profile(_portfolio(v, brd_b, scl_b, div_b)).score for v in vol_sweep]
        for i in range(len(scores) - 1):
            assert scores[i] <= scores[i + 1], (
                f"volume monotonicity failed at baseline {(vol_b, brd_b, scl_b, div_b)}: "
                f"vol {vol_sweep[i]}→{vol_sweep[i + 1]}, score {scores[i]}→{scores[i + 1]}"
            )

        # breadth axis: volume/scale/diversity held at baseline
        scores = [profile(_portfolio(vol_b, b, scl_b, div_b)).score for b in brd_sweep]
        for i in range(len(scores) - 1):
            assert scores[i] <= scores[i + 1], (
                f"breadth monotonicity failed at baseline {(vol_b, brd_b, scl_b, div_b)}: "
                f"brd {brd_sweep[i]}→{brd_sweep[i + 1]}, score {scores[i]}→{scores[i + 1]}"
            )

        # scale axis: volume/breadth/diversity held at baseline
        scores = [profile(_portfolio(vol_b, brd_b, s, div_b)).score for s in scl_sweep]
        for i in range(len(scores) - 1):
            assert scores[i] <= scores[i + 1], (
                f"scale monotonicity failed at baseline {(vol_b, brd_b, scl_b, div_b)}: "
                f"scl {scl_sweep[i]}→{scl_sweep[i + 1]}, score {scores[i]}→{scores[i + 1]}"
            )

        # stack_diversity axis: volume/breadth/scale held at baseline
        scores = [profile(_portfolio(vol_b, brd_b, scl_b, d)).score for d in div_sweep]
        for i in range(len(scores) - 1):
            assert scores[i] <= scores[i + 1], (
                f"stack_diversity monotonicity failed at baseline {(vol_b, brd_b, scl_b, div_b)}: "
                f"div {div_sweep[i]}→{div_sweep[i + 1]}, score {scores[i]}→{scores[i + 1]}"
            )


def test_trivial_floor():
    """Done-when item 4 — trivial floor: an empty portfolio, a portfolio with a single
    PR whose additions+deletions < 30, and a portfolio with five tiny PRs each yield
    grade == "D" and score < GRADE_BANDS["C"][0] (strictly below 55).

    Verified by: python -m pytest tests/test_rating_calibration.py -k trivial
    """
    c_min = GRADE_BANDS["C"][0]  # 55 — strict ceiling for trivial-floor fixtures

    # Empty portfolio (no evidence at all)
    p_empty = Portfolio(subject="empty", evidence=[], claims=[])
    r_empty = profile(p_empty)
    assert r_empty.grade == "D", f"empty portfolio: expected D, got {r_empty.grade}"
    assert r_empty.score < c_min, f"empty portfolio score {r_empty.score} not < {c_min}"

    # Single PR with additions+deletions == 25 (< 30)
    p_one = Portfolio(
        subject="one_tiny",
        evidence=[Evidence(kind="pr", ref="PR1", additions=15, deletions=10)],
        claims=[],
    )
    assert p_one.evidence[0].additions + p_one.evidence[0].deletions < 30  # fixture sanity
    r_one = profile(p_one)
    assert r_one.grade == "D", f"single tiny PR: expected D, got {r_one.grade}"
    assert r_one.score < c_min, f"single tiny PR score {r_one.score} not < {c_min}"

    # Five tiny PRs each with additions+deletions == 10 (< 30)
    p_five = Portfolio(
        subject="five_tiny",
        evidence=[Evidence(kind="pr", ref=f"PR{i}", additions=5, deletions=5) for i in range(5)],
        claims=[],
    )
    for e in p_five.evidence:
        assert e.additions + e.deletions < 30  # fixture sanity
    r_five = profile(p_five)
    assert r_five.grade == "D", f"five tiny PRs: expected D, got {r_five.grade}"
    assert r_five.score < c_min, f"five tiny PRs score {r_five.score} not < {c_min}"


def test_top_reachable():
    """Done-when item 5 — top reachable: a fixture explicitly meeting every top-band
    criterion (high volume, high breadth, median additions+deletions at or above the
    _CAPABILITY_CURVES scale b-anchor (80), >= 4 distinct code languages, and
    satisfying every clause of _meets_s_guard) reaches grade == "S".

    _meets_s_guard requires: volume>=250, breadth>=900, diversity>=4, scale>=40,
    plus one stretch axis: volume>=400 OR breadth>=1600 OR scale>=120.
    This fixture uses volume=500, breadth=2000, scale=150, diversity=5 — all
    guards and the stretch axis are satisfied simultaneously.

    Verified by: python -m pytest tests/test_rating_calibration.py -k top_reachable
    """
    # volume=500 (≥400 stretch), breadth=2000 (≥1600 stretch), scale=150 (≥120 stretch),
    # diversity=5 (≥4); satisfies every _meets_s_guard clause.
    p = _portfolio(volume=500, breadth=2000, scale=150, diversity=5)
    r = profile(p)
    assert r.grade == "S", (
        f"top-reachable fixture: expected grade S, got {r.grade} (score={r.score}). "
        "Verify the fixture meets all _meets_s_guard clauses."
    )


def test_no_collapse_discriminates_grades():
    """Done-when item 5 (no-collapse) — a small set of clearly-distinct metric-fact
    fixtures yields at least 3 distinct grade values. This is a signal-discrimination
    guard: asserted as a set-cardinality check on {profile(p).grade for p in fixtures},
    not as a distributional or "spreads nicely" claim.

    Fixture set: 5 portfolios with clearly-distinct metric facts, expected to cover
    at least 3 of {D, C, B, A, S}.

    Verified by: python -m pytest tests/test_rating_calibration.py -k discriminat
    """
    fixtures = [
        Portfolio(subject="empty", evidence=[], claims=[]),  # → D
        _portfolio(volume=15, breadth=200, scale=40, diversity=2),  # → C
        _portfolio(volume=30, breadth=50, scale=80, diversity=4),  # → B
        _portfolio(volume=200, breadth=1500, scale=100, diversity=4),  # → A
        _portfolio(volume=500, breadth=2000, scale=150, diversity=5),  # → S
    ]
    grades = {profile(p).grade for p in fixtures}
    assert len(grades) >= 3, (
        f"Expected >= 3 distinct grades across {len(fixtures)} distinct-metric-fact fixtures, "
        f"got {len(grades)}: {grades}. The rating must discriminate across clearly-different "
        "evidence bodies — this is a signal-discrimination guard, not a distribution claim."
    )


# ---------------------------------------------------------------------------
# Part B — criterion-referenced framing (Done-when items 6–8)
# ---------------------------------------------------------------------------


def test_profile_framing_comment():
    """Done-when item 6 — rating/profile.py contains a concise comment block with the
    literal phrases 'criterion-referenced' and 'not a percentile', stating these are
    product-defined evidence thresholds carrying no population/ranking/hiring-readiness
    meaning.

    Verified by: python -m pytest tests/test_rating_calibration.py -k profile_framing_comment
    """
    content = (_REPO_ROOT / "rating" / "profile.py").read_text(encoding="utf-8")
    lower = content.lower()
    assert "criterion-referenced" in lower, "rating/profile.py must contain the phrase 'criterion-referenced'"
    assert "not a percentile" in lower, "rating/profile.py must contain the phrase 'not a percentile'"


def test_readme_framing():
    """Done-when item 7 — the ### /rating command section of README.md contains a short
    note with the literal phrases 'criterion-referenced' and 'not a percentile', stating
    the rating is absolute/product-chosen and not a population comparison/ranking/
    hiring-readiness claim.

    Verified by: python -m pytest tests/test_rating_calibration.py -k readme_framing
    """
    content = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
    # Locate the /rating command section header
    rating_start = content.find("### `/rating`")
    assert rating_start != -1, "'### `/rating`' section header not found in README.md"
    # Extract until the next top-level or same-level section header
    next_section = content.find("\n## ", rating_start)
    rating_section = content[rating_start:] if next_section == -1 else content[rating_start:next_section]
    lower = rating_section.lower()
    assert "criterion-referenced" in lower, "README.md /rating section must contain 'criterion-referenced'"
    assert "not a percentile" in lower, "README.md /rating section must contain 'not a percentile'"


def test_changelog_entry():
    """Done-when item 8 — CHANGELOG.md [Unreleased] section gains a bullet naming #48,
    the exit-(a) calibration-spike conclusion, and the new criterion-referenced regression
    guards. The literal token '#48' and at least one of 'criterion-referenced' /
    'calibration' / 'regression' appear inside the [Unreleased] block.

    Verified by: python -m pytest tests/test_rating_calibration.py -k changelog_entry
    """
    content = (_REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased_start = content.find("## [Unreleased]")
    assert unreleased_start != -1, "## [Unreleased] block not found in CHANGELOG.md"
    next_version = content.find("\n## [", unreleased_start + len("## [Unreleased]"))
    block = content[unreleased_start:] if next_version == -1 else content[unreleased_start:next_version]
    assert "#48" in block, "#48 not found in the [Unreleased] block of CHANGELOG.md"
    lower_block = block.lower()
    assert any(phrase in lower_block for phrase in ("criterion-referenced", "calibration", "regression")), (
        "CHANGELOG.md [Unreleased] block must contain at least one of: "
        "'criterion-referenced', 'calibration', 'regression'"
    )
