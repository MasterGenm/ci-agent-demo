from __future__ import annotations

from cs_mvp.agents.collector import RELIABILITY_BY_SOURCE_TYPE, real_collect
from cs_mvp.tools.fetch import FetchResult
from cs_mvp.tools.search import SearchResult


def test_reliability_score_by_source_type(monkeypatch) -> None:
    def fake_search(query: str, competitor_name: str, **kwargs):
        return [
            SearchResult(
                url="https://cursor.com",
                title="Cursor",
                snippet="official",
                score=0.01,
                source_type_guess="official_site",
            ),
            SearchResult(
                url="https://cursor.com/pricing",
                title="Cursor Pricing",
                snippet="pricing",
                score=0.01,
                source_type_guess="pricing",
            ),
            SearchResult(
                url="https://docs.cursor.com",
                title="Cursor Docs",
                snippet="docs",
                score=0.01,
                source_type_guess="docs",
            ),
            SearchResult(
                url="https://blog.cursor.com/post",
                title="Cursor Blog",
                snippet="blog",
                score=0.01,
                source_type_guess="blog",
            ),
            SearchResult(
                url="https://techcrunch.com/2025/01/01/cursor",
                title="Cursor News",
                snippet="news",
                score=0.01,
                source_type_guess="news",
            ),
        ]

    def fake_fetch(url: str):
        return FetchResult(
            url=url,
            status="fetched",
            title=url,
            raw_text="reliable source text " * 80,
            content_hash=url[-16:],
        )

    monkeypatch.setattr("cs_mvp.agents.collector.search", fake_search)
    monkeypatch.setattr("cs_mvp.agents.collector.fetch", fake_fetch)

    records = real_collect("RUN-abcdef", "Cursor", "AI IDE")
    by_type = {record.source_type: record.reliability_score for record in records}

    for source_type in ["official_site", "pricing", "docs", "blog", "news"]:
        assert by_type[source_type] == RELIABILITY_BY_SOURCE_TYPE[source_type]
