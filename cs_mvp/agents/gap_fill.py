from __future__ import annotations

import logging
from typing import Any

from cs_mvp import db
from cs_mvp.agents.analyst import real_analyze
from cs_mvp.agents.extractor import real_extract
from cs_mvp.models import AnalysisClaim, GraphState, SourceRecord
from cs_mvp.tools.fetch import FetchResult, fetch
from cs_mvp.tools.search import SearchResult, search
from cs_mvp.tools.url_utils import classify_source_type, dedupe_urls, normalize_url_key

logger = logging.getLogger(__name__)

GAP_FILL_DIMS = ["features", "pricing", "target_users", "positioning"]
MAX_URLS_PER_COMPETITOR = 3
MAX_GAP_FILL_ROUNDS = 1

_DIM_QUERY = {
    "features": "核心功能 产品特性 功能介绍",
    "pricing": "定价 收费 价格 套餐",
    "target_users": "目标用户 适用场景 用户群体",
    "positioning": "产品定位 品牌定位 竞争优势",
}

_RELIABILITY_BY_SOURCE_TYPE = {
    "official_site": 0.95,
    "pricing": 0.90,
    "docs": 0.85,
    "blog": 0.70,
    "news": 0.60,
    "other": 0.50,
}

_ALLOWED_FAILURE_REASONS = {
    "timeout",
    "non_200",
    "parse_empty",
    "too_short",
    "blocked",
    "duplicate",
    "unknown",
}


def _claim_value(claim: AnalysisClaim | dict[str, Any], field: str) -> Any:
    if isinstance(claim, dict):
        return claim.get(field)
    return getattr(claim, field, None)


def find_gaps(
    claims: list[AnalysisClaim],
    competitors: list[str],
) -> dict[str, list[str]]:
    """Return missing core dimensions per competitor.

    Rejected claims do not count as coverage. Cross-competitor claims without a
    competitor name also do not fill a competitor-specific matrix cell.
    """
    covered: dict[str, set[str]] = {competitor: set() for competitor in competitors}
    for claim in claims:
        if _claim_value(claim, "accepted") is False:
            continue
        competitor_name = _claim_value(claim, "competitor_name")
        dimension = _claim_value(claim, "dimension")
        if competitor_name in covered and dimension in GAP_FILL_DIMS:
            covered[str(competitor_name)].add(str(dimension))

    gaps: dict[str, list[str]] = {}
    for competitor in competitors:
        missing = [dim for dim in GAP_FILL_DIMS if dim not in covered[competitor]]
        if missing:
            gaps[competitor] = missing
    return gaps


def build_gap_queries(gaps: dict[str, list[str]]) -> dict[str, list[str]]:
    """Build at most two focused Tavily queries per competitor."""
    queries: dict[str, list[str]] = {}
    for competitor, dims in gaps.items():
        chunks = [dims[:2], dims[2:4]]
        competitor_queries = []
        for chunk in chunks:
            keywords = " ".join(_DIM_QUERY[dim] for dim in chunk if dim in _DIM_QUERY)
            if keywords:
                competitor_queries.append(f"{competitor} {keywords}")
        if competitor_queries:
            queries[competitor] = competitor_queries[:2]
    return queries


def _source_id(run_id: str, competitor_name: str, dimension: str, idx: int) -> str:
    comp_token = "".join(ch for ch in competitor_name if ch.isalnum())[:3] or "CMP"
    dim_token = dimension[:3] or "gap"
    return f"S-GAP-{run_id[-6:]}-{comp_token}-{dim_token}-{idx:03d}"


def _failure_reason(value: str | None) -> str | None:
    if not value:
        return None
    return value if value in _ALLOWED_FAILURE_REASONS else "unknown"


def _to_gap_source_record(
    *,
    run_id: str,
    competitor_name: str,
    dimension: str,
    idx: int,
    result: SearchResult,
    fetched: FetchResult,
) -> SourceRecord:
    source_type = classify_source_type(result.url, competitor_name)
    raw_text = fetched.raw_text or ""
    return SourceRecord(
        source_id=_source_id(run_id, competitor_name, dimension, idx),
        run_id=run_id,
        competitor_name=competitor_name,
        url=fetched.url or result.url,
        title=fetched.title or result.title,
        source_type=source_type,  # type: ignore[arg-type]
        content_hash=fetched.content_hash,
        raw_text=raw_text,
        reliability_score=_RELIABILITY_BY_SOURCE_TYPE.get(source_type, 0.5),
        fetch_status=fetched.status,
        failure_reason=_failure_reason(fetched.failure_reason),  # type: ignore[arg-type]
        raw_text_length=len(raw_text),
    )


def _select_gap_results(
    competitor_name: str,
    competitor_queries: list[str],
    existing_url_keys: set[str],
) -> list[SearchResult]:
    raw_results: list[SearchResult] = []
    for query in competitor_queries:
        raw_results.extend(search(query, competitor_name, max_results=5))

    by_key: dict[str, SearchResult] = {}
    for result in raw_results:
        key = normalize_url_key(result.url)
        if key in existing_url_keys or key in by_key:
            continue
        by_key[key] = result

    selected_urls = dedupe_urls([result.url for result in by_key.values()])
    selected_keys = [normalize_url_key(url) for url in selected_urls]
    return [by_key[key] for key in selected_keys[:MAX_URLS_PER_COMPETITOR] if key in by_key]


def run_gap_fill(state: GraphState) -> dict[str, Any]:
    """Run one non-blocking evidence gap-fill pass.

    Any internal failure is swallowed so the DAG can continue to QA/writer.
    """
    next_round = min(state.gap_fill_round + 1, MAX_GAP_FILL_ROUNDS)
    if state.gap_fill_round >= MAX_GAP_FILL_ROUNDS:
        return {"gap_fill_round": state.gap_fill_round}

    try:
        competitors = [competitor.name for competitor in state.task.competitors]
        gaps = find_gaps(state.claims, competitors)
        if not gaps:
            return {"gap_fill_round": next_round}

        query_map = build_gap_queries(gaps)
        existing_url_keys = {
            normalize_url_key(source.url)
            for source in state.sources
            if source.url
        }
        gap_sources: list[SourceRecord] = []

        for competitor_name, competitor_queries in query_map.items():
            selected_results = _select_gap_results(
                competitor_name,
                competitor_queries,
                existing_url_keys,
            )
            missing_dims = gaps.get(competitor_name) or ["gap"]
            for idx, result in enumerate(selected_results, start=1):
                try:
                    fetched = fetch(result.url)
                    dimension = missing_dims[min(idx - 1, len(missing_dims) - 1)]
                    source = _to_gap_source_record(
                        run_id=state.run_id,
                        competitor_name=competitor_name,
                        dimension=dimension,
                        idx=idx,
                        result=result,
                        fetched=fetched,
                    )
                    gap_sources.append(source)
                    existing_url_keys.add(normalize_url_key(source.url))
                except Exception as exc:  # noqa: BLE001
                    logger.debug("gap_fill fetch failed for %s: %s", result.url, exc)

        if not gap_sources:
            return {"gap_fill_round": next_round}

        # 写入 DB，让 finalize 的 db.list_sources_for_run() 能拿到补采来源
        for source in gap_sources:
            try:
                db.insert_source(source)
            except Exception as exc:  # noqa: BLE001
                logger.debug("gap_fill db insert_source failed: %s", exc)

        gap_evidence, _, _ = real_extract(state.run_id, gap_sources)
        if not gap_evidence:
            return {
                "gap_fill_round": next_round,
                "sources": [source.model_dump(mode="json") for source in [*state.sources, *gap_sources]],
            }

        gap_competitors = list(query_map.keys())
        gap_claims, _, _ = real_analyze(state.run_id, gap_evidence, gap_competitors)

        existing_evidence_ids = {item.evidence_id for item in state.evidence}
        merged_evidence = [
            *state.evidence,
            *[item for item in gap_evidence if item.evidence_id not in existing_evidence_ids],
        ]
        existing_claim_ids = {item.claim_id for item in state.claims}
        merged_claims = [
            *state.claims,
            *[item for item in gap_claims if item.claim_id not in existing_claim_ids],
        ]
        return {
            "gap_fill_round": next_round,
            "sources": [source.model_dump(mode="json") for source in [*state.sources, *gap_sources]],
            "evidence": [item.model_dump(mode="json") for item in merged_evidence],
            "claims": [item.model_dump(mode="json") for item in merged_claims],
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("gap_fill skipped after internal failure: %s", exc)
        return {"gap_fill_round": next_round}
