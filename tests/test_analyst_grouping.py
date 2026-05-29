from __future__ import annotations

from cs_mvp.agents.analyst_grouping import (
    DIMENSIONS,
    group_evidence_by_dimension,
)
from cs_mvp.models import EvidenceItem


def _ev(
    eid: str,
    competitor: str,
    claim_type: str,
    confidence: float = 0.8,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=eid,
        source_id=f"S-{eid}",
        competitor_name=competitor,
        claim_type=claim_type,  # type: ignore[arg-type]
        quote="x" * 60,
        normalized_fact="standard fact",
        confidence=confidence,
    )


def test_group_by_claim_type_mapping() -> None:
    evidence = [
        _ev("E1", "Cursor", "feature"),
        _ev("E2", "Cursor", "pricing"),
        _ev("E3", "Cursor", "positioning"),
        _ev("E4", "Cursor", "metric"),
        _ev("E5", "Cursor", "other"),
        _ev("E6", "Windsurf", "feature"),  # 不同 competitor 应被排除
    ]
    result = group_evidence_by_dimension(evidence, "Cursor")

    assert {e.evidence_id for e in result["features"]} >= {"E1", "E4"}
    assert {e.evidence_id for e in result["pricing"]} >= {"E2"}
    assert {e.evidence_id for e in result["positioning"]} >= {"E3"}
    # other 不主映射到 features/pricing/positioning, 但会作为 secondary 补充
    # E6 必须被排除
    for dim in DIMENSIONS:
        assert "E6" not in {e.evidence_id for e in result[dim]}


def test_swot_dimension_synthesized_from_metric_other_positioning() -> None:
    evidence = [
        _ev("EP", "Cursor", "positioning"),
        _ev("EM", "Cursor", "metric"),
        _ev("EO", "Cursor", "other"),
        _ev("EF", "Cursor", "feature"),
    ]
    result = group_evidence_by_dimension(evidence, "Cursor")

    swot_ids = {e.evidence_id for e in result["swot"]}
    assert "EP" in swot_ids
    assert "EM" in swot_ids
    assert "EO" in swot_ids
    # feature 不应进 swot 种子
    assert "EF" not in swot_ids


def test_each_dimension_caps_at_10_evidence() -> None:
    # 13 条 feature, 应裁到 10 条
    evidence = [
        _ev(f"E{i:03d}", "Cursor", "feature", confidence=0.5 + i * 0.01)
        for i in range(13)
    ]
    result = group_evidence_by_dimension(evidence, "Cursor")
    assert len(result["features"]) == 10
    # 应保留 confidence 最高的 10 条(E003..E012)
    kept = {e.evidence_id for e in result["features"]}
    assert "E000" not in kept  # 最低 confidence 应被裁掉


def test_other_pool_supplements_features_when_primary_thin() -> None:
    # features 只有 1 条 primary, other 有 5 条 -> features 应被补充
    evidence = [
        _ev("F1", "Cursor", "feature"),
        _ev("O1", "Cursor", "other"),
        _ev("O2", "Cursor", "other"),
        _ev("O3", "Cursor", "other"),
    ]
    result = group_evidence_by_dimension(evidence, "Cursor")
    feature_ids = {e.evidence_id for e in result["features"]}
    assert "F1" in feature_ids
    assert len(feature_ids) > 1  # 被 other 补充了


def test_swot_deduplicates_when_positioning_metric_other_overlap() -> None:
    # 同一条 positioning evidence 不应在 swot 出现两次
    evidence = [
        _ev("E1", "Cursor", "positioning"),
        _ev("E2", "Cursor", "positioning"),
    ]
    result = group_evidence_by_dimension(evidence, "Cursor")
    swot_ids = [e.evidence_id for e in result["swot"]]
    assert len(swot_ids) == len(set(swot_ids))


def test_empty_evidence_returns_empty_dimensions() -> None:
    result = group_evidence_by_dimension([], "Cursor")
    for dim in DIMENSIONS:
        assert result[dim] == []
