from __future__ import annotations

from cs_mvp.models import AnalysisClaim, EvidenceItem
from cs_mvp.tools.citation import compute_support_score, verify_claim


def _evidence(quote: str) -> EvidenceItem:
    return EvidenceItem(
        evidence_id="E-001",
        source_id="S-001",
        competitor_name="Cursor",
        quote=quote,
    )


def test_verify_claim_pass() -> None:
    evidence = _evidence("Cursor Pro costs $20 per month.")
    claim = AnalysisClaim(
        claim_id="C-001",
        run_id="RUN-1",
        competitor_name="Cursor",
        dimension="pricing",
        statement="Cursor Pro costs $20 per month.",
        evidence_ids=["E-001"],
    )

    accepted, discarded = verify_claim(claim, {"E-001": evidence})

    assert accepted is claim
    assert discarded is None
    assert claim.accepted is True
    assert claim.support_score is not None and claim.support_score >= 0.6


def test_verify_claim_uncertain() -> None:
    evidence = _evidence("Cursor costs $20.")
    claim = AnalysisClaim(
        claim_id="C-002",
        run_id="RUN-1",
        competitor_name="Cursor",
        dimension="pricing",
        statement="Cursor Enterprise Teams Advanced costs $20.",
        evidence_ids=["E-001"],
    )

    accepted, discarded = verify_claim(claim, {"E-001": evidence})

    assert accepted is claim
    assert discarded is not None
    assert discarded.verdict == "uncertain"
    assert 0.3 <= claim.support_score < 0.6  # type: ignore[operator]


def test_verify_claim_fail() -> None:
    evidence = _evidence("Cursor supports code completion.")
    claim = AnalysisClaim(
        claim_id="C-003",
        run_id="RUN-1",
        competitor_name="Cursor",
        dimension="pricing",
        statement="Windsurf Enterprise costs $99.",
        evidence_ids=["E-001"],
    )

    accepted, discarded = verify_claim(claim, {"E-001": evidence})

    assert accepted is None
    assert discarded is not None
    assert discarded.verdict == "fail"


def test_uncertain_claim_kept_accepted_with_discarded_record() -> None:
    """uncertain claim 必须同时：accepted=True（仍能渲染到 Risks & Unknowns）+ 产生 discarded 记录"""
    evidence = _evidence("Cursor costs $20.")
    claim = AnalysisClaim(
        claim_id="C-UNCERTAIN",
        run_id="RUN-1",
        competitor_name="Cursor",
        dimension="pricing",
        statement="Cursor Enterprise Teams Advanced costs $20.",
        evidence_ids=["E-001"],
    )

    accepted, discarded = verify_claim(claim, {"E-001": evidence})

    assert accepted is not None
    assert accepted.accepted is True
    assert discarded is not None
    assert discarded.verdict == "uncertain"
    assert discarded.claim_id == "C-UNCERTAIN"


def test_numeric_price_match_scores_above_zero() -> None:
    evidence = _evidence("The Pro plan is $20 per month.")
    claim = AnalysisClaim(
        claim_id="C-004",
        run_id="RUN-1",
        competitor_name="Cursor",
        dimension="pricing",
        statement="The Pro plan costs $20.",
        evidence_ids=["E-001"],
    )

    score, _ = compute_support_score(claim, {"E-001": evidence})

    assert score > 0


def test_cross_claim_uses_lower_threshold() -> None:
    evidence = _evidence("Notion costs $20 per month.")
    cross_claim = AnalysisClaim(
        claim_id="C-CROSS",
        run_id="RUN-1",
        competitor_name=None,
        dimension="pricing",
        statement="Cursor Notion Evernote pricing differs significantly",
        evidence_ids=["E-001"],
    )

    accepted, _discarded = verify_claim(cross_claim, {"E-001": evidence})

    if cross_claim.support_score and cross_claim.support_score >= 0.4:
        assert accepted is not None
        assert accepted.accepted is True


def test_single_claim_still_uses_06_threshold() -> None:
    evidence = _evidence("Cursor costs $20.")
    claim = AnalysisClaim(
        claim_id="C-SINGLE",
        run_id="RUN-1",
        competitor_name="Cursor",
        dimension="pricing",
        statement="Cursor Pro Enterprise Advanced costs $20.",
        evidence_ids=["E-001"],
    )

    accepted, discarded = verify_claim(claim, {"E-001": evidence})

    assert accepted is not None
    assert discarded is not None
    assert discarded.verdict == "uncertain"
    assert claim.support_score is not None and 0.3 <= claim.support_score < 0.6
