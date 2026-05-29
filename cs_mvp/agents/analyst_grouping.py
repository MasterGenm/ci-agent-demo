from __future__ import annotations

from cs_mvp.models import EvidenceItem

CLAIM_TYPE_TO_DIMENSION: dict[str, str | None] = {
    "feature": "features",
    "pricing": "pricing",
    "positioning": "positioning",
    "metric": "features",
    "other": None,
}

BASE_DIMENSIONS = ["features", "pricing", "positioning", "swot"]
INSIGHT_DIMENSIONS = ["target_users", "strategic_implications"]
DIMENSIONS = BASE_DIMENSIONS + INSIGHT_DIMENSIONS

_MAX_PER_DIMENSION = 10
_OTHER_POOL_SUPPLEMENT = 3
_SWOT_SEED_PER_SOURCE = 3


def group_evidence_by_dimension(
    evidence: list[EvidenceItem],
    competitor_name: str,
) -> dict[str, list[EvidenceItem]]:
    """把某一竞品的 evidence 切分到 4 个 dimension。

    映射规则:
    - feature / metric -> features
    - pricing -> pricing
    - positioning -> positioning
    - other -> secondary pool, 不主映射, 但补充给 features/pricing/positioning
    - swot 没有原生 claim_type, 从 positioning / metric / other 中各取前 3 条合成

    每个 dimension 上限 10 条, 按 confidence 降序裁剪。
    """
    competitor_evidence = [
        e for e in evidence if e.competitor_name == competitor_name
    ]
    by_dim: dict[str, list[EvidenceItem]] = {d: [] for d in DIMENSIONS}

    other_pool: list[EvidenceItem] = []
    metric_pool: list[EvidenceItem] = []

    for e in competitor_evidence:
        target = CLAIM_TYPE_TO_DIMENSION.get(e.claim_type)
        if target is None:
            other_pool.append(e)
        else:
            by_dim[target].append(e)
        if e.claim_type == "metric":
            metric_pool.append(e)

    # swot 从 positioning / metric / other 合成(去重保序)
    swot_seed = (
        by_dim["positioning"][:_SWOT_SEED_PER_SOURCE]
        + metric_pool[:_SWOT_SEED_PER_SOURCE]
        + other_pool[:_SWOT_SEED_PER_SOURCE]
    )
    seen_ids: set[str] = set()
    for e in swot_seed:
        if e.evidence_id in seen_ids:
            continue
        by_dim["swot"].append(e)
        seen_ids.add(e.evidence_id)

    # other_pool 作为 secondary 补充给 base 维度
    for dim in ("features", "pricing", "positioning"):
        existing_ids = {e.evidence_id for e in by_dim[dim]}
        for e in other_pool:
            if e.evidence_id in existing_ids:
                continue
            by_dim[dim].append(e)
            existing_ids.add(e.evidence_id)
            if len(by_dim[dim]) >= _MAX_PER_DIMENSION + _OTHER_POOL_SUPPLEMENT:
                break

    for dim in BASE_DIMENSIONS:
        by_dim[dim].sort(key=lambda x: x.confidence or 0.0, reverse=True)
        by_dim[dim] = by_dim[dim][:_MAX_PER_DIMENSION]

    return by_dim
