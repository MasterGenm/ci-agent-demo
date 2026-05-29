from __future__ import annotations

import logging
import os

from langchain_core.language_models.chat_models import BaseChatModel

logger = logging.getLogger(__name__)


def get_extractor_llm() -> BaseChatModel:
    """根据 LLM_PROVIDER 返回 LangChain ChatModel。

    支持两类 provider:
    - anthropic: 走 ChatAnthropic,可通过 ANTHROPIC_BASE_URL 切换到兼容代理
    - openai:    走 ChatOpenAI,通过 OPENAI_BASE_URL 切换到任意 OpenAI 兼容端点
                 (DeepSeek / 智谱 / Moonshot / 火山方舟 / OpenRouter 等)

    模型名通过 EXTRACTOR_MODEL 指定。
    """
    provider = os.getenv("LLM_PROVIDER", "anthropic").lower()
    model = os.getenv("EXTRACTOR_MODEL", "claude-haiku-4-5")

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL")
        if not api_key:
            raise RuntimeError(
                "LLM_PROVIDER=openai but OPENAI_API_KEY is not set"
            )
        kwargs: dict = {
            "model": model,
            "temperature": 0.0,
            "max_tokens": 4096,
            "timeout": 60.0,
            "max_retries": 0,
            "api_key": api_key,
        }
        if base_url:
            kwargs["base_url"] = base_url
        # M2 抽取任务不需要 reasoning,默认关闭 thinking。
        # 设 EXTRACTOR_ENABLE_THINKING=true 才打开(成本/延迟翻倍)。
        # 该参数对非 thinking 模型(gpt-4o-mini / qwen-plus 等)是 no-op,百炼会忽略。
        enable_thinking = os.getenv("EXTRACTOR_ENABLE_THINKING", "false").lower() == "true"
        kwargs["extra_body"] = {"enable_thinking": enable_thinking}
        return ChatOpenAI(**kwargs)

    # 默认 anthropic
    from langchain_anthropic import ChatAnthropic

    api_key = os.getenv("ANTHROPIC_API_KEY")
    base_url = os.getenv("ANTHROPIC_BASE_URL")
    if not api_key:
        raise RuntimeError(
            "LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set"
        )
    kwargs = {
        "model": model,
        "temperature": 0.0,
        "max_tokens": 4096,
        "timeout": 60.0,
        "max_retries": 0,
        "api_key": api_key,
    }
    if base_url:
        kwargs["base_url"] = base_url
    return ChatAnthropic(**kwargs)


# USD per 1M tokens. 仅用于预算估算,价格变动不影响功能正确性。
# 未列出的模型走 _FALLBACK_PRICING,会在日志里告警。
_PRICING_USD_PER_1M: dict[str, dict[str, float]] = {
    # Anthropic
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-opus-4-7": {"input": 15.00, "output": 75.00},
    # OpenAI
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    # DeepSeek
    "deepseek-chat": {"input": 0.27, "output": 1.10},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
    # 智谱 GLM
    "glm-4-plus": {"input": 0.70, "output": 0.70},
    "glm-4-air": {"input": 0.07, "output": 0.07},
    # Moonshot
    "moonshot-v1-8k": {"input": 1.70, "output": 1.70},
    "moonshot-v1-32k": {"input": 3.30, "output": 3.30},
    # 火山方舟 doubao
    "doubao-pro-32k": {"input": 0.11, "output": 0.28},
    "doubao-lite-32k": {"input": 0.04, "output": 0.11},
    "qwen3.6-plus": {"input": 0.30, "output": 0.90},
}

_FALLBACK_PRICING = {"input": 1.00, "output": 3.00}
_warned_models: set[str] = set()


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = _PRICING_USD_PER_1M.get(model)
    if pricing is None:
        if model not in _warned_models:
            logger.warning(
                "Pricing unknown for model %s, using fallback $%.2f/$%.2f per 1M tokens",
                model,
                _FALLBACK_PRICING["input"],
                _FALLBACK_PRICING["output"],
            )
            _warned_models.add(model)
        pricing = _FALLBACK_PRICING
    return (
        input_tokens * pricing["input"] + output_tokens * pricing["output"]
    ) / 1_000_000
