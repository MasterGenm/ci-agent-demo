from __future__ import annotations

from cs_mvp.agents.collector import real_collect
from cs_mvp.cli import _parse_competitors
from cs_mvp.tools.fetch import FetchResult


def test_parse_competitors_with_seed_urls() -> None:
    competitors = _parse_competitors("Mem|seed=https://mem.ai,https://mem.ai/pricing")

    assert competitors[0].name == "Mem"
    assert competitors[0].seed_urls == ["https://mem.ai", "https://mem.ai/pricing"]
    assert competitors[0].exclude_keywords == []


def test_parse_competitors_with_seed_and_exclude() -> None:
    competitors = _parse_competitors("Mem|seed=https://mem.ai|memory card;memory foam")

    assert competitors[0].name == "Mem"
    assert competitors[0].seed_urls == ["https://mem.ai"]
    assert competitors[0].exclude_keywords == ["memory card", "memory foam"]


def test_parse_competitors_with_mixed_seed_entry() -> None:
    competitors = _parse_competitors(
        "Notion,Evernote,Mem|seed=https://mem.ai,https://mem.ai/about"
    )

    assert [c.name for c in competitors] == ["Notion", "Evernote", "Mem"]
    assert competitors[2].seed_urls == ["https://mem.ai", "https://mem.ai/about"]


def test_real_collect_with_seed_urls_skips_tavily(monkeypatch) -> None:
    def fake_search(*args, **kwargs):
        raise AssertionError("Tavily search should not be called when seed_urls provided")

    def fake_fetch(url: str):
        return FetchResult(
            url=url,
            status="fetched",
            title="Mem.ai",
            raw_text="some real mem content " * 50,
            content_hash="abcdef0123456789",
        )

    monkeypatch.setattr("cs_mvp.agents.collector.search", fake_search)
    monkeypatch.setattr("cs_mvp.agents.collector.fetch", fake_fetch)

    records = real_collect(
        "RUN-test",
        "Mem",
        "AI notes",
        seed_urls=["https://mem.ai/about", "https://mem.ai/pricing"],
    )

    assert len(records) == 2
    assert all(record.fetch_status == "fetched" for record in records)
    assert records[0].url == "https://mem.ai/about"


def test_real_collect_seed_retries_get_mem_for_mem_ai_spa(monkeypatch) -> None:
    calls: list[str] = []

    def fake_search(*args, **kwargs):
        raise AssertionError("Tavily search should not be called when seed_urls provided")

    def fake_fetch(url: str):
        calls.append(url)
        if url == "https://mem.ai/pricing":
            return FetchResult(
                url=url,
                status="empty",
                failure_reason="too_short",
                title="Mem",
                raw_text="Your browser needs an update.",
            )
        return FetchResult(
            url=url,
            status="fetched",
            title="Mem Pricing",
            raw_text="Mem Pro Unlimited costs $12/month and includes unlimited notes. " * 20,
            content_hash="abcdef0123456789",
        )

    monkeypatch.setattr("cs_mvp.agents.collector.search", fake_search)
    monkeypatch.setattr("cs_mvp.agents.collector.fetch", fake_fetch)

    records = real_collect(
        "RUN-test",
        "Mem",
        "AI notes",
        seed_urls=["https://mem.ai/pricing"],
    )

    assert calls == ["https://mem.ai/pricing", "https://get.mem.ai/pricing"]
    assert records[0].fetch_status == "fetched"
    assert records[0].url == "https://get.mem.ai/pricing"
