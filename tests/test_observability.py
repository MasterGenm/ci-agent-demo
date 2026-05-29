from unittest.mock import patch

from cs_mvp.observability import (
    get_langfuse_callback,
    get_langfuse_metadata,
    is_langfuse_enabled,
)


class FakeObservation:
    def __init__(self) -> None:
        self.ended = False

    def end(self, **kwargs):
        self.ended = True
        return self


class FakeLangfuse:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.flushed = False

    def trace(self, **kwargs):
        return FakeObservation()

    def span(self, **kwargs):
        return FakeObservation()

    def generation(self, **kwargs):
        return FakeObservation()

    def flush(self):
        self.flushed = True


def test_langfuse_disabled_when_env_missing(monkeypatch):
    monkeypatch.delenv("LANGFUSE_ENABLED", raising=False)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    assert is_langfuse_enabled() is False
    assert get_langfuse_callback() is None


def test_langfuse_disabled_when_flag_explicitly_false(monkeypatch):
    monkeypatch.setenv("LANGFUSE_ENABLED", "0")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    assert is_langfuse_enabled() is False
    assert get_langfuse_callback() is None


def test_langfuse_enabled_returns_callback_from_patched_sdk(monkeypatch):
    monkeypatch.delenv("LANGFUSE_ENABLED", raising=False)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    with patch(
        "cs_mvp.observability.langfuse_handler._langfuse_client_cls",
        return_value=FakeLangfuse,
    ):
        assert is_langfuse_enabled() is True
        callback = get_langfuse_callback()
        assert callback is not None
        assert callback.client.kwargs["host"] == "https://cloud.langfuse.com"


def test_langfuse_init_failure_returns_none(monkeypatch):
    monkeypatch.delenv("LANGFUSE_ENABLED", raising=False)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    with patch(
        "cs_mvp.observability.langfuse_handler._langfuse_client_cls",
        side_effect=RuntimeError("boom"),
    ):
        assert get_langfuse_callback() is None


def test_langfuse_metadata_has_stable_fields():
    metadata = get_langfuse_metadata()

    assert metadata["cs_mvp_version"] == "v1.5.0"
    assert metadata["schema_version"] == "1.2.0"
    assert metadata["observability"] == "langfuse-cloud-optional"


def test_langfuse_callback_records_chain_events(monkeypatch):
    monkeypatch.delenv("LANGFUSE_ENABLED", raising=False)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    with patch(
        "cs_mvp.observability.langfuse_handler._langfuse_client_cls",
        return_value=FakeLangfuse,
    ):
        callback = get_langfuse_callback()

    callback.on_chain_start({"name": "node"}, {"input": "x"}, run_id="run-1")
    callback.on_chain_end({"output": "y"}, run_id="run-1")

    assert callback.client.flushed is True
