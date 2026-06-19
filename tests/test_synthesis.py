"""Tests for portfolio/synthesis.py.

Each test traces 1:1 to a Done-when item in outcome.md via its docstring.
No live model, no network — all runner seams are fakes.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.model import Claim, Evidence, Portfolio  # noqa: E402
from portfolio.synthesis import HighlightBullet, SynthesisResult, synthesize  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _portfolio(
    claims: list[Claim] | None = None,
    evidence: list[Evidence] | None = None,
) -> Portfolio:
    ev = evidence or [
        Evidence(kind="pr", ref="PR#1", url="https://github.com/o/r/pull/1"),
        Evidence(kind="file", ref="app/main.py"),
    ]
    cl = claims or [
        Claim(text="Built main feature", evidence_refs=["PR#1", "app/main.py"], confidence=0.9),
    ]
    return Portfolio(subject="alice", evidence=ev, claims=cl)


def _fake_runner_returning(data: dict):
    """Return a runner that always returns the given dict as JSON."""

    def runner(prompt: str) -> str:
        return json.dumps(data)

    return runner


def _grounded_response(
    headline: str = "Great developer",
    headline_refs: list[str] | None = None,
    highlights: list[dict] | None = None,
) -> dict:
    return {
        "headline": headline,
        "headline_refs": headline_refs if headline_refs is not None else ["PR#1"],
        "highlights": highlights
        if highlights is not None
        else [{"text": "Built the main feature", "evidence_refs": ["PR#1"]}],
    }


# ---------------------------------------------------------------------------
# Done-when: signature import test
# ---------------------------------------------------------------------------


def test_highlightbullet_dataclass_fields():
    """HighlightBullet has exactly: text: str, evidence_refs: list[str]."""
    b = HighlightBullet(text="foo", evidence_refs=["PR#1"])
    assert b.text == "foo"
    assert b.evidence_refs == ["PR#1"]


def test_synthesisresult_dataclass_fields():
    """SynthesisResult has: headline: str|None, headline_refs: list[str], highlights: list[HighlightBullet]."""
    r = SynthesisResult(headline="hello", headline_refs=["PR#1"], highlights=[])
    assert r.headline == "hello"
    assert r.headline_refs == ["PR#1"]
    assert r.highlights == []


def test_synthesisresult_headline_none():
    """When headline is None, headline_refs is []."""
    r = SynthesisResult(headline=None, headline_refs=[], highlights=[])
    assert r.headline is None
    assert r.headline_refs == []


def test_synthesize_callable():
    """synthesize is callable with (portfolio, runner) -> SynthesisResult."""
    sig = inspect.signature(synthesize)
    params = list(sig.parameters)
    assert params[0] == "portfolio"
    assert params[1] == "runner"
    assert sig.return_annotation is SynthesisResult or "SynthesisResult" in str(sig.return_annotation)


# ---------------------------------------------------------------------------
# Done-when: prompt content test
# ---------------------------------------------------------------------------


def test_prompt_enumerates_claim_text_and_refs():
    """The prompt enumerates every grounded claim's text and evidence_refs.

    Outcome: 'The prompt enumerates EVERY grounded claim in portfolio.claims with
    its text and each of its evidence_refs.'
    """
    recorded: list[str] = []

    def recording_runner(prompt: str) -> str:
        recorded.append(prompt)
        return json.dumps(_grounded_response())

    portfolio = _portfolio(
        claims=[
            Claim(text="Built auth service", evidence_refs=["PR#1", "app/main.py"], confidence=0.9),
            Claim(text="Fixed cache bug", evidence_refs=["PR#1"], confidence=0.85),
        ],
        evidence=[
            Evidence(kind="pr", ref="PR#1"),
            Evidence(kind="file", ref="app/main.py"),
        ],
    )

    synthesize(portfolio, recording_runner)
    assert len(recorded) == 1
    prompt = recorded[0]

    # Both claim texts must appear in the prompt.
    assert "Built auth service" in prompt
    assert "Fixed cache bug" in prompt

    # Both refs must appear.
    assert "PR#1" in prompt
    assert "app/main.py" in prompt


def test_prompt_excludes_unclaimed_evidence_ref():
    """Refs in evidence that no grounded claim cites do NOT appear in the prompt.

    Outcome: 'asserts a ref cited only by portfolio.evidence (but by no claim) does
    NOT appear in the prompt.'
    """
    recorded: list[str] = []

    def recording_runner(prompt: str) -> str:
        recorded.append(prompt)
        return json.dumps(_grounded_response())

    portfolio = Portfolio(
        subject="alice",
        evidence=[
            Evidence(kind="pr", ref="PR#1"),
            Evidence(kind="pr", ref="PR#99"),  # in evidence but cited by no claim
        ],
        claims=[
            Claim(text="Built thing", evidence_refs=["PR#1"], confidence=0.9),
        ],
    )

    synthesize(portfolio, recording_runner)
    prompt = recorded[0]

    assert "PR#1" in prompt
    # PR#99 is in evidence but no claim cites it — must not appear in the claims enumeration
    # (it may appear in the instruction text, but not as a citable ref).
    # The key constraint: the allowed-refs set is from claims, not evidence.
    # We check that it's not enumerated as a claim ref.
    assert "PR#99" not in prompt


def test_runner_called_exactly_once():
    """synthesize calls runner exactly once.

    Outcome: 'synthesize(portfolio, runner) calls runner(prompt) exactly once.'
    """
    call_count = [0]

    def counting_runner(prompt: str) -> str:
        call_count[0] += 1
        return json.dumps(_grounded_response())

    synthesize(_portfolio(), counting_runner)
    assert call_count[0] == 1


# ---------------------------------------------------------------------------
# Done-when: parser tolerance
# ---------------------------------------------------------------------------


def test_parser_clean_json():
    """Clean JSON response is parsed correctly.

    Outcome: 'parser test with three inputs: clean JSON ...'
    """
    runner = _fake_runner_returning(_grounded_response())
    result = synthesize(_portfolio(), runner)
    assert result.headline == "Great developer"
    assert result.headline_refs == ["PR#1"]
    assert len(result.highlights) == 1


def test_parser_json_inside_code_fences():
    """JSON wrapped in ```json ... ``` fences is parsed correctly.

    Outcome: '... JSON inside ```json fences ...'
    """
    inner = json.dumps(_grounded_response())

    def fenced_runner(prompt: str) -> str:
        return f"```json\n{inner}\n```"

    result = synthesize(_portfolio(), fenced_runner)
    assert result.headline == "Great developer"


def test_parser_total_garbage():
    """Totally unparseable runner output returns empty SynthesisResult.

    Outcome: '... total garbage ... returns SynthesisResult(headline=None, headline_refs=[], highlights=[]).'
    """

    def garbage_runner(prompt: str) -> str:
        return "this is not json at all"

    result = synthesize(_portfolio(), garbage_runner)
    assert result.headline is None
    assert result.headline_refs == []
    assert result.highlights == []


# ---------------------------------------------------------------------------
# Done-when: grounding re-check — allowed refs = claim-refs union
# ---------------------------------------------------------------------------


def test_allowed_refs_is_claim_refs_union_not_full_evidence():
    """headline and highlight citing a ref in evidence but not in any claim are dropped.

    Outcome: 'asserts the headline is dropped to None and the highlight is dropped,
    proving the gate uses the claim-cited subset rather than the full evidence set.'
    """
    portfolio = Portfolio(
        subject="alice",
        evidence=[
            Evidence(kind="pr", ref="PR#1"),
            Evidence(kind="pr", ref="PR#99"),  # in evidence, but no claim cites it
        ],
        claims=[
            Claim(text="Built thing", evidence_refs=["PR#1"], confidence=0.9),
        ],
    )

    def runner(prompt: str) -> str:
        return json.dumps(
            {
                "headline": "Summary citing PR#99",
                "headline_refs": ["PR#99"],  # NOT in allowed_refs (claim-refs union)
                "highlights": [{"text": "PR#99 highlight", "evidence_refs": ["PR#99"]}],
            }
        )

    result = synthesize(portfolio, runner)
    assert result.headline is None
    assert result.headline_refs == []
    assert result.highlights == []


def test_highlight_with_hallucinated_ref_dropped_other_valid_survive():
    """A highlight citing a hallucinated ref is dropped; valid bullets survive.

    Outcome: '(a) emits a highlight citing a hallucinated ref → that bullet only is
    dropped, other valid bullets survive.'
    """
    portfolio = _portfolio(
        claims=[Claim(text="Built thing", evidence_refs=["PR#1"], confidence=0.9)],
        evidence=[Evidence(kind="pr", ref="PR#1")],
    )

    def runner(prompt: str) -> str:
        return json.dumps(
            {
                "headline": "Great developer",
                "headline_refs": ["PR#1"],
                "highlights": [
                    {"text": "Valid bullet", "evidence_refs": ["PR#1"]},
                    {"text": "Hallucinated bullet", "evidence_refs": ["PR#FAKE"]},
                ],
            }
        )

    result = synthesize(portfolio, runner)
    assert len(result.highlights) == 1
    assert result.highlights[0].text == "Valid bullet"


def test_headline_with_hallucinated_ref_sets_headline_none_highlights_kept():
    """Headline citing a hallucinated ref → headline=None; valid highlights kept.

    Outcome: '(b) emits a headline citing a hallucinated ref → headline becomes
    None, surviving highlights are kept.'
    """
    portfolio = _portfolio(
        claims=[Claim(text="Built thing", evidence_refs=["PR#1"], confidence=0.9)],
        evidence=[Evidence(kind="pr", ref="PR#1")],
    )

    def runner(prompt: str) -> str:
        return json.dumps(
            {
                "headline": "Summary citing PR#FAKE",
                "headline_refs": ["PR#FAKE"],  # hallucinated
                "highlights": [{"text": "Valid bullet", "evidence_refs": ["PR#1"]}],
            }
        )

    result = synthesize(portfolio, runner)
    assert result.headline is None
    assert result.headline_refs == []
    assert len(result.highlights) == 1
    assert result.highlights[0].text == "Valid bullet"


def test_empty_headline_refs_sets_headline_none():
    """headline_refs=[] → headline is None (empty-refs reject).

    Outcome: '(c) emits a headline with "headline_refs": [] → headline becomes
    None (empty-refs reject).'
    """
    portfolio = _portfolio(
        claims=[Claim(text="Built thing", evidence_refs=["PR#1"], confidence=0.9)],
        evidence=[Evidence(kind="pr", ref="PR#1")],
    )

    def runner(prompt: str) -> str:
        return json.dumps(
            {
                "headline": "A real headline",
                "headline_refs": [],  # empty → reject
                "highlights": [{"text": "Valid bullet", "evidence_refs": ["PR#1"]}],
            }
        )

    result = synthesize(portfolio, runner)
    assert result.headline is None


def test_refs_in_evidence_not_in_claim_refs_dropped():
    """Headline + highlight citing a real evidence ref not in any claim's refs are dropped.

    Outcome: '(d) emits a headline + highlight that each cite ONLY a ref present in
    portfolio.evidence but NOT in any grounded claim's evidence_refs → both are dropped.'
    """
    portfolio = Portfolio(
        subject="alice",
        evidence=[
            Evidence(kind="pr", ref="PR#1"),
            Evidence(kind="pr", ref="PR#2"),  # real evidence, but no claim cites it
        ],
        claims=[
            Claim(text="Built thing", evidence_refs=["PR#1"], confidence=0.9),
        ],
    )

    def runner(prompt: str) -> str:
        return json.dumps(
            {
                "headline": "References PR#2",
                "headline_refs": ["PR#2"],
                "highlights": [{"text": "PR#2 highlight", "evidence_refs": ["PR#2"]}],
            }
        )

    result = synthesize(portfolio, runner)
    assert result.headline is None
    assert result.highlights == []


# ---------------------------------------------------------------------------
# Done-when: deterministic ≤5 highlight cap
# ---------------------------------------------------------------------------


def test_seven_grounded_highlights_capped_to_five():
    """7 grounded highlights → result has exactly 5, in model order.

    Outcome: 'fake runner that returns SEVEN grounded highlights yields
    len(result.highlights) == 5 and ... exactly the first five in model order.'
    """
    portfolio = _portfolio(
        claims=[Claim(text="Built thing", evidence_refs=["PR#1"], confidence=0.9)],
        evidence=[Evidence(kind="pr", ref="PR#1")],
    )

    highlights_7 = [{"text": f"bullet{i}", "evidence_refs": ["PR#1"]} for i in range(7)]

    def runner(prompt: str) -> str:
        return json.dumps(
            {
                "headline": "Great developer",
                "headline_refs": ["PR#1"],
                "highlights": highlights_7,
            }
        )

    result = synthesize(portfolio, runner)
    assert len(result.highlights) == 5
    assert [h.text for h in result.highlights] == [f"bullet{i}" for i in range(5)]


# ---------------------------------------------------------------------------
# Done-when: deterministic headline length enforcement (PR-012)
# ---------------------------------------------------------------------------


def test_headline_line_cap_and_char_truncation():
    """6-line headline truncated to 3; 600-char line truncated to 200.

    Outcome: 'fake runner emits a grounded headline with 6 non-empty lines AND a
    600-character line: the result is capped to 3 lines, each ≤200 chars.'
    """
    portfolio = _portfolio(
        claims=[Claim(text="Built thing", evidence_refs=["PR#1"], confidence=0.9)],
        evidence=[Evidence(kind="pr", ref="PR#1")],
    )

    long_line = "x" * 600
    six_line_headline = "\n".join([f"line{i}" for i in range(5)] + [long_line])

    def runner(prompt: str) -> str:
        return json.dumps(
            {
                "headline": six_line_headline,
                "headline_refs": ["PR#1"],
                "highlights": [],
            }
        )

    result = synthesize(portfolio, runner)
    assert result.headline is not None
    result_lines = result.headline.split("\n")
    assert len(result_lines) == 3
    for ln in result_lines:
        assert len(ln) <= 200


def test_headline_char_truncation_on_a_surviving_line():
    """Per-line 200-char truncation runs on a line that SURVIVES the 3-line cap.

    The previous test's 600-char line was the 6th, removed by the line cap before
    char-truncation could matter. Here the headline is 2 lines (within the cap) and
    the 2nd is 600 chars, so the 200-char truncation is the assertion under test.
    """
    portfolio = _portfolio(
        claims=[Claim(text="Built thing", evidence_refs=["PR#1"], confidence=0.9)],
        evidence=[Evidence(kind="pr", ref="PR#1")],
    )

    long_line = "y" * 600
    two_line_headline = f"short summary\n{long_line}"

    def runner(prompt: str) -> str:
        return json.dumps(
            {
                "headline": two_line_headline,
                "headline_refs": ["PR#1"],
                "highlights": [],
            }
        )

    result = synthesize(portfolio, runner)
    assert result.headline is not None
    lines = result.headline.split("\n")
    assert len(lines) == 2  # both within the 3-line cap → both survive
    assert lines[0] == "short summary"
    assert len(lines[1]) == 200  # the 600-char line truncated to exactly 200
    assert lines[1] == "y" * 200


# ---------------------------------------------------------------------------
# Done-when: empty portfolio → synthesis runner not called
# ---------------------------------------------------------------------------


def test_empty_portfolio_synthesis_runner_not_called():
    """When portfolio.claims is empty, build_from_evidence does NOT invoke synthesis_runner.

    Outcome: 'pipeline test that passes a synthesis_runner that raises on call;
    the test must complete without an exception and produce BuildResult.synthesis is None.'
    """
    from portfolio.pipeline import build_from_evidence

    def exploding_runner(prompt: str) -> str:
        raise RuntimeError("synthesis_runner must not be called on empty portfolio")

    def fake_narrate_runner(prompt: str) -> str:
        # Returns no claims (empty list)
        return "[]"

    evidence = [Evidence(kind="pr", ref="PR#1")]
    result = build_from_evidence("alice", evidence, fake_narrate_runner, synthesis_runner=exploding_runner)
    # portfolio.claims is empty (narrate returned []) → synthesis must NOT run
    assert result.synthesis is None
