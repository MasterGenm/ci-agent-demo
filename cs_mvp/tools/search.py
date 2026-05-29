from __future__ import annotations

import os
import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel
from tavily import TavilyClient

from cs_mvp.tools.url_utils import classify_source_type, rerank_results

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_DEAD_DOMAINS = [
    "zhuanlan.zhihu.com",
    "www.zhihu.com",
    "baike.baidu.com",
    "www.pingwest.com",
    "apps.microsoft.com",
    "weixin.qq.com",
    "mp.weixin.qq.com",
    "m.weixin.qq.com",
]
_DEAD_DOMAINS_SET = frozenset(_DEAD_DOMAINS)


class SearchResult(BaseModel):
    url: str
    title: str
    snippet: str
    score: float
    source_type_guess: Literal["official_site", "pricing", "docs", "blog", "news", "other"]


def _client() -> TavilyClient:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is required for M1 real collector")
    return TavilyClient(api_key=api_key)


def _call_tavily(client: TavilyClient, query: str, max_results: int) -> list[dict]:
    response = client.search(
        query=query,
        search_depth="basic",
        max_results=max_results,
        include_answer=False,
        include_raw_content=False,
    )
    return list(response.get("results", []))


def _has_chinese(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def _translate_query_to_english(query: str) -> str | None:
    """Translate a Chinese product-research query into concise English keywords."""
    try:
        from cs_mvp.tools.llm import get_extractor_llm

        llm = get_extractor_llm()
        prompt = (
            "Translate the following Chinese product research query to a concise "
            "English search query (maximum 20 words). Output ONLY the English text, "
            "no quotes, no explanation.\n\n"
            f"Chinese query: {query}\n\nEnglish query:"
        )
        response = llm.invoke(prompt)
        content = getattr(response, "content", None)
        if isinstance(content, list):
            text = " ".join(
                str(item.get("text", item)) if isinstance(item, dict) else str(item)
                for item in content
            )
        else:
            text = content or str(response)
        text = str(text).strip().strip('"').strip("'")
        if not text or len(text) > 200:
            return None
        return text
    except Exception:
        return None


def _exclude_clause(exclude_keywords: list[str]) -> str:
    """Tavily supports basic boolean: -word excludes results containing it."""
    return " ".join(f'-"{kw}"' if " " in kw else f"-{kw}" for kw in exclude_keywords)


def _dead_domain_clause() -> str:
    """Generate Tavily -site clauses for domains known to be uncollectable."""
    return " ".join(f"-site:{domain}" for domain in _DEAD_DOMAINS)


def _hit_exclusion(text: str, exclude_keywords: list[str]) -> bool:
    if not exclude_keywords:
        return False
    lowered = text.lower()
    return any(kw.lower() in lowered for kw in exclude_keywords)


def search(
    query: str,
    competitor_name: str,
    max_results: int = 10,
    exclude_keywords: list[str] | None = None,
) -> list[SearchResult]:
    """Call Tavily search and return deterministic-reranked results.

    exclude_keywords filters ambiguous same-name products. Dead domains are
    filtered both in the Tavily query and again after results are returned.
    """
    exclude_keywords = exclude_keywords or []
    exclude_clause = _exclude_clause(exclude_keywords)
    dead_clause = _dead_domain_clause()
    client = _client()
    queries = [
        f"{competitor_name} {query} {exclude_clause} {dead_clause}".strip(),
        f"{competitor_name} 定价 收费 功能 {exclude_clause} {dead_clause}".strip(),
        f"{competitor_name} 官网 产品介绍 {exclude_clause} {dead_clause}".strip(),
        f"{competitor_name} 评测 对比 教程 {exclude_clause} {dead_clause}".strip(),
    ]
    if _has_chinese(query):
        english_query = _translate_query_to_english(query)
        if english_query:
            queries.append(
                f"{competitor_name} {english_query} {exclude_clause} {dead_clause}".strip()
            )
            queries.append(
                f"{competitor_name} pricing features review {exclude_clause} {dead_clause}".strip()
            )

    raw_results = []
    for search_query in queries:
        raw_results.extend(_call_tavily(client, search_query, max_results))

    by_url: dict[str, SearchResult] = {}
    for item in raw_results:
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        title = str(item.get("title") or "")
        snippet = str(item.get("content") or item.get("snippet") or "")
        if _hit_exclusion(f"{url} {title} {snippet}", exclude_keywords):
            continue
        netloc = urlparse(url).netloc.lower().split(":", 1)[0]
        if netloc in _DEAD_DOMAINS_SET:
            continue
        result = SearchResult(
            url=url,
            title=title,
            snippet=snippet,
            score=float(item.get("score") or 0.0),
            source_type_guess=classify_source_type(url, competitor_name),
        )
        previous = by_url.get(url)
        if previous is None or result.score > previous.score:
            by_url[url] = result

    return rerank_results(list(by_url.values()), competitor_name)
