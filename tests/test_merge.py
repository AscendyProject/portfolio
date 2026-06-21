"""Tests for merge_portfolios (store.py) and the CLI merge subcommand (cli.py).

Each test traces to a Done-when item in the task outcome.md via its docstring.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.cli import run  # noqa: E402 — after sys.path setup per test-conventions
from portfolio.grounding import check_claims  # noqa: E402 — after sys.path setup per test-conventions
from portfolio.model import Claim, Evidence, Portfolio  # noqa: E402 — after sys.path setup per test-conventions
from portfolio.sources import SourceRequest, resolve_source  # noqa: E402 — after sys.path setup per test-conventions
from portfolio.store import (  # noqa: E402 — after sys.path setup per test-conventions
    SCHEMA_VERSION,
    PortfolioStoreError,
    merge_portfolios,
    portfolio_from_json,
    portfolio_to_json,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ev(kind: str, ref: str, url: str = "", detail: str = "", context: str = "") -> Evidence:
    return Evidence(kind=kind, ref=ref, url=url, detail=detail, context=context)


def _cl(
    text: str,
    refs: list[str],
    confidence: float = 0.9,
    needs_confirmation: bool = False,
) -> Claim:
    return Claim(
        text=text,
        evidence_refs=refs,
        confidence=confidence,
        needs_user_confirmation=needs_confirmation,
        grounded=True,
    )


def _make_portfolio_a() -> Portfolio:
    """Portfolio A with repo-qualified refs."""
    return Portfolio(
        subject="alice-corp",
        evidence=[
            _ev("pr", "owner-a/repo-a#1", url="https://github.com/owner-a/repo-a/pull/1", detail="Feature A"),
            _ev("file", "owner-a/repo-a:src/main.py"),
        ],
        claims=[_cl("Built feature A", ["owner-a/repo-a#1"])],
    )


def _make_portfolio_b() -> Portfolio:
    """Portfolio B with repo-qualified refs."""
    return Portfolio(
        subject="alice-personal",
        evidence=[
            _ev("pr", "owner-b/repo-b#2", url="https://github.com/owner-b/repo-b/pull/2", detail="Feature B"),
        ],
        claims=[_cl("Built feature B", ["owner-b/repo-b#2"])],
    )


# ---------------------------------------------------------------------------
# Done-when: two-input union (happy path)
# ---------------------------------------------------------------------------


def test_two_input_union_happy_path():
    """'Merging two Portfolios yields one Portfolio whose evidence count equals |A ∪ B|
    and whose claims count equals the union of input claims (all grounded here).'"""
    a = _make_portfolio_a()
    b = _make_portfolio_b()
    merged = merge_portfolios([a, b], subject="Alice Smith")
    # evidence: 2 from A + 1 from B = 3 total (no overlapping (kind, ref))
    assert len(merged.evidence) == 3
    # claims: 1 from A + 1 from B = 2 total
    assert len(merged.claims) == 2
    assert merged.subject == "Alice Smith"


# ---------------------------------------------------------------------------
# Done-when: evidence dedup by (kind, ref)
# ---------------------------------------------------------------------------


def test_evidence_dedup_by_kind_ref():
    """'Identical (kind, ref) across inputs collapses to exactly one entry,
    even when other Evidence fields differ; non-identical (kind, ref) pairs are preserved.'"""
    shared_ref = "owner-a/repo-a#1"
    a = Portfolio(
        subject="a",
        evidence=[_ev("pr", shared_ref, url="https://example.com/1", detail="From A")],
        claims=[_cl("A claim", [shared_ref])],
    )
    b = Portfolio(
        subject="b",
        evidence=[
            _ev("pr", shared_ref, url="https://example.com/2", detail="From B"),  # same (kind, ref), different fields
            _ev("pr", "owner-b/repo-b#2", detail="Unique to B"),
        ],
        claims=[_cl("B claim", ["owner-b/repo-b#2"])],
    )
    merged = merge_portfolios([a, b], subject="Alice")
    # Only 2 evidence entries: shared_ref once + unique B ref
    refs = [(e.kind, e.ref) for e in merged.evidence]
    assert refs.count(("pr", shared_ref)) == 1
    assert ("pr", "owner-b/repo-b#2") in refs
    assert len(merged.evidence) == 2


def test_evidence_dedup_preserves_first_seen():
    """When (kind, ref) collides, the first-seen evidence entry (from portfolio[0]) wins."""
    shared_ref = "owner-a/repo-a#1"
    a = Portfolio(
        subject="a",
        evidence=[_ev("pr", shared_ref, url="https://from-a.example.com", detail="From A")],
        claims=[],
    )
    b = Portfolio(
        subject="b",
        evidence=[_ev("pr", shared_ref, url="https://from-b.example.com", detail="From B")],
        claims=[],
    )
    merged = merge_portfolios([a, b], subject="Alice")
    assert len(merged.evidence) == 1
    assert merged.evidence[0].detail == "From A"  # first-seen wins


# ---------------------------------------------------------------------------
# Done-when: subject is authoritative-by-argument
# ---------------------------------------------------------------------------


def test_subject_is_authoritative_by_argument():
    """'Given inputs with differing subjects (alice-corp, alice-personal) and
    explicit subject="Alice Smith", the merged Portfolio's subject equals "Alice Smith",
    with no error raised. The subjects of the input portfolios are not compared.'"""
    a = _make_portfolio_a()  # subject="alice-corp"
    b = _make_portfolio_b()  # subject="alice-personal"
    merged = merge_portfolios([a, b], subject="Alice Smith")
    assert merged.subject == "Alice Smith"


# ---------------------------------------------------------------------------
# Done-when: empty / invalid subject argument
# ---------------------------------------------------------------------------


def test_empty_subject_raises():
    """'merge_portfolios([p1, p2], subject="") raises PortfolioStoreError.'"""
    a = _make_portfolio_a()
    b = _make_portfolio_b()
    with pytest.raises(PortfolioStoreError):
        merge_portfolios([a, b], subject="")


def test_whitespace_subject_raises():
    """'merge_portfolios([p1, p2], subject="   ") raises PortfolioStoreError (whitespace-only).'"""
    a = _make_portfolio_a()
    b = _make_portfolio_b()
    with pytest.raises(PortfolioStoreError):
        merge_portfolios([a, b], subject="   ")


def test_empty_portfolios_list_raises():
    """'merge_portfolios([], subject="x") raises PortfolioStoreError.'"""
    with pytest.raises(PortfolioStoreError):
        merge_portfolios([], subject="Alice")


# ---------------------------------------------------------------------------
# Done-when: bare-vs-repo-qualified collision guard (REJECTION strategy, PR-002)
# ---------------------------------------------------------------------------


def test_bare_pr_ref_raises_names_first_offender():
    """'A portfolio containing a bare PR#1 evidence ref causes a typed REJECTION error
    (PortfolioStoreError) naming the offending input portfolio by 0-based index.
    The merge does not proceed.'"""
    bare = Portfolio(
        subject="a",
        evidence=[_ev("pr", "PR#1", url="https://github.com/o/r/pull/1", detail="bare ref")],
        claims=[],
    )
    clean = _make_portfolio_b()
    with pytest.raises(PortfolioStoreError, match="0"):
        merge_portfolios([bare, clean], subject="Alice")


def test_bare_file_ref_raises():
    """'A bare file ref (no colon, lacks owner/repo: qualification) triggers PortfolioStoreError.'"""
    bare_file = Portfolio(
        subject="a",
        evidence=[_ev("file", "src/main.py")],  # no colon → bare
        claims=[],
    )
    with pytest.raises(PortfolioStoreError):
        merge_portfolios([bare_file, _make_portfolio_b()], subject="Alice")


def test_bare_ref_in_second_input_names_index_1():
    """'Bare ref in the second input portfolio → error message names index 1.'"""
    clean = _make_portfolio_a()
    bare = Portfolio(
        subject="b",
        evidence=[_ev("pr", "PR#99")],
        claims=[],
    )
    with pytest.raises(PortfolioStoreError, match="1"):
        merge_portfolios([clean, bare], subject="Alice")


def test_repo_qualified_pr_refs_dedup_no_error():
    """'Two portfolios both carrying the repo-qualified ref owner-a/repo-a#1 collapse to
    exactly one entry — the guard targets only bare refs, not qualified ones.'"""
    ref = "owner-a/repo-a#1"
    a = Portfolio(
        subject="a",
        evidence=[_ev("pr", ref, detail="From A")],
        claims=[_cl("Claim from A", [ref])],
    )
    b = Portfolio(
        subject="b",
        evidence=[_ev("pr", ref, detail="From B")],
        claims=[_cl("Claim from B", [ref])],
    )
    # Must NOT raise — repo-qualified refs are acceptable inputs
    merged = merge_portfolios([a, b], subject="Alice")
    assert len(merged.evidence) == 1
    assert merged.evidence[0].ref == ref


# ---------------------------------------------------------------------------
# Done-when: grounding invariant on merged output
# ---------------------------------------------------------------------------


def test_grounding_invariant_drops_dangling_claim():
    """'A claim citing a ref that disappears (or never existed) in the merged evidence
    set is dropped from merged.claims; grounding.check_claims(list(merged.claims),
    merged.evidence).rejected is empty.'"""
    ref_a = "owner-a/repo-a#1"
    ref_b = "owner-b/repo-b#2"
    a = Portfolio(
        subject="a",
        evidence=[_ev("pr", ref_a)],
        claims=[_cl("Valid claim from A", [ref_a])],
    )
    b = Portfolio(
        subject="b",
        evidence=[_ev("pr", ref_b)],
        claims=[
            _cl("Valid claim from B", [ref_b]),
            Claim(
                text="Dangling claim",
                evidence_refs=["owner-x/repo-x#999"],  # not in any input evidence
                confidence=0.5,
                needs_user_confirmation=False,
                grounded=True,  # was grounded within B; now dangling after merge
            ),
        ],
    )
    merged = merge_portfolios([a, b], subject="Alice")
    claim_texts = [c.text for c in merged.claims]
    assert "Dangling claim" not in claim_texts
    assert "Valid claim from A" in claim_texts
    assert "Valid claim from B" in claim_texts
    # The grounding invariant: re-checking the final output must yield no rejections
    re_check = check_claims(list(merged.claims), merged.evidence)
    assert re_check.rejected == []


def test_grounding_invariant_holds_needs_confirmation():
    """'Claims with needs_user_confirmation=True that are grounded survive the merge.'"""
    ref = "owner-a/repo-a#1"
    a = Portfolio(
        subject="a",
        evidence=[_ev("pr", ref)],
        claims=[
            Claim(
                text="Confirmed claim", evidence_refs=[ref], confidence=0.9, needs_user_confirmation=True, grounded=True
            ),
        ],
    )
    merged = merge_portfolios([a, _make_portfolio_b()], subject="Alice")
    claim_texts = [c.text for c in merged.claims]
    assert "Confirmed claim" in claim_texts


# ---------------------------------------------------------------------------
# Done-when: round-trip
# ---------------------------------------------------------------------------


def test_round_trip():
    """'portfolio_from_json(portfolio_to_json(merged)) equals merged field-by-field, and
    the serialized dict's schema_version equals the current SCHEMA_VERSION constant.'"""
    a = _make_portfolio_a()
    b = _make_portfolio_b()
    merged = merge_portfolios([a, b], subject="Alice Smith")

    roundtripped = portfolio_from_json(portfolio_to_json(merged))
    assert roundtripped == merged

    serialized = json.loads(portfolio_to_json(merged))
    assert serialized["schema_version"] == SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Done-when: load via --source-type portfolio
# ---------------------------------------------------------------------------


def test_load_via_portfolio_source(tmp_path):
    """'Writing the merged Portfolio to a temp path and resolving it through the existing
    portfolio source loader (_portfolio_handler in sources.py) yields a Portfolio equal
    to merged. sources.py is not modified.'"""
    a = _make_portfolio_a()
    b = _make_portfolio_b()
    merged = merge_portfolios([a, b], subject="Alice Smith")

    saved = tmp_path / "merged.json"
    saved.write_text(portfolio_to_json(merged), encoding="utf-8")

    resolved = resolve_source("portfolio", SourceRequest(source=str(saved), author=None))
    assert resolved.prebuilt is not None
    assert resolved.prebuilt == merged


# ---------------------------------------------------------------------------
# Done-when: CLI happy path
# ---------------------------------------------------------------------------


def test_cli_merge_happy_path(tmp_path, capsys):
    """'python -m portfolio merge a.json b.json --subject Alice --out merged.json exits 0
    and writes a Portfolio JSON to merged.json whose subject is "Alice".'"""
    a = _make_portfolio_a()
    b = _make_portfolio_b()

    a_json = tmp_path / "a.json"
    b_json = tmp_path / "b.json"
    out_json = tmp_path / "merged.json"

    a_json.write_text(portfolio_to_json(a), encoding="utf-8")
    b_json.write_text(portfolio_to_json(b), encoding="utf-8")

    code = run(["merge", str(a_json), str(b_json), "--subject", "Alice", "--out", str(out_json)])
    capsys.readouterr()
    assert code == 0
    assert out_json.exists()
    loaded = portfolio_from_json(out_json.read_text(encoding="utf-8"))
    assert loaded.subject == "Alice"


def test_cli_merge_does_not_invoke_extraction_or_model(tmp_path):
    """merge dispatch is PURE — it must not call the extractor (`gh`), runner
    (model), or fetcher (network) seams. Injects raise-on-call seams and asserts
    the merge still succeeds. Fails against pre-change code, which has no `merge`
    path so `run(["merge", ...])` never produces a merged file (IR-002)."""
    from portfolio.model import Claim, Evidence, Portfolio
    from portfolio.store import portfolio_from_json, portfolio_to_json

    p1 = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="owner-a/repo#1")],
        claims=[Claim(text="A", evidence_refs=["owner-a/repo#1"], confidence=0.9, grounded=True)],
    )
    p2 = Portfolio(
        subject="alice",
        evidence=[Evidence(kind="pr", ref="owner-b/repo#2")],
        claims=[Claim(text="B", evidence_refs=["owner-b/repo#2"], confidence=0.9, grounded=True)],
    )
    f1 = tmp_path / "a.json"
    f1.write_text(portfolio_to_json(p1), encoding="utf-8")
    f2 = tmp_path / "b.json"
    f2.write_text(portfolio_to_json(p2), encoding="utf-8")
    out = tmp_path / "merged.json"

    def boom_extractor(**_kw):
        raise AssertionError("extractor (gh) must not be called for merge")

    def boom_runner(_prompt):
        raise AssertionError("runner (model) must not be called for merge")

    def boom_fetcher(_url):
        raise AssertionError("fetcher (network) must not be called for merge")

    code = run(
        ["merge", str(f1), str(f2), "--subject", "alice", "--out", str(out)],
        extractor=boom_extractor,
        runner=boom_runner,
        fetcher=boom_fetcher,
    )
    assert code == 0
    assert out.exists()
    merged = portfolio_from_json(out.read_text(encoding="utf-8"))
    assert merged.subject == "alice"
    assert len(merged.evidence) == 2  # union of two distinct repo-qualified refs


# ---------------------------------------------------------------------------
# Done-when: CLI exit code 2 (non-traceback stderr) cases
# ---------------------------------------------------------------------------


def test_cli_merge_missing_input_file_exits_2(tmp_path, capsys):
    """(a) 'input path is missing → exit 2, failing path named in message, no traceback.'"""
    a = _make_portfolio_a()
    a_json = tmp_path / "a.json"
    a_json.write_text(portfolio_to_json(a), encoding="utf-8")
    missing = tmp_path / "nonexistent.json"
    out = tmp_path / "out.json"

    code = run(["merge", str(a_json), str(missing), "--subject", "Alice", "--out", str(out)])
    err = capsys.readouterr().err
    assert code == 2
    assert "Traceback" not in err
    assert err.strip() != ""
    # The failing path should be named in the message
    assert "nonexistent.json" in err


def test_cli_merge_malformed_json_exits_2(tmp_path, capsys):
    """(b) 'input path holds malformed JSON → exit 2, failing path named in message, no traceback.'"""
    a = _make_portfolio_a()
    a_json = tmp_path / "a.json"
    a_json.write_text(portfolio_to_json(a), encoding="utf-8")
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("this is not json {{{", encoding="utf-8")
    out = tmp_path / "out.json"

    code = run(["merge", str(a_json), str(bad_json), "--subject", "Alice", "--out", str(out)])
    err = capsys.readouterr().err
    assert code == 2
    assert "Traceback" not in err
    assert err.strip() != ""
    assert "bad.json" in err


def test_cli_merge_bare_ref_guard_exits_2(tmp_path, capsys):
    """(c) 'bare-ref guard fires → exit 2, no traceback.'"""
    bare = Portfolio(
        subject="x",
        evidence=[_ev("pr", "PR#1")],
        claims=[],
    )
    clean = _make_portfolio_b()
    a_json = tmp_path / "bare.json"
    b_json = tmp_path / "clean.json"
    out = tmp_path / "out.json"
    a_json.write_text(portfolio_to_json(bare), encoding="utf-8")
    b_json.write_text(portfolio_to_json(clean), encoding="utf-8")

    code = run(["merge", str(a_json), str(b_json), "--subject", "Alice", "--out", str(out)])
    err = capsys.readouterr().err
    assert code == 2
    assert "Traceback" not in err
    assert err.strip() != ""


def test_cli_merge_fewer_than_2_inputs_exits_2(tmp_path, capsys):
    """(d) 'fewer than 2 input paths → exit 2, no traceback.'"""
    a = _make_portfolio_a()
    a_json = tmp_path / "a.json"
    a_json.write_text(portfolio_to_json(a), encoding="utf-8")
    out = tmp_path / "out.json"

    code = run(["merge", str(a_json), "--subject", "Alice", "--out", str(out)])
    err = capsys.readouterr().err
    assert code == 2
    assert "Traceback" not in err
    assert err.strip() != ""


def test_cli_merge_missing_subject_exits_2(tmp_path, capsys):
    """(e) '--subject missing → exit 2, no traceback.'"""
    a = _make_portfolio_a()
    b = _make_portfolio_b()
    a_json = tmp_path / "a.json"
    b_json = tmp_path / "b.json"
    out = tmp_path / "out.json"
    a_json.write_text(portfolio_to_json(a), encoding="utf-8")
    b_json.write_text(portfolio_to_json(b), encoding="utf-8")

    code = run(["merge", str(a_json), str(b_json), "--out", str(out)])
    err = capsys.readouterr().err
    assert code == 2
    assert "Traceback" not in err
    assert err.strip() != ""


def test_cli_merge_empty_subject_exits_2(tmp_path, capsys):
    """(e) '--subject empty string → exit 2, no traceback.'"""
    a = _make_portfolio_a()
    b = _make_portfolio_b()
    a_json = tmp_path / "a.json"
    b_json = tmp_path / "b.json"
    out = tmp_path / "out.json"
    a_json.write_text(portfolio_to_json(a), encoding="utf-8")
    b_json.write_text(portfolio_to_json(b), encoding="utf-8")

    code = run(["merge", str(a_json), str(b_json), "--subject", "", "--out", str(out)])
    err = capsys.readouterr().err
    assert code == 2
    assert "Traceback" not in err
    assert err.strip() != ""


def test_cli_merge_missing_out_exits_2(tmp_path, capsys):
    """(f) '--out missing → exit 2, no traceback.'"""
    a = _make_portfolio_a()
    b = _make_portfolio_b()
    a_json = tmp_path / "a.json"
    b_json = tmp_path / "b.json"
    a_json.write_text(portfolio_to_json(a), encoding="utf-8")
    b_json.write_text(portfolio_to_json(b), encoding="utf-8")

    code = run(["merge", str(a_json), str(b_json), "--subject", "Alice"])
    err = capsys.readouterr().err
    assert code == 2
    assert "Traceback" not in err
    assert err.strip() != ""
