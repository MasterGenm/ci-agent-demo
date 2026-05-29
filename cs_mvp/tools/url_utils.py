from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse, urlunparse

if TYPE_CHECKING:
    from cs_mvp.tools.search import SearchResult

OFFICIAL_HINTS = {"docs", "pricing", "features", "product", "blog"}
JUNK_DOMAINS = {
    "reddit.com",
    "quora.com",
    "youtube.com",
    "facebook.com",
    "twitter.com",
    "x.com",
}


def normalize_url_key(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            "",
            "",
            "",
        )
    )


def classify_source_type(url: str, competitor_name: str) -> str:
    """Infer source_type from URL shape."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if "/pricing" in path or "pricing" in host:
        return "pricing"
    if "/docs" in path or host.startswith("docs."):
        return "docs"
    if "/blog" in path or host.startswith("blog."):
        return "blog"
    if competitor_name.lower() in host:
        return "official_site"
    if any(news in host for news in ["techcrunch", "venturebeat", "theverge", "wired"]):
        return "news"
    return "other"


def is_junk(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(junk in host for junk in JUNK_DOMAINS)


def rerank_results(results: list["SearchResult"], competitor_name: str) -> list["SearchResult"]:
    """Deterministic rerank: official/docs/pricing first, junk domains later."""

    def priority(result: "SearchResult") -> tuple[int, int, int, float]:
        type_rank = {
            "official_site": 0,
            "pricing": 1,
            "docs": 2,
            "blog": 3,
            "news": 4,
            "other": 5,
        }.get(result.source_type_guess, 5)
        name_in_title = 0 if competitor_name.lower() in result.title.lower() else 1
        junk_penalty = 10 if is_junk(result.url) else 0
        return (type_rank, name_in_title, junk_penalty, -result.score)

    return sorted(results, key=priority)


def dedupe_urls(urls: list[str]) -> list[str]:
    """Deduplicate URLs within a run, removing trailing slash and fragment."""
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        key = normalize_url_key(url)
        if key in seen:
            continue
        seen.add(key)
        out.append(url)
    return out
