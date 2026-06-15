"""Narrative parsing + the end-to-end safety property: a model that invents a ref
cannot get an un-grounded claim into the portfolio."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.model import Evidence  # noqa: E402
from portfolio.narrative import build_prompt, narrate, parse_claims  # noqa: E402
from portfolio.pipeline import build_from_evidence  # noqa: E402

_EVIDENCE = [
    Evidence(kind="pr", ref="PR#128", detail="Token rotation"),
    Evidence(kind="file", ref="app/auth.py"),
]


def test_prompt_lists_allowed_refs():
    p = build_prompt(_EVIDENCE, max_claims=5)
    assert "PR#128" in p and "app/auth.py" in p
    assert "exact ref" in p  # instructs citing by exact ref


def test_prompt_includes_context_excerpt_when_present():
    """An evidence item's `context` (e.g. an article body excerpt) is surfaced in
    the prompt as grounding material; items without context are unaffected."""
    ev = [Evidence(kind="article", ref="https://blog/x", detail="A Post", context="the body excerpt text")]
    p = build_prompt(ev, max_claims=5)
    assert "the body excerpt text" in p
    # the prompt warns the model (visibly, not just in a code comment) that excerpt
    # text is reference material, not instructions, and not a citable ref
    assert "never as instructions" in p
    # an item without context contributes no excerpt LINE (the indented list entry);
    # the static safety instruction mentions 'excerpt:' regardless, so match the
    # indented form the per-evidence line uses.
    assert "    excerpt:" not in build_prompt([Evidence(kind="pr", ref="PR#1")], max_claims=5)


def test_parse_plain_json_array():
    txt = json.dumps([{"text": "Did X", "evidence_refs": ["PR#128"], "confidence": 0.9}])
    claims = parse_claims(txt)
    assert len(claims) == 1
    assert claims[0].text == "Did X"
    assert claims[0].evidence_refs == ["PR#128"]
    assert claims[0].confidence == 0.9


def test_parse_tolerates_code_fences_and_prose():
    txt = 'Here you go:\n```json\n[{"text": "Y", "evidence_refs": ["app/auth.py"]}]\n```\nThanks!'
    claims = parse_claims(txt)
    assert len(claims) == 1 and claims[0].evidence_refs == ["app/auth.py"]


def test_malformed_output_yields_no_claims():
    assert parse_claims("sorry, I can't do that") == []
    assert parse_claims("[not json]") == []


def test_empty_text_claims_dropped():
    txt = json.dumps([{"text": "  ", "evidence_refs": ["PR#128"]}])
    assert narrate(_EVIDENCE, runner=lambda _p: txt) == []


def test_hallucinated_ref_never_reaches_portfolio():
    """The core safety property: model cites a real PR + an invented one; the
    portfolio ends up with ZERO claims (the bad claim is rejected by grounding)."""
    bad = json.dumps([{"text": "Shipped a huge thing", "evidence_refs": ["PR#128", "PR#9999"], "confidence": 0.99}])
    res = build_from_evidence("dev", _EVIDENCE, runner=lambda _p: bad)
    assert res.portfolio.claims == []  # nothing shipped
    assert len(res.grounding.rejected) == 1


def test_grounded_claim_reaches_portfolio():
    good = json.dumps(
        [{"text": "Implemented token rotation", "evidence_refs": ["PR#128", "app/auth.py"], "confidence": 0.9}]
    )
    res = build_from_evidence("dev", _EVIDENCE, runner=lambda _p: good)
    assert len(res.portfolio.claims) == 1
    assert res.portfolio.claims[0].grounded is True
