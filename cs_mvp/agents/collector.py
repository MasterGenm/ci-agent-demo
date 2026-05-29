from __future__ import annotations

import hashlib
from urllib.parse import urlparse, urlunparse

from cs_mvp.models import SourceRecord
from cs_mvp.tools.fetch import FetchResult, fetch
from cs_mvp.tools.search import SearchResult, search
from cs_mvp.tools.url_utils import (
    classify_source_type,
    dedupe_urls,
    normalize_url_key,
    rerank_results,
)

RELIABILITY_BY_SOURCE_TYPE: dict[str, float] = {
    "official_site": 0.95,
    "pricing": 0.90,
    "docs": 0.85,
    "blog": 0.70,
    "news": 0.60,
    "other": 0.50,
}


def mock_collect(run_id: str, competitor_name: str) -> list[SourceRecord]:
    prefix = competitor_name[:3].upper()
    return [
        SourceRecord(
            source_id=f"S-{prefix}-001",
            run_id=run_id,
            competitor_name=competitor_name,
            url=f"https://mock-{competitor_name.lower()}.example.com",
            title=f"{competitor_name} 官网（mock）",
            source_type="official_site",
            raw_text=(
                f"{competitor_name} 是一款 AI 编程助手，支持代码补全和对话式编程，"
                f"支持多语言开发。{competitor_name} Pro 版定价 $20/月。"
                f"{competitor_name} 定位为开发者 AI 助手。"
                f"{competitor_name} 的优势是生态集成，劣势是价格偏高。"
            ),
            reliability_score=0.8,
            fetch_status="fetched",
            raw_text_length=120,
        ),
        SourceRecord(
            source_id=f"S-{prefix}-002",
            run_id=run_id,
            competitor_name=competitor_name,
            url=f"https://mock-{competitor_name.lower()}.example.com/pricing",
            title=f"{competitor_name} 定价页（mock）",
            source_type="pricing",
            raw_text=(
                f"{competitor_name} 提供免费版（每月 2000 次补全）和 Pro 版"
                f"（$20/月，无限补全）。"
            ),
            reliability_score=0.9,
            fetch_status="fetched",
            raw_text_length=80,
        ),
    ]


def _source_id(run_id: str, competitor_name: str, idx: int) -> str:
    # Keep the M1 requested shape S-<run_suffix>-<nnn>, while avoiding
    # competitor-level collisions when real_collect is called per competitor.
    digest = hashlib.sha1(competitor_name.encode("utf-8")).hexdigest()
    base = int(digest[:4], 16) % 900
    return f"S-{run_id[-6:]}-{base + idx:03d}"


def _to_source_record(
    run_id: str,
    competitor_name: str,
    idx: int,
    result: SearchResult,
    fetched: FetchResult,
) -> SourceRecord:
    source_type = classify_source_type(result.url, competitor_name)
    raw_text = fetched.raw_text or ""
    return SourceRecord(
        source_id=_source_id(run_id, competitor_name, idx),
        run_id=run_id,
        competitor_name=competitor_name,
        url=fetched.url or result.url,
        title=fetched.title or result.title,
        source_type=source_type,  # type: ignore[arg-type]
        content_hash=fetched.content_hash,
        raw_text=raw_text,
        reliability_score=RELIABILITY_BY_SOURCE_TYPE.get(source_type, 0.5),
        fetch_status=fetched.status if fetched.status != "empty" else "empty",
        failure_reason=fetched.failure_reason,  # type: ignore[arg-type]
        raw_text_length=len(raw_text),
    )


def _seed_fallback_url(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host in {"mem.ai", "www.mem.ai"}:
        return urlunparse(
            (
                parsed.scheme or "https",
                "get.mem.ai",
                parsed.path,
                "",
                parsed.query,
                "",
            )
        )
    return None


def _fetch_seed_url(url: str) -> FetchResult:
    fetched = fetch(url)
    fallback_url = _seed_fallback_url(url)
    if (
        fallback_url
        and fetched.status == "empty"
        and fetched.failure_reason == "too_short"
    ):
        fallback = fetch(fallback_url)
        if fallback.status == "fetched":
            return fallback
    return fetched


def real_collect(
    run_id: str,
    competitor_name: str,
    query: str,
    exclude_keywords: list[str] | None = None,
    seed_urls: list[str] | None = None,
) -> list[SourceRecord]:
    """Tavily search -> deterministic rerank -> httpx fetch -> SourceRecord."""
    seed_urls = seed_urls or []
    if seed_urls:
        sources: list[SourceRecord] = []
        for idx, url in enumerate(seed_urls, start=1):
            fetched = _fetch_seed_url(url)
            pseudo_result = SearchResult(
                url=url,
                title=fetched.title or competitor_name,
                snippet="(seed URL provided by user)",
                score=1.0,
                source_type_guess=classify_source_type(url, competitor_name),  # type: ignore[arg-type]
            )
            sources.append(
                _to_source_record(run_id, competitor_name, idx, pseudo_result, fetched)
            )
        return sources

    results = rerank_results(
        search(query, competitor_name, exclude_keywords=exclude_keywords),
        competitor_name,
    )
    result_by_key = {normalize_url_key(result.url): result for result in results}
    selected_urls = dedupe_urls([result.url for result in results])[:6]

    sources: list[SourceRecord] = []
    for idx, url in enumerate(selected_urls, start=1):
        result = result_by_key[normalize_url_key(url)]
        fetched = fetch(url)
        source = _to_source_record(run_id, competitor_name, idx, result, fetched)
        sources.append(source)

    return sources
