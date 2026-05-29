from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from cs_mvp.agents.analyst_grouping import (
    BASE_DIMENSIONS,
    INSIGHT_DIMENSIONS,
    group_evidence_by_dimension,
)
from cs_mvp.models import AnalysisClaim, EvidenceItem
from cs_mvp.tools.llm import estimate_cost, get_extractor_llm

logger = logging.getLogger(__name__)


# ---------- LLM 输出 schema ----------

class LLMClaim(BaseModel):
    competitor_name: str | None = None  # cross-competitor 时为 null
    dimension: str = Field(
        pattern=r"^(features|pricing|positioning|swot|target_users|strategic_implications)$"
    )
    statement: str = Field(min_length=20, max_length=240)
    evidence_ids: list[str] = Field(min_length=1, max_length=3)
    confidence: float = Field(ge=0.3, le=0.95)


class LLMClaimList(BaseModel):
    items: list[LLMClaim] = Field(default_factory=list, max_length=3)


class LLMCrossClaimList(BaseModel):
    items: list[LLMClaim] = Field(default_factory=list, max_length=2)


class LLMInsightClaim(BaseModel):
    competitor_name: str | None = None
    dimension: str
    # v1.4.1: insights claim 通常包含综合性陈述,LLM 实测易超 240 字 + 4-5 evidence,
    # 放宽到 360 / 5 以提高 Phase 3 产出率(实测 v1.4.0 仅 1/6 通过)。
    statement: str = Field(min_length=20, max_length=360)
    evidence_ids: list[str] = Field(min_length=1, max_length=5)
    confidence: float = Field(ge=0.3, le=0.95)


class LLMInsightClaimList(BaseModel):
    items: list[LLMInsightClaim] = Field(default_factory=list, max_length=4)


# ---------- 工具函数 ----------

_ENGLISH_TOKEN_RE = re.compile(r"[a-zA-Z]{3,}")
_PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


def is_bilingual(statement: str) -> bool:
    """检查 statement 是否双语。

    要求:含至少 2 个 3 字符以上英文 token。
    单一个产品名(如 "Cursor")不足以通过——必须有额外英文关键短语锚点
    才能进入下游 CitationVerifier 关键词匹配。
    """
    matches = _ENGLISH_TOKEN_RE.findall(statement or "")
    return len(matches) >= 2


def _evidence_block(evidence_list: list[EvidenceItem]) -> str:
    if not evidence_list:
        return "(无 evidence)"
    lines = []
    for e in evidence_list:
        comp = f"[{e.competitor_name}]" if e.competitor_name else ""
        quote_preview = (e.quote or "").replace("\n", " ")[:200]
        lines.append(
            f"- {e.evidence_id} {comp} ({e.claim_type}, conf={e.confidence}): "
            f"{quote_preview}"
        )
    return "\n".join(lines)


def _single_claims_block(claims: list[AnalysisClaim]) -> str:
    if not claims:
        return "(无 single-competitor claim)"
    lines = []
    for c in claims:
        ev_ids = ",".join(c.evidence_ids)
        lines.append(
            f"- [{c.competitor_name}] {c.dimension}: {c.statement} (evidence={ev_ids})"
        )
    return "\n".join(lines)


def _parse_claim_result(result: Any, schema_cls: type[BaseModel]) -> Any:
    """与 extractor 同一套兼容策略,支持 dict / list / 单 dict / Pydantic 实例。"""
    if isinstance(result, schema_cls):
        return result
    if isinstance(result, list):
        return schema_cls.model_validate({"items": result})
    if isinstance(result, dict):
        if "items" not in result and any(
            k in result for k in ("statement", "evidence_ids")
        ):
            return schema_cls.model_validate({"items": [result]})
        return schema_cls.model_validate(result)
    return schema_cls.model_validate_json(str(result))


def _render_prompt(template: str, **substitutions: str) -> str:
    """用 str.replace 替代 str.format,避免 prompt 里 JSON 示例 {} 冲突。"""
    rendered = template
    for key, value in substitutions.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def _load_prompt(name: str) -> str:
    return (_PROMPT_DIR / name).read_text(encoding="utf-8")


# ---------- 单 chunk LLM 调用(一次重试) ----------

def _call_llm(
    llm: Any,
    prompt: str,
    schema_cls: type[BaseModel],
) -> tuple[Any | None, str | None, int, int]:
    structured = llm.with_structured_output(schema_cls, method="json_mode")
    input_tokens = len(prompt) // 4  # 粗略估算

    for attempt in (1, 2):
        try:
            raw = structured.invoke(prompt)
            parsed = _parse_claim_result(raw, schema_cls)
            output_tokens = len(parsed.model_dump_json()) // 4
            return parsed, None, input_tokens, output_tokens
        except (ValidationError, ValueError) as exc:
            err = f"schema_invalid: {exc}"
            if attempt == 2:
                return None, err, input_tokens, 0
            prompt = (
                prompt
                + "\n\nPrevious output failed schema validation. "
                + "Return a valid JSON object that matches the schema exactly."
            )
        except Exception as exc:  # noqa: BLE001
            err = f"llm_error: {exc.__class__.__name__}: {exc}"
            if attempt == 2:
                return None, err, input_tokens, 0
            prompt = prompt + "\n\nPrevious call failed. Retry once."

    return None, "unreachable", input_tokens, 0


# ---------- AnalysisClaim 构建 ----------

def _to_single_claim(
    run_id: str,
    item: LLMClaim,
    counter_by_comp_dim: dict[tuple[str, str], int],
) -> AnalysisClaim:
    run_suffix = run_id[-6:]
    comp_short = (item.competitor_name or "UNK")[:3].upper()
    dim_short = item.dimension[:3].upper()
    key = (comp_short, dim_short)
    counter_by_comp_dim[key] = counter_by_comp_dim.get(key, 0) + 1
    idx = counter_by_comp_dim[key]
    return AnalysisClaim(
        claim_id=f"C-{run_suffix}-{comp_short}-{dim_short}-{idx:02d}",
        run_id=run_id,
        competitor_name=item.competitor_name,
        dimension=item.dimension,  # type: ignore[arg-type]
        statement=item.statement,
        evidence_ids=item.evidence_ids,
        confidence=item.confidence,
    )


def _to_cross_claim(
    run_id: str,
    item: LLMClaim,
    counter_by_dim: dict[str, int],
) -> AnalysisClaim:
    run_suffix = run_id[-6:]
    dim_short = item.dimension[:3].upper()
    counter_by_dim[dim_short] = counter_by_dim.get(dim_short, 0) + 1
    idx = counter_by_dim[dim_short]
    return AnalysisClaim(
        claim_id=f"C-{run_suffix}-CROSS-{dim_short}-{idx:02d}",
        run_id=run_id,
        competitor_name=None,
        dimension=item.dimension,  # type: ignore[arg-type]
        statement=item.statement,
        evidence_ids=item.evidence_ids,
        confidence=item.confidence,
    )


def _build_insights_phase(
    run_id: str,
    llm: Any,
    evidence_by_id: dict[str, EvidenceItem],
    competitor_names: list[str],
    existing_claims: list[AnalysisClaim],
    max_concurrency: int = 4,
) -> tuple[list[AnalysisClaim], list[dict[str, Any]], int, int]:
    """v1.4 Phase 3: generate lightweight business insight claims.

    This phase runs after the original single/cross analysis. It does not
    repartition evidence by dimension; each competitor gets its own evidence
    pool and can produce 0-2 target_users plus 0-2 strategic_implications claims.
    """
    prompt_template = _load_prompt("analyst_insights.txt")
    insight_dims = set(INSIGHT_DIMENSIONS)
    work: list[tuple[str, list[EvidenceItem], list[AnalysisClaim]]] = []

    for competitor in competitor_names:
        comp_evidence = [
            item
            for item in evidence_by_id.values()
            if item.competitor_name == competitor
        ]
        if not comp_evidence:
            continue
        comp_existing = [
            claim
            for claim in existing_claims
            if claim.competitor_name == competitor
        ]
        work.append((competitor, comp_evidence, comp_existing))

    def _insights_task(item):
        comp, ev_list, existing = item
        prompt = _render_prompt(
            prompt_template,
            competitor_name=comp,
            evidence_block=_evidence_block(ev_list),
            existing_claims_block=_single_claims_block(existing),
        )
        parsed, err, in_t, out_t = _call_llm(llm, prompt, LLMInsightClaimList)
        return comp, ev_list, parsed, err, in_t, out_t

    insight_claims: list[AnalysisClaim] = []
    failures: list[dict[str, Any]] = []
    counter_single: dict[tuple[str, str], int] = {}
    dimension_counts: dict[tuple[str, str], int] = {}
    input_tokens = 0
    output_tokens = 0

    with ThreadPoolExecutor(max_workers=max(1, max_concurrency)) as pool:
        futures = [pool.submit(_insights_task, w) for w in work]
        for f in as_completed(futures):
            comp, ev_list, parsed, err, in_t, out_t = f.result()
            input_tokens += in_t
            output_tokens += out_t
            if parsed is None:
                failures.append({
                    "phase": "insights",
                    "competitor": comp,
                    "error": err or "unknown",
                })
                continue

            allowed_evidence_ids = {ev.evidence_id for ev in ev_list}
            for item in parsed.items:
                if item.dimension not in insight_dims:
                    failures.append({
                        "phase": "insights",
                        "competitor": comp,
                        "error": f"dimension_mismatch:{item.dimension}",
                        "preview": item.statement[:120],
                    })
                    continue
                key = (comp, item.dimension)
                if dimension_counts.get(key, 0) >= 2:
                    failures.append({
                        "phase": "insights",
                        "competitor": comp,
                        "dimension": item.dimension,
                        "error": "dimension_cap_exceeded",
                    })
                    continue
                if not is_bilingual(item.statement):
                    failures.append({
                        "phase": "insights",
                        "competitor": comp,
                        "dimension": item.dimension,
                        "error": "monolingual_statement",
                        "preview": item.statement[:120],
                    })
                    continue
                invalid_ids = [
                    eid
                    for eid in item.evidence_ids
                    if eid not in allowed_evidence_ids
                ]
                if invalid_ids:
                    failures.append({
                        "phase": "insights",
                        "competitor": comp,
                        "dimension": item.dimension,
                        "error": f"invalid_evidence_ids:{invalid_ids}",
                        "preview": item.statement[:120],
                    })
                    continue
                if item.competitor_name and item.competitor_name != comp:
                    item.competitor_name = comp
                elif not item.competitor_name:
                    item.competitor_name = comp
                insight_claims.append(
                    _to_single_claim(run_id, item, counter_single)  # type: ignore[arg-type]
                )
                dimension_counts[key] = dimension_counts.get(key, 0) + 1

    return insight_claims, failures, input_tokens, output_tokens


# ---------- 主入口 ----------

def real_analyze(
    run_id: str,
    evidence: list[EvidenceItem],
    competitor_names: list[str],
    max_concurrency: int = 4,
) -> tuple[list[AnalysisClaim], list[dict[str, Any]], dict[str, Any]]:
    """Phase 1: 每个 (competitor, dimension) 切片生成 1-3 条 claim
    Phase 2: 对每个 dimension 做跨竞品对比, 生成 0-2 条 cross claim

    返回 (claims, failures, stats)。
    """
    llm = get_extractor_llm()
    model_name = (
        getattr(llm, "model", None)
        or getattr(llm, "model_name", None)
        or "unknown"
    )
    single_prompt_template = _load_prompt("analyst.txt")
    cross_prompt_template = _load_prompt("analyst_cross.txt")
    evidence_by_id: dict[str, EvidenceItem] = {e.evidence_id: e for e in evidence}

    failures: list[dict[str, Any]] = []
    accumulated_input = 0
    accumulated_output = 0

    # ============ Phase 1: per (competitor, dimension) ============
    work: list[tuple[str, str, list[EvidenceItem]]] = []
    for competitor in competitor_names:
        by_dim = group_evidence_by_dimension(evidence, competitor)
        for dim in BASE_DIMENSIONS:
            work.append((competitor, dim, by_dim[dim]))

    def _single_task(item):
        comp, dim, ev_list = item
        if not ev_list:
            return comp, dim, None, "no_evidence", 0, 0
        prompt = _render_prompt(
            single_prompt_template,
            competitor_name=comp,
            dimension=dim,
            evidence_block=_evidence_block(ev_list),
        )
        parsed, err, in_t, out_t = _call_llm(llm, prompt, LLMClaimList)
        return comp, dim, parsed, err, in_t, out_t

    single_claims: list[AnalysisClaim] = []
    counter_single: dict[tuple[str, str], int] = {}

    with ThreadPoolExecutor(max_workers=max(1, max_concurrency)) as pool:
        futures = [pool.submit(_single_task, w) for w in work]
        for f in as_completed(futures):
            comp, dim, parsed, err, in_t, out_t = f.result()
            accumulated_input += in_t
            accumulated_output += out_t
            if parsed is None:
                if err != "no_evidence":
                    failures.append({
                        "phase": "single",
                        "competitor": comp,
                        "dimension": dim,
                        "error": err or "unknown",
                    })
                continue
            for item in parsed.items:
                # 校验 1: 双语
                if not is_bilingual(item.statement):
                    failures.append({
                        "phase": "single",
                        "competitor": comp,
                        "dimension": dim,
                        "error": "monolingual_statement",
                        "preview": item.statement[:120],
                    })
                    continue
                # 校验 2: dimension 必须匹配
                if item.dimension != dim:
                    failures.append({
                        "phase": "single",
                        "competitor": comp,
                        "dimension": dim,
                        "error": f"dimension_mismatch:{item.dimension}",
                        "preview": item.statement[:120],
                    })
                    continue
                # 校验 3: evidence_ids 必须都存在
                invalid_ids = [
                    eid for eid in item.evidence_ids if eid not in evidence_by_id
                ]
                if invalid_ids:
                    failures.append({
                        "phase": "single",
                        "competitor": comp,
                        "dimension": dim,
                        "error": f"invalid_evidence_ids:{invalid_ids}",
                        "preview": item.statement[:120],
                    })
                    continue
                # 校验 4: competitor_name 必须匹配(LLM 偶尔会写错)
                if item.competitor_name and item.competitor_name != comp:
                    # 修正而不丢弃: 用 prompt 提供的 comp 覆盖
                    item.competitor_name = comp
                single_claims.append(
                    _to_single_claim(run_id, item, counter_single)
                )

    # ============ Phase 2: cross-competitor ============
    cross_claims: list[AnalysisClaim] = []
    counter_cross: dict[str, int] = {}

    for dim in BASE_DIMENSIONS:
        dim_singles = [c for c in single_claims if c.dimension == dim]
        # 跨竞品对比至少需要 2 个竞品参与
        unique_comps = {c.competitor_name for c in dim_singles}
        if len(unique_comps) < 2:
            continue
        # 每竞品取最多 2 条 claim 进 prompt 上下文
        per_comp_top: dict[str, list[AnalysisClaim]] = {}
        for c in sorted(dim_singles, key=lambda x: x.confidence or 0.0, reverse=True):
            per_comp_top.setdefault(c.competitor_name or "", []).append(c)
        prompt_singles: list[AnalysisClaim] = []
        for _, lst in per_comp_top.items():
            prompt_singles.extend(lst[:2])

        # evidence pool: 这些 claim 引用的 evidence 去重
        ev_ids_seen: set[str] = set()
        evidence_pool: list[EvidenceItem] = []
        for c in prompt_singles:
            for eid in c.evidence_ids:
                if eid in ev_ids_seen:
                    continue
                ev = evidence_by_id.get(eid)
                if ev is not None:
                    evidence_pool.append(ev)
                    ev_ids_seen.add(eid)

        prompt = _render_prompt(
            cross_prompt_template,
            dimension=dim,
            single_claims_block=_single_claims_block(prompt_singles),
            evidence_block=_evidence_block(evidence_pool),
        )
        parsed, err, in_t, out_t = _call_llm(llm, prompt, LLMCrossClaimList)
        accumulated_input += in_t
        accumulated_output += out_t
        if parsed is None:
            if err:
                failures.append({
                    "phase": "cross",
                    "dimension": dim,
                    "error": err,
                })
            continue
        for item in parsed.items:
            # 校验 1: 双语
            if not is_bilingual(item.statement):
                failures.append({
                    "phase": "cross",
                    "dimension": dim,
                    "error": "monolingual_statement",
                    "preview": item.statement[:120],
                })
                continue
            # 校验 2: dimension 必须匹配
            if item.dimension != dim:
                failures.append({
                    "phase": "cross",
                    "dimension": dim,
                    "error": f"dimension_mismatch:{item.dimension}",
                })
                continue
            # 校验 3: evidence_ids 全部存在
            invalid_ids = [
                eid for eid in item.evidence_ids if eid not in evidence_by_id
            ]
            if invalid_ids:
                failures.append({
                    "phase": "cross",
                    "dimension": dim,
                    "error": f"invalid_evidence_ids:{invalid_ids}",
                })
                continue
            # 校验 4: 跨竞品 claim 必须引用 ≥2 个不同 competitor
            referenced_competitors = {
                evidence_by_id[eid].competitor_name for eid in item.evidence_ids
            }
            if len(referenced_competitors) < 2:
                failures.append({
                    "phase": "cross",
                    "dimension": dim,
                    "error": "cross_claim_single_competitor",
                    "referenced": list(referenced_competitors),
                })
                continue
            # 强制 competitor_name=None
            item.competitor_name = None
            cross_claims.append(_to_cross_claim(run_id, item, counter_cross))

    # ============ Phase 3: target users / strategic implications ============
    insights_claims, insights_failures, in_t, out_t = _build_insights_phase(
        run_id=run_id,
        llm=llm,
        evidence_by_id=evidence_by_id,
        competitor_names=competitor_names,
        existing_claims=single_claims,
        max_concurrency=max_concurrency,
    )
    accumulated_input += in_t
    accumulated_output += out_t
    failures.extend(insights_failures)
    single_claims.extend(insights_claims)

    all_claims = single_claims + cross_claims
    llm_cost = estimate_cost(model_name, accumulated_input, accumulated_output)
    stats = {
        "single_claims": len(single_claims),
        "insight_claims": len(insights_claims),
        "cross_claims": len(cross_claims),
        "total_claims": len(all_claims),
        "failures_count": len(failures),
        "model": model_name,
        "input_tokens": accumulated_input,
        "output_tokens": accumulated_output,
        "llm_cost_usd": round(llm_cost, 4),
    }
    logger.info(
        "Analyst done: %d single + %d cross, %d failures, cost $%.4f",
        len(single_claims), len(cross_claims), len(failures), llm_cost,
    )
    return all_claims, failures, stats


# ---------- 兼容旧测试: 保留 mock_analyze ----------

def mock_analyze(
    run_id: str,
    competitor_name: str,
    dimension: str,
    evidence_ids: list[str],
) -> AnalysisClaim:
    statements = {
        "features": f"{competitor_name} 支持代码补全和对话式编程 [mock]",
        "pricing": f"{competitor_name} Pro 版定价 $20/月 [mock]",
        "positioning": f"{competitor_name} 定位为开发者 AI 助手 [mock]",
        "swot": f"{competitor_name} 的优势是生态集成,劣势是价格偏高 [mock]",
    }
    run_suffix = run_id.split("-")[-1][:6] if run_id else "000000"
    return AnalysisClaim(
        claim_id=f"C-{run_suffix}-{competitor_name[:3].upper()}-{dimension[:3].upper()}",
        run_id=run_id,
        competitor_name=competitor_name,
        dimension=dimension,  # type: ignore[arg-type]
        statement=statements.get(dimension, f"{competitor_name} {dimension} 分析 [mock]"),
        evidence_ids=evidence_ids[:1],
        confidence=0.75,
    )
