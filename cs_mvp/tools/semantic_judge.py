from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cs_mvp.tools.chunker import estimate_tokens
from cs_mvp.tools.llm import estimate_cost, get_extractor_llm


_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "semantic_judge.txt"
_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)
_VERDICTS = {"supported", "partial", "unsupported"}
_ACTIONS = {"promote_to_accepted", "human_review", "keep_as_fail"}
_DEFAULT_ACTION = {
    "supported": "promote_to_accepted",
    "partial": "human_review",
    "unsupported": "keep_as_fail",
}


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _preview(text: str | None, limit: int = 220) -> str:
    value = " ".join((text or "").split())
    if len(value) <= limit:
        return value
    return f"{value[: limit - 1]}..."


def _llm_model_name(llm: Any) -> str:
    for attr in ("model_name", "model"):
        value = getattr(llm, attr, None)
        if value:
            return str(value)
    return "unknown"


def _response_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content)


def _usage_from_response(response: Any, prompt: str, text: str) -> tuple[int, int]:
    usage = getattr(response, "usage_metadata", None)
    if isinstance(usage, dict):
        input_tokens = usage.get("input_tokens") or usage.get("prompt_tokens")
        output_tokens = usage.get("output_tokens") or usage.get("completion_tokens")
        if input_tokens is not None and output_tokens is not None:
            return int(input_tokens), int(output_tokens)

    metadata = getattr(response, "response_metadata", None)
    if isinstance(metadata, dict):
        token_usage = metadata.get("token_usage") or metadata.get("usage")
        if isinstance(token_usage, dict):
            input_tokens = token_usage.get("prompt_tokens") or token_usage.get("input_tokens")
            output_tokens = token_usage.get("completion_tokens") or token_usage.get("output_tokens")
            if input_tokens is not None and output_tokens is not None:
                return int(input_tokens), int(output_tokens)

    return estimate_tokens(prompt), estimate_tokens(text)


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = re.sub(r"^\s*json\s*", "", cleaned, flags=re.IGNORECASE)
    match = _JSON_BLOCK_RE.search(cleaned)
    if match:
        cleaned = match.group(0)
    payload = json.loads(cleaned)
    if not isinstance(payload, dict):
        raise ValueError("judge response is not a JSON object")
    return payload


def _validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    verdict = str(payload.get("semantic_verdict") or "").strip().lower()
    if verdict not in _VERDICTS:
        raise ValueError(f"invalid semantic_verdict: {verdict}")

    confidence = _safe_float(payload.get("semantic_confidence"))
    if confidence < 0 or confidence > 1:
        raise ValueError(f"invalid semantic_confidence: {confidence}")

    reasoning = str(payload.get("reasoning") or "").strip()
    if not reasoning:
        raise ValueError("reasoning is required")

    action = str(payload.get("suggested_action") or "").strip()
    if not action:
        action = _DEFAULT_ACTION[verdict]
    if action not in _ACTIONS:
        raise ValueError(f"invalid suggested_action: {action}")

    return {
        "semantic_verdict": verdict,
        "semantic_confidence": confidence,
        "reasoning": reasoning,
        "suggested_action": action,
    }


def _evidence_items(claim: dict[str, Any], evidence_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for evidence_id in claim.get("evidence_ids") or []:
        item = evidence_map.get(str(evidence_id))
        if not item:
            continue
        items.append(
            {
                "evidence_id": item.get("evidence_id"),
                "source_id": item.get("source_id"),
                "competitor_name": item.get("competitor_name"),
                "claim_type": item.get("claim_type"),
                "quote": item.get("quote"),
                "normalized_fact": item.get("normalized_fact"),
            }
        )
    return items


def _infer_competitor(
    claim: dict[str, Any],
    evidence_items: list[dict[str, Any]],
) -> str | None:
    if claim.get("competitor_name"):
        return str(claim.get("competitor_name"))
    competitors = [
        str(item.get("competitor_name"))
        for item in evidence_items
        if item.get("competitor_name")
    ]
    unique = sorted(set(competitors))
    if len(unique) == 1:
        return unique[0]
    if len(unique) > 1:
        return "CROSS"
    return None


def _claim_dimension(claim: dict[str, Any]) -> str:
    if claim.get("dimension"):
        return str(claim.get("dimension"))
    claim_id = str(claim.get("claim_id") or "")
    marker_map = {
        "-FEA-": "features",
        "-PRI-": "pricing",
        "-POS-": "positioning",
        "-SWO-": "swot",
    }
    for marker, dimension in marker_map.items():
        if marker in claim_id:
            return dimension
    return "unknown"


def _base_judgment(
    claim: dict[str, Any],
    evidence_items: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "claim_id": claim.get("claim_id"),
        "current_verifier_score": _safe_float(claim.get("support_score")),
        "current_verdict": claim.get("current_verdict") or claim.get("verdict"),
        "competitor_name": _infer_competitor(claim, evidence_items),
        "dimension": _claim_dimension(claim),
        "statement_preview": _preview(claim.get("statement")),
        "evidence_ids": claim.get("evidence_ids") or [],
    }


def _render_prompt(claim: dict[str, Any], evidence_items: list[dict[str, Any]]) -> str:
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    claim_payload = {
        "claim_id": claim.get("claim_id"),
        "statement": claim.get("statement"),
        "current_verifier_score": claim.get("support_score"),
        "current_verdict": claim.get("current_verdict") or claim.get("verdict"),
        "dimension": _claim_dimension(claim),
    }
    return (
        template.replace(
            "{claim_json}",
            json.dumps(claim_payload, ensure_ascii=False, indent=2),
        )
        .replace(
            "{evidence_json}",
            json.dumps(evidence_items, ensure_ascii=False, indent=2),
        )
    )


def judge_one_claim(
    claim: dict[str, Any],
    evidence_map: dict[str, dict[str, Any]],
    llm: Any,
) -> dict[str, Any]:
    evidence_items = _evidence_items(claim, evidence_map)
    judgment = _base_judgment(claim, evidence_items)
    model = _llm_model_name(llm)
    prompt = _render_prompt(claim, evidence_items)
    last_error: Exception | None = None
    total_input_tokens = 0
    total_output_tokens = 0

    for attempt in range(2):
        attempt_prompt = prompt
        if attempt:
            attempt_prompt += (
                "\n\nPrevious response was invalid. Return one valid JSON object "
                "matching the schema exactly."
            )
        try:
            response = llm.invoke(attempt_prompt)
            text = _response_text(response)
            input_tokens, output_tokens = _usage_from_response(
                response, attempt_prompt, text
            )
            total_input_tokens += input_tokens
            total_output_tokens += output_tokens
            payload = _validate_payload(_parse_json_object(text))
            judgment.update(payload)
            judgment["_input_tokens"] = total_input_tokens
            judgment["_output_tokens"] = total_output_tokens
            judgment["_llm_cost_usd"] = estimate_cost(
                model,
                total_input_tokens,
                total_output_tokens,
            )
            judgment["_model"] = model
            return judgment
        except Exception as exc:  # retry once for invalid JSON/schema or transport errors
            last_error = exc

    judgment.update(
        {
            "semantic_verdict": "judge_failed",
            "semantic_confidence": 0.0,
            "reasoning": "LLM 调用异常",
            "suggested_action": "human_review",
            "_input_tokens": total_input_tokens or estimate_tokens(prompt),
            "_output_tokens": total_output_tokens,
            "_llm_cost_usd": estimate_cost(
                model,
                total_input_tokens or estimate_tokens(prompt),
                total_output_tokens,
            ),
            "_model": model,
            "_error": str(last_error) if last_error else "unknown",
        }
    )
    return judgment


def _public_judgment(judgment: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in judgment.items() if not key.startswith("_")}


def _evidence_map(run_dir: Path) -> dict[str, dict[str, Any]]:
    evidence = _load_json(run_dir / "evidence.json", [])
    if not isinstance(evidence, list):
        return {}
    return {
        str(item.get("evidence_id")): item
        for item in evidence
        if item.get("evidence_id")
    }


def judge_run_dir(run_dir: Path, llm: Any | None = None) -> dict[str, Any]:
    run_dir = Path(run_dir)
    llm = llm or get_extractor_llm()
    model = _llm_model_name(llm)
    discarded_claims = _load_json(run_dir / "discarded_claims.json", [])
    if not isinstance(discarded_claims, list):
        discarded_claims = []
    evidence_map = _evidence_map(run_dir)

    raw_judgments = [
        judge_one_claim(claim, evidence_map, llm)
        for claim in discarded_claims
        if isinstance(claim, dict)
    ]
    verdict_counts = {
        verdict: sum(1 for item in raw_judgments if item.get("semantic_verdict") == verdict)
        for verdict in ("supported", "partial", "unsupported")
    }
    judge_failed_count = sum(
        1 for item in raw_judgments if item.get("semantic_verdict") == "judge_failed"
    )
    false_positive_estimate = sum(
        1
        for item in raw_judgments
        if item.get("semantic_verdict") == "supported"
        and item.get("current_verdict") != "pass"
    )
    input_tokens = sum(int(item.get("_input_tokens") or 0) for item in raw_judgments)
    output_tokens = sum(int(item.get("_output_tokens") or 0) for item in raw_judgments)
    llm_cost = round(sum(float(item.get("_llm_cost_usd") or 0.0) for item in raw_judgments), 6)

    return {
        "model": model,
        "judged_at": _now_iso(),
        "total_judged": len(raw_judgments),
        "supported_count": verdict_counts["supported"],
        "partial_count": verdict_counts["partial"],
        "unsupported_count": verdict_counts["unsupported"],
        "judge_failed_count": judge_failed_count,
        "false_positive_estimate": false_positive_estimate,
        "llm_cost_usd": llm_cost,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "judgments": [_public_judgment(item) for item in raw_judgments],
    }


def write_semantic_judge_placeholder(run_dir: Path) -> Path:
    run_dir = Path(run_dir)
    path = run_dir / "semantic_judge_report.json"
    if path.exists():
        return path
    _write_json(
        path,
        {
            "status": "not_yet_judged",
            "hint": f"run: cs-mvp judge --task-id {run_dir.name}",
        },
    )
    return path


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Semantic Judge Report",
        "",
        f"- model: {report.get('model')}",
        f"- judged_at: {report.get('judged_at')}",
        f"- total_judged: {report.get('total_judged')}",
        f"- supported: {report.get('supported_count')}",
        f"- partial: {report.get('partial_count')}",
        f"- unsupported: {report.get('unsupported_count')}",
        f"- judge_failed: {report.get('judge_failed_count')}",
        f"- false_positive_estimate: {report.get('false_positive_estimate')}",
        f"- llm_cost_usd: {report.get('llm_cost_usd')}",
        "",
        "## Judgments",
        "",
    ]
    for item in report.get("judgments", []):
        lines.extend(
            [
                (
                    f"### {item.get('claim_id')} - "
                    f"{item.get('semantic_verdict')} "
                    f"({item.get('semantic_confidence')})"
                ),
                "",
                f"- current_verdict: {item.get('current_verdict')}",
                f"- current_verifier_score: {item.get('current_verifier_score')}",
                f"- competitor_name: {item.get('competitor_name')}",
                f"- dimension: {item.get('dimension')}",
                f"- suggested_action: {item.get('suggested_action')}",
                f"- evidence_ids: {', '.join(item.get('evidence_ids') or [])}",
                f"- statement: {item.get('statement_preview')}",
                f"- reasoning: {item.get('reasoning')}",
                "",
            ]
        )
    return "\n".join(lines)


def write_semantic_judge_report(
    run_dir: Path,
    llm: Any | None = None,
) -> tuple[Path, Path]:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    report = judge_run_dir(run_dir, llm=llm)

    report_path = run_dir / "semantic_judge_report.json"
    markdown_path = run_dir / "semantic_judge.md"
    stats_path = run_dir / "judge_stats.json"

    _write_json(report_path, report)
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    _write_json(
        stats_path,
        {
            "model": report.get("model"),
            "llm_cost_usd": report.get("llm_cost_usd"),
            "input_tokens": report.get("input_tokens"),
            "output_tokens": report.get("output_tokens"),
            "total_judged": report.get("total_judged"),
            "supported_count": report.get("supported_count"),
            "partial_count": report.get("partial_count"),
            "unsupported_count": report.get("unsupported_count"),
            "judge_failed_count": report.get("judge_failed_count"),
        },
    )
    return report_path, markdown_path
