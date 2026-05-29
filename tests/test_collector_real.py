from __future__ import annotations

import re

from cs_mvp.agents.collector import real_collect
from cs_mvp.tools.fetch import FetchResult
from cs_mvp.tools.search import SearchResult


def test_real_collect_converts_search_and_fetch_results(monkeypatch) -> None:
    def fake_search(query: str, competitor_name: str, **kwargs):
        return [
            SearchResult(
                url="https://cursor.com",
                title="Cursor",
                snippet="official",
                score=0.9,
                source_type_guess="official_site",
            ),
            SearchResult(
                url="https://cursor.com/pricing",
                title="Cursor Pricing",
                snippet="pricing",
                score=0.8,
                source_type_guess="pricing",
            ),
            SearchResult(
                url="https://cursor.com/blog",
                title="Cursor Blog",
                snippet="blog",
                score=0.7,
                source_type_guess="blog",
            ),
        ]

    def fake_fetch(url: str):
        if url.endswith("/pricing"):
            return FetchResult(url=url, status="failed", failure_reason="non_200", http_status=404)
        if url.endswith("/blog"):
            return FetchResult(url=url, status="empty", failure_reason="too_short", raw_text="short")
        return FetchResult(
            url=url,
            status="fetched",
            title="Cursor",
            raw_text="long text " * 80,
            content_hash="abcdef1234567890",
            http_status=200,
        )

    monkeypatch.setattr("cs_mvp.agents.collector.search", fake_search)
    monkeypatch.setattr("cs_mvp.agents.collector.fetch", fake_fetch)

    records = real_collect("RUN-123456", "Cursor", "AI IDE")

    assert len(records) == 3
    assert all(re.match(r"^S-123456-\d{3}$", item.source_id) for item in records)
    assert [item.fetch_status for item in records] == ["fetched", "failed", "empty"]
    assert records[0].raw_text_length >= 500
    assert records[1].failure_reason == "non_200"
    assert records[2].failure_reason == "too_short"


def test_real_collect_failure_reason_is_set_for_failures(monkeypatch) -> None:
    def fake_search(query: str, competitor_name: str, **kwargs):
        return [
            SearchResult(
                url="https://cursor.com/pricing",
                title="Cursor Pricing",
                snippet="pricing",
                score=0.8,
                source_type_guess="pricing",
            )
        ]

    def fake_fetch(url: str):
        return FetchResult(url=url, status="failed", failure_reason="timeout")

    monkeypatch.setattr("cs_mvp.agents.collector.search", fake_search)
    monkeypatch.setattr("cs_mvp.agents.collector.fetch", fake_fetch)

    records = real_collect("RUN-abcdef", "Cursor", "AI IDE")

    assert records[0].fetch_status == "failed"
    assert records[0].failure_reason is not None
