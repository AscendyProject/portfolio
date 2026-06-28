from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.model import Evidence, Portfolio
from rating.grade import grade
from rating.profile import profile


def test_rating_output_gate_banned_terms():
    # Setup portfolio with valid refs
    portfolio = Portfolio(
        subject="test",
        evidence=[
            Evidence(kind="pr", ref="PR1", additions=10, deletions=5),
            Evidence(kind="file", ref="f1.py"),
        ],
        claims=[],
    )
    profile_result = profile(portfolio)

    # Test cases:
    # 1. Banned term + valid ref is dropped
    # 2. Case-insensitive matching drops banned terms (e.g. "Percentile", "GLOBALLY")
    # 3. Clean grounded bullet is kept
    # 4. If all are dropped, fallback to safe reasoning is used

    raw_response = json.dumps(
        {
            "reasoning": [
                {"text": "Clean bullet that should be kept", "evidence_refs": ["PR1"]},
                {"text": "Banned percentile claim here", "evidence_refs": ["PR1"]},
                {"text": "Another banned Percentile claim", "evidence_refs": ["PR1"]},
                {"text": "Globally ranked top developer", "evidence_refs": ["PR1"]},
            ]
        }
    )

    def mock_grader(prompt: str, temperature: float = 0) -> str:
        return raw_response

    result = grade(portfolio, profile_result, mock_grader)

    # Clean bullet must be kept, others must be dropped
    assert len(result.reasoning) == 1
    assert result.reasoning[0]["text"] == "Clean bullet that should be kept"
    assert result.reasoning[0]["evidence_refs"] == ["PR1"]

    # Score and Grade must remain identical to profile_result
    assert result.score == profile_result.score
    assert result.grade == profile_result.grade


def test_rating_output_gate_all_dropped_fallback():
    portfolio = Portfolio(
        subject="test",
        evidence=[
            Evidence(kind="pr", ref="PR1", additions=10, deletions=5),
        ],
        claims=[],
    )
    profile_result = profile(portfolio)

    raw_response = json.dumps(
        {
            "reasoning": [
                {"text": "Banned percentile claim", "evidence_refs": ["PR1"]},
                {"text": "Un-grounded ref", "evidence_refs": ["PR999"]},
            ]
        }
    )

    def mock_grader(prompt: str, temperature: float = 0) -> str:
        return raw_response

    result = grade(portfolio, profile_result, mock_grader)

    # All bullets dropped -> fallback to safe reasoning
    assert len(result.reasoning) == 1
    assert result.reasoning[0]["text"] == "Assessment based on grounded evidence."
    assert result.reasoning[0]["evidence_refs"] == []
    assert result.score == profile_result.score
    assert result.grade == profile_result.grade
