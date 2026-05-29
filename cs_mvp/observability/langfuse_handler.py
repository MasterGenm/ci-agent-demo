"""v1.5 Langfuse Cloud optional integration.

Langfuse stays env-gated and fail-safe. If the required Cloud keys are absent,
or SDK initialization fails, callers receive None and the local v1.4.1 path is
unchanged.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from json import dumps
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger(__name__)

_FALSE_VALUES = {"0", "false", "no", "off"}
_MAX_PAYLOAD_CHARS = 2000


def is_langfuse_enabled() -> bool:
    """Return True only when Langfuse Cloud keys are configured."""
    explicit_flag = os.environ.get("LANGFUSE_ENABLED")
    if explicit_flag is not None and explicit_flag.strip().lower() in _FALSE_VALUES:
        return False
    return bool(
        os.environ.get("LANGFUSE_PUBLIC_KEY")
        and os.environ.get("LANGFUSE_SECRET_KEY")
    )


def _langfuse_client_cls() -> type[Any]:
    from langfuse import Langfuse

    return Langfuse


def _payload(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    try:
        text = dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = repr(value)
    if len(text) > _MAX_PAYLOAD_CHARS:
        return f"{text[:_MAX_PAYLOAD_CHARS]}..."
    return text


def _node_name(serialized: Any, fallback: str) -> str:
    if isinstance(serialized, dict):
        name = serialized.get("name")
        if isinstance(name, str) and name:
            return name
        ids = serialized.get("id")
        if isinstance(ids, list) and ids:
            return str(ids[-1])
    return fallback


def _agent_role_for_node(name: str) -> str | None:
    try:
        from cs_mvp.agents.role_cards import ROLE_CARDS
    except Exception:
        return None
    card = ROLE_CARDS.get(name)
    return card.role if card else None


def _run_key(run_id: Any) -> str:
    return str(run_id)


class LangfuseCloudCallback(BaseCallbackHandler):
    """Minimal LangChain-core callback backed by Langfuse Cloud v2 SDK."""

    def __init__(self, *, client: Any, metadata: dict[str, str]) -> None:
        super().__init__()
        self.client = client
        self.metadata = metadata
        self._trace_ids: dict[str, str] = {}
        self._observations: dict[str, Any] = {}

    def _trace_id(self, run_id: Any, parent_run_id: Any | None) -> str:
        run_key = _run_key(run_id)
        parent_key = _run_key(parent_run_id) if parent_run_id else None
        if parent_key and parent_key in self._trace_ids:
            trace_id = self._trace_ids[parent_key]
        else:
            trace_id = run_key
            self._safe(
                lambda: self.client.trace(
                    id=trace_id,
                    name="cs-mvp",
                    metadata=self.metadata,
                    tags=["cs-mvp", "v1.5"],
                    timestamp=datetime.now(timezone.utc),
                )
            )
        self._trace_ids[run_key] = trace_id
        return trace_id

    def _parent_observation_id(self, parent_run_id: Any | None) -> str | None:
        if parent_run_id is None:
            return None
        parent_key = _run_key(parent_run_id)
        if parent_key in self._observations:
            return parent_key
        return None

    def _safe(self, fn: Any) -> Any | None:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            logger.warning("langfuse callback event failed: %s", exc)
            return None

    def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        *,
        run_id: Any,
        parent_run_id: Any | None = None,
        **kwargs: Any,
    ) -> None:
        run_key = _run_key(run_id)
        trace_id = self._trace_id(run_id, parent_run_id)
        node_name = _node_name(serialized, "chain")
        metadata = {"kind": "chain", **self.metadata}
        agent_role = _agent_role_for_node(node_name)
        if agent_role:
            metadata["agent_role"] = agent_role

        span = self._safe(
            lambda: self.client.span(
                id=run_key,
                trace_id=trace_id,
                parent_observation_id=self._parent_observation_id(parent_run_id),
                name=node_name,
                input=_payload(inputs),
                start_time=datetime.now(timezone.utc),
                metadata=metadata,
            )
        )
        if span is not None:
            self._observations[run_key] = span

    def on_chain_end(
        self,
        outputs: dict[str, Any],
        *,
        run_id: Any,
        **kwargs: Any,
    ) -> None:
        run_key = _run_key(run_id)
        span = self._observations.get(run_key)
        if span is not None:
            self._safe(
                lambda: span.end(
                    output=_payload(outputs),
                    end_time=datetime.now(timezone.utc),
                )
            )
        self._safe(self.client.flush)

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: Any,
        **kwargs: Any,
    ) -> None:
        run_key = _run_key(run_id)
        span = self._observations.get(run_key)
        if span is not None:
            self._safe(
                lambda: span.end(
                    level="ERROR",
                    status_message=str(error),
                    end_time=datetime.now(timezone.utc),
                )
            )
        self._safe(self.client.flush)

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: Any,
        parent_run_id: Any | None = None,
        **kwargs: Any,
    ) -> None:
        run_key = _run_key(run_id)
        trace_id = self._trace_id(run_id, parent_run_id)

        generation = self._safe(
            lambda: self.client.generation(
                id=run_key,
                trace_id=trace_id,
                parent_observation_id=self._parent_observation_id(parent_run_id),
                name=_node_name(serialized, "llm"),
                input=_payload(prompts),
                start_time=datetime.now(timezone.utc),
                metadata={"kind": "llm", **self.metadata},
            )
        )
        if generation is not None:
            self._observations[run_key] = generation

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: Any,
        **kwargs: Any,
    ) -> None:
        run_key = _run_key(run_id)
        generation = self._observations.get(run_key)
        if generation is not None:
            self._safe(
                lambda: generation.end(
                    output=_payload(response),
                    end_time=datetime.now(timezone.utc),
                )
            )
        self._safe(self.client.flush)

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: Any,
        **kwargs: Any,
    ) -> None:
        run_key = _run_key(run_id)
        generation = self._observations.get(run_key)
        if generation is not None:
            self._safe(
                lambda: generation.end(
                    level="ERROR",
                    status_message=str(error),
                    end_time=datetime.now(timezone.utc),
                )
            )
        self._safe(self.client.flush)


def get_langfuse_callback() -> Any | None:
    """Build a Langfuse LangChain callback handler when configured.

    Returning None means Langfuse is disabled or unavailable; the caller should
    keep running with the local artifact trace only.
    """
    if not is_langfuse_enabled():
        return None

    try:
        client_cls = _langfuse_client_cls()
        handler = LangfuseCloudCallback(
            client=client_cls(
                public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
                secret_key=os.environ["LANGFUSE_SECRET_KEY"],
                host=os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"),
            ),
            metadata=get_langfuse_metadata(),
        )
        logger.info(
            "langfuse callback enabled (host=%s)",
            os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
        return handler
    except ImportError:
        logger.warning("langfuse not installed; skipping observability")
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("langfuse init failed: %s; falling back to local trace only", exc)
        return None


def get_langfuse_metadata(version: str = "v1.5.0") -> dict[str, str]:
    """Return stable metadata attached to Langfuse traces."""
    return {
        "cs_mvp_version": version,
        "schema_version": "1.2.0",
        "observability": "langfuse-cloud-optional",
    }
