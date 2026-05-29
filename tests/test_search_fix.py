from __future__ import annotations

import inspect


def test_dead_domain_clause_excludes_zhihu() -> None:
    from cs_mvp.tools.search import _dead_domain_clause

    clause = _dead_domain_clause()

    assert "-site:zhuanlan.zhihu.com" in clause
    assert "-site:baike.baidu.com" in clause


def test_dead_domain_hard_filter(monkeypatch) -> None:
    from cs_mvp.tools import search as search_mod

    def fake_call(client, q, max_r):
        return [
            {
                "url": "https://zhuanlan.zhihu.com/p/123",
                "title": "Zhihu article",
                "content": "dead domain",
                "score": 0.99,
            },
            {
                "url": "https://example.com/cursor-review",
                "title": "Cursor review",
                "content": "collectable review",
                "score": 0.5,
            },
        ]

    monkeypatch.setattr(search_mod, "_client", lambda: object())
    monkeypatch.setattr(search_mod, "_call_tavily", fake_call)

    results = search_mod.search("AI IDE", "Cursor")

    assert all("zhuanlan.zhihu.com" not in item.url for item in results)
    assert any(item.url == "https://example.com/cursor-review" for item in results)


def test_max_results_default_is_10() -> None:
    from cs_mvp.tools.search import search

    signature = inspect.signature(search)

    assert signature.parameters["max_results"].default == 10


def test_queries_include_review_query(monkeypatch) -> None:
    from cs_mvp.tools import search as search_mod

    queries: list[str] = []

    def fake_call(client, q, max_r):
        queries.append(q)
        return []

    monkeypatch.setattr(search_mod, "_client", lambda: object())
    monkeypatch.setattr(search_mod, "_call_tavily", fake_call)

    search_mod.search("AI IDE", "Cursor")

    assert any("评测" in query or "review" in query for query in queries)
    assert all("-site:zhuanlan.zhihu.com" in query for query in queries)
