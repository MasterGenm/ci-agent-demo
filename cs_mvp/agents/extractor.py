from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from cs_mvp.models import EvidenceItem, SourceRecord
from cs_mvp.tools.chunker import TextChunk, chunk_source, estimate_tokens
from cs_mvp.tools.llm import estimate_cost, get_extractor_llm

logger = logging.getLogger(__name__)


class LLMEvidence(BaseModel):
    competitor_name: str
    claim_type: str = Field(pattern=r"^(feature|pricing|positioning|metric|other)$")
    quote: str = Field(min_length=20, max_length=800)
    normalized_fact: str = Field(min_length=5, max_length=500)
    confidence: float = Field(ge=0.3, le=0.95)


class LLMEvidenceList(BaseModel):
    items: list[LLMEvidence] = Field(default_factory=list, max_length=5)


_WS_RE = re.compile(r"\s+")


def _normalize_for_match(text: str) -> str:
    return _WS_RE.sub(" ", text or "").strip().lower()


def quote_in_raw(quote: str, raw_text: str) -> bool:
    return _normalize_for_match(quote) in _normalize_for_match(raw_text)


def load_prompt() -> str:
    return (
        Path(__file__).resolve().parent.parent / "prompts" / "extractor.txt"
    ).read_text(encoding="utf-8")


def _json_dump(data: Any) -> str:
    if isinstance(data, BaseModel):
        return data.model_dump_json()
    return str(data)


def _parse_structured_result(result: Any) -> LLMEvidenceList:
    if isinstance(result, LLMEvidenceList):
        return result
    # 部分供应商(如 DashScope 的 qwen)在 json_object 模式下会返回裸数组
    # [{...}, {...}] 而不是 {"items": [...]}。这里宽容兼容。
    if isinstance(result, list):
        return LLMEvidenceList.model_validate({"items": result})
    if isinstance(result, dict):
        if "items" not in result and any(
            k in result for k in ("competitor_name", "claim_type", "quote")
        ):
            # 返回了单个 evidence 对象而非列表
            return LLMEvidenceList.model_validate({"items": [result]})
        return LLMEvidenceList.model_validate(result)
    return LLMEvidenceList.model_validate_json(_json_dump(result))


def _call_llm_for_chunk(
    llm: Any,
    prompt_template: str,
    source: SourceRecord,
    chunk: TextChunk,
) -> tuple[LLMEvidenceList | None, str | None, int, int]:
    structured = llm.with_structured_output(LLMEvidenceList, method="json_mode")
    # 用 str.replace 而不是 str.format,避免 prompt 里的 JSON 示例 {} 被误当占位符
    prompt = (
        prompt_template
        .replace("{competitor_name}", source.competitor_name)
        .replace("{source_type}", source.source_type or "other")
        .replace("{chunk_id}", chunk.chunk_id)
        .replace("{chunk_text}", chunk.text)
    )
    input_tokens = estimate_tokens(prompt)

    for attempt in (1, 2):
        try:
            result = _parse_structured_result(structured.invoke(prompt))
            output_tokens = estimate_tokens(result.model_dump_json())
            return result, None, input_tokens, output_tokens
        except (ValidationError, ValueError) as exc:
            err = f"schema_invalid: {exc}"
            if attempt == 2:
                return None, err, input_tokens, 0
            prompt = (
                prompt
                + "\n\nPrevious output failed schema validation. "
                + "Return a valid EvidenceItemList only."
            )
        except Exception as exc:  # noqa: BLE001
            err = f"llm_error: {exc.__class__.__name__}: {exc}"
            if attempt == 2:
                return None, err, input_tokens, 0
            prompt = prompt + "\n\nPrevious call failed. Retry once."

    return None, "unreachable", input_tokens, 0


def real_extract(
    run_id: str,
    sources: list[SourceRecord],
    max_concurrency: int = 4,
    max_cost_usd: float = 2.0,
) -> tuple[list[EvidenceItem], list[dict[str, Any]], dict[str, Any]]:
    llm = get_extractor_llm()
    model_name = (
        getattr(llm, "model", None)
        or getattr(llm, "model_name", None)
        or "claude-haiku-4-5"
    )
    prompt_template = load_prompt()
    run_suffix = run_id[-6:]

    priority = {"official_site": 0, "pricing": 0, "docs": 1, "blog": 2, "news": 3}
    valid_sources = [
        source
        for source in sources
        if (source.raw_text or "") and source.fetch_status == "fetched"
    ]
    valid_sources.sort(key=lambda s: priority.get(s.source_type or "other", 4))

    work: list[tuple[SourceRecord, TextChunk]] = []
    for source in valid_sources:
        for chunk in chunk_source(source.source_id, source.raw_text or ""):
            work.append((source, chunk))

    est_input_tokens = sum(chunk.estimated_tokens for _, chunk in work) + 400 * len(work)
    est_output_tokens = 800 * len(work)
    est_cost = estimate_cost(model_name, est_input_tokens, est_output_tokens)
    logger.info(
        "Extractor budget estimate: $%.3f for %d chunks", est_cost, len(work)
    )

    raw_results: list[
        tuple[SourceRecord, TextChunk, LLMEvidenceList | None, str | None, int, int]
    ] = []
    accumulated_cost = 0.0
    budget_exhausted = False

    def task(
        source: SourceRecord, chunk: TextChunk
    ) -> tuple[SourceRecord, TextChunk, LLMEvidenceList | None, str | None, int, int]:
        parsed, err, in_tokens, out_tokens = _call_llm_for_chunk(
            llm, prompt_template, source, chunk
        )
        return source, chunk, parsed, err, in_tokens, out_tokens

    with ThreadPoolExecutor(max_workers=max(1, max_concurrency)) as pool:
        futures = [pool.submit(task, source, chunk) for source, chunk in work]
        for future in as_completed(futures):
            try:
                source, chunk, parsed, err, in_tokens, out_tokens = future.result()
            except Exception as exc:  # noqa: BLE001
                failures = [
                    {
                        "source_id": "unknown",
                        "chunk_id": "unknown",
                        "error": f"worker_error: {exc.__class__.__name__}: {exc}",
                        "stage": "llm",
                    }
                ]
                stats = {
                    "total_chunks": len(work),
                    "pass_chunks": 0,
                    "schema_pass_rate": 0.0,
                    "quote_match_rate": 0.0,
                    "duplicate_rate": 0.0,
                    "llm_cost_usd": round(accumulated_cost, 4),
                    "max_cost_usd": max_cost_usd,
                    "model": model_name,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "budget_exhausted": budget_exhausted,
                }
                return [], failures, stats

            accumulated_cost += estimate_cost(model_name, in_tokens, out_tokens)
            raw_results.append((source, chunk, parsed, err, in_tokens, out_tokens))
            if accumulated_cost >= max_cost_usd * 1.5:
                budget_exhausted = True
                for pending in futures:
                    pending.cancel()
                break

    failures: list[dict[str, Any]] = []
    evidence: list[EvidenceItem] = []
    seen_keys: set[tuple[str, str]] = set()
    pass_chunks = 0
    quote_match_count = 0
    total_emitted = 0
    duplicate_count = 0
    input_tokens_total = 0
    output_tokens_total = 0

    for source, chunk, parsed, err, in_tokens, out_tokens in raw_results:
        input_tokens_total += in_tokens
        output_tokens_total += out_tokens
        if parsed is None:
            failures.append(
                {
                    "source_id": source.source_id,
                    "chunk_id": chunk.chunk_id,
                    "error": err or "unknown",
                    "stage": "schema",
                }
            )
            continue

        pass_chunks += 1
        for item in parsed.items:
            total_emitted += 1
            if not quote_in_raw(item.quote, source.raw_text or ""):
                failures.append(
                    {
                        "source_id": source.source_id,
                        "chunk_id": chunk.chunk_id,
                        "error": "quote_not_in_raw_text",
                        "stage": "quote_match",
                        "quote_preview": item.quote[:120],
                    }
                )
                continue
            if not 50 <= len(item.quote) <= 500:
                failures.append(
                    {
                        "source_id": source.source_id,
                        "chunk_id": chunk.chunk_id,
                        "error": f"quote_length_out_of_range:{len(item.quote)}",
                        "stage": "quote_length",
                    }
                )
                continue

            quote_match_count += 1
            normalized_fact = item.normalized_fact.strip()
            key = (item.competitor_name.strip(), normalized_fact)
            if key in seen_keys:
                duplicate_count += 1
                continue
            seen_keys.add(key)

            evidence.append(
                EvidenceItem(
                    evidence_id=f"E-{run_suffix}-{len(evidence) + 1:03d}",
                    source_id=source.source_id,
                    competitor_name=item.competitor_name,
                    claim_type=item.claim_type,  # type: ignore[arg-type]
                    quote=item.quote,
                    normalized_fact=normalized_fact,
                    confidence=item.confidence,
                    extracted_at=datetime.utcnow(),
                    source_chunk_index=chunk.chunk_index,
                )
            )

    stats = {
        "total_chunks": len(work),
        "pass_chunks": pass_chunks,
        "schema_pass_rate": round(pass_chunks / len(work), 3) if work else 0.0,
        "quote_match_rate": round(quote_match_count / total_emitted, 3)
        if total_emitted
        else 0.0,
        "duplicate_rate": round(duplicate_count / total_emitted, 3)
        if total_emitted
        else 0.0,
        "llm_cost_usd": round(accumulated_cost, 4),
        "max_cost_usd": max_cost_usd,
        "model": model_name,
        "input_tokens": input_tokens_total,
        "output_tokens": output_tokens_total,
        "budget_exhausted": budget_exhausted,
        "estimated_cost_usd": round(est_cost, 4),
    }
    return evidence, failures, stats


def mock_extract(source: SourceRecord, index: int | None = None) -> EvidenceItem:
    run_suffix = source.run_id.split("-")[-1][:6] if source.run_id else "000000"
    evidence_id = (
        f"E-{run_suffix}-{index:03d}" if index is not None else f"E-{source.source_id}"
    )
    return EvidenceItem(
        evidence_id=evidence_id,
        source_id=source.source_id,
        competitor_name=source.competitor_name,
        claim_type="feature" if source.source_type == "official_site" else "pricing",
        quote=source.raw_text or "",
        normalized_fact=f"{source.competitor_name} core fact (mock)",
        confidence=0.8,
        source_chunk_index=0,
    )
