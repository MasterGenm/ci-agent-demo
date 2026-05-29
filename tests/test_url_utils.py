from __future__ import annotations

from cs_mvp.tools.search import SearchResult
from cs_mvp.tools.url_utils import classify_source_type, dedupe_urls, is_junk, rerank_results


def test_classify_source_type() -> None:
    assert classify_source_type("https://cursor.com", "Cursor") == "official_site"
    assert classify_source_type("https://cursor.com/pricing", "Cursor") == "pricing"
    assert classify_source_type("https://docs.cursor.com/start", "Cursor") == "docs"
    assert classify_source_type("https://techcrunch.com/cursor-news", "Cursor") == "news"
    assert is_junk("https://reddit.com/r/example") is True


def test_rerank_results_prefers_official() -> None:
    results = [
        SearchResult(
            url="https://reddit.com/r/cursor",
            title="Cursor discussion",
            snippet="forum",
            score=0.99,
            source_type_guess="other",
        ),
        SearchResult(
            url="https://cursor.com",
            title="Cursor official",
            snippet="official",
            score=0.5,
            source_type_guess="official_site",
        ),
    ]

    ranked = rerank_results(results, "Cursor")

    assert ranked[0].url == "https://cursor.com"


def test_dedupe_urls_normalizes_trailing_slash_fragment_and_query() -> None:
    urls = [
        "https://example.com/pricing/",
        "https://example.com/pricing#plans",
        "https://example.com/pricing?utm_source=test",
        "https://example.com/docs",
    ]

    assert dedupe_urls(urls) == [
        "https://example.com/pricing/",
        "https://example.com/docs",
    ]
