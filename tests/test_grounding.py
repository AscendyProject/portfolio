"""The grounding gate is the trust boundary — test it hardest. A claim ships only
if every ref it cites is real; a hallucinated ref is a hard reject."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.grounding import check_claims  # noqa: E402
from portfolio.model import Claim, Evidence  # noqa: E402

_EVIDENCE = [
    Evidence(kind="pr", ref="PR#128", url="u"),
    Evidence(kind="file", ref="app/auth.py"),
]


def test_claim_citing_real_evidence_is_grounded():
    c = Claim(text="Implemented token rotation", evidence_refs=["PR#128", "app/auth.py"])
    res = check_claims([c], _EVIDENCE)
    assert res.grounded == [c]
    assert c.grounded is True
    assert not res.rejected


def test_claim_citing_nothing_is_rejected():
    c = Claim(text="Led the whole rewrite", evidence_refs=[])
    res = check_claims([c], _EVIDENCE)
    assert res.rejected == [c]
    assert c.grounded is False


def test_hallucinated_ref_poisons_the_claim():
    # one real ref + one invented PR → still rejected (can't ship a fabricated cite)
    c = Claim(text="Shipped X and Y", evidence_refs=["PR#128", "PR#999"])
    res = check_claims([c], _EVIDENCE)
    assert res.rejected == [c]
    assert c.grounded is False


def test_needs_confirmation_is_separated_from_clean_grounded():
    c = Claim(text="Owned auth design", evidence_refs=["PR#128"], needs_user_confirmation=True)
    res = check_claims([c], _EVIDENCE)
    assert res.needs_confirmation == [c]
    assert res.grounded == []
    assert c.grounded is True  # grounded, but still gated for a human


def test_partitions_a_mixed_batch():
    real = Claim(text="real", evidence_refs=["PR#128"])
    fake = Claim(text="fake", evidence_refs=["PR#404"])
    empty = Claim(text="vibes", evidence_refs=[])
    res = check_claims([real, fake, empty], _EVIDENCE)
    assert res.grounded == [real]
    assert set(id(c) for c in res.rejected) == {id(fake), id(empty)}
