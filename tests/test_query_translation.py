from __future__ import annotations


def test_has_chinese() -> None:
    from cs_mvp.tools.search import _has_chinese

    assert _has_chinese("AI 编程") is True
    assert _has_chinese("AI coding") is False
    assert _has_chinese("") is False


def test_search_adds_english_query_for_chinese_input(monkeypatch) -> None:
    from cs_mvp.tools import search as search_mod

    call_count = [0]

    def fake_call(client, q, max_r):
        call_count[0] += 1
        return []

    monkeypatch.setattr(search_mod, "_call_tavily", fake_call)
    monkeypatch.setattr(search_mod, "_client", lambda: None)
    monkeypatch.setattr(
        search_mod,
        "_translate_query_to_english",
        lambda q: "AI coding IDE comparison",
    )

    search_mod.search("AI 编程 IDE", "Cursor")

    # 4 固定查询 + 翻译成功后的 2 条英文查询 = 6
    assert call_count[0] == 6


def test_search_no_english_query_for_english_input(monkeypatch) -> None:
    from cs_mvp.tools import search as search_mod

    call_count = [0]

    def fake_call(client, q, max_r):
        call_count[0] += 1
        return []

    def should_not_call(q):
        raise AssertionError("translate should not be called for English query")

    monkeypatch.setattr(search_mod, "_call_tavily", fake_call)
    monkeypatch.setattr(search_mod, "_client", lambda: None)
    monkeypatch.setattr(search_mod, "_translate_query_to_english", should_not_call)

    search_mod.search("AI coding IDE", "Cursor")

    # 英文查询：4 条固定查询，不触发翻译
    assert call_count[0] == 4


def test_translate_failure_falls_back_to_two_queries(monkeypatch) -> None:
    from cs_mvp.tools import search as search_mod

    call_count = [0]

    def fake_call(client, q, max_r):
        call_count[0] += 1
        return []

    monkeypatch.setattr(search_mod, "_call_tavily", fake_call)
    monkeypatch.setattr(search_mod, "_client", lambda: None)
    monkeypatch.setattr(search_mod, "_translate_query_to_english", lambda q: None)

    search_mod.search("AI 编程", "Cursor")

    # 翻译失败时只有 4 条固定查询
    assert call_count[0] == 4
