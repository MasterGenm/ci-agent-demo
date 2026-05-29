from __future__ import annotations

import httpx

from cs_mvp.tools.fetch import fetch


class FakeClient:
    response: httpx.Response | None = None
    error: Exception | None = None

    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, *args) -> None:
        return None

    def get(self, url: str) -> httpx.Response:
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def _response(status_code: int, text: str, url: str = "https://example.com") -> httpx.Response:
    return httpx.Response(
        status_code,
        text=text,
        request=httpx.Request("GET", url),
    )


def test_fetch_success(monkeypatch) -> None:
    body = "<html><title>Example</title><main>" + ("Useful content " * 60) + "</main></html>"
    FakeClient.response = _response(200, body)
    FakeClient.error = None
    monkeypatch.setattr("cs_mvp.tools.fetch.httpx.Client", FakeClient)

    result = fetch("https://example.com")

    assert result.status == "fetched"
    assert result.failure_reason is None
    assert result.content_hash
    assert result.title == "Example"


def test_fetch_non_200(monkeypatch) -> None:
    FakeClient.response = _response(404, "Not found")
    FakeClient.error = None
    monkeypatch.setattr("cs_mvp.tools.fetch.httpx.Client", FakeClient)

    result = fetch("https://example.com/missing")

    assert result.status == "failed"
    assert result.failure_reason == "non_200"
    assert result.http_status == 404


def test_fetch_timeout(monkeypatch) -> None:
    FakeClient.response = None
    FakeClient.error = httpx.TimeoutException("timeout")
    monkeypatch.setattr("cs_mvp.tools.fetch.httpx.Client", FakeClient)

    result = fetch("https://example.com/slow")

    assert result.status == "failed"
    assert result.failure_reason == "timeout"


def test_fetch_short_text(monkeypatch) -> None:
    body = "<html><title>Short</title><main>" + ("short text " * 25) + "</main></html>"
    FakeClient.response = _response(200, body)
    FakeClient.error = None
    monkeypatch.setattr("cs_mvp.tools.fetch.httpx.Client", FakeClient)

    result = fetch("https://example.com/short")

    assert result.status == "empty"
    assert result.failure_reason == "too_short"
