from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


_WS_RE = re.compile(r"\s+")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _norm(text: str | None) -> str:
    return _WS_RE.sub(" ", text or "").strip().lower()


def _rate(num: int, den: int) -> float:
    return num / den if den else 0.0


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def _line(ok: bool, label: str, detail: str) -> str:
    return f"- {'PASS' if ok else 'FAIL'} {label}: {detail}"


def evaluate(evidence_path: Path) -> str:
    run_dir = evidence_path.parent
    evidence = _load_json(evidence_path, [])
    sources = _load_json(run_dir / "sources.json", [])
    stats = _load_json(run_dir / "extractor_stats.json", {})
    source_by_id = {item.get("source_id"): item for item in sources}

    per_competitor: dict[str, int] = {}
    types: dict[str, int] = {}
    quote_matches = 0
    quote_lengths: list[int] = []
    confidences: list[float] = []
    seen: set[tuple[str, str]] = set()
    duplicates = 0

    for item in evidence:
        competitor = item.get("competitor_name") or "unknown"
        per_competitor[competitor] = per_competitor.get(competitor, 0) + 1
        claim_type = item.get("claim_type") or "other"
        types[claim_type] = types.get(claim_type, 0) + 1

        quote = item.get("quote") or ""
        quote_lengths.append(len(quote))
        source = source_by_id.get(item.get("source_id"), {})
        if quote and _norm(quote) in _norm(source.get("raw_text")):
            quote_matches += 1

        confidence = item.get("confidence")
        if confidence is not None:
            confidences.append(float(confidence))

        fact = _norm(item.get("normalized_fact"))
        key = (competitor, fact)
        if fact and key in seen:
            duplicates += 1
        seen.add(key)

    total = len(evidence)
    # quote_match_rate 必须用 extractor_stats.json 的值——它统计的是
    # (落库 + 被 quote_match 丢弃) 的总分母,反映真实 LLM 输出质量。
    # 如果只在 evidence.json 上自算会变成幸存者偏差(已落库的当然 100% 通过)。
    if "quote_match_rate" in stats:
        quote_match_rate = float(stats["quote_match_rate"])
        quote_match_source = "extractor_stats.json (含被丢弃)"
    else:
        quote_match_rate = _rate(quote_matches, total)
        quote_match_source = "evidence.json (幸存者偏差,缺 stats)"
    duplicate_rate = _rate(duplicates, total)
    schema_pass_rate = float(stats.get("schema_pass_rate") or 0.0)
    min_quote = min(quote_lengths) if quote_lengths else 0
    max_quote = max(quote_lengths) if quote_lengths else 0
    min_conf = min(confidences) if confidences else None
    max_conf = max(confidences) if confidences else None
    all_conf_one = bool(confidences) and all(value == 1.0 for value in confidences)

    lines = [
        "# M2 Evidence Evaluation",
        "",
        f"- evidence_path: `{evidence_path}`",
        f"- evidence_count: {total}",
        f"- per_competitor: {per_competitor}",
        f"- claim_types: {types}",
        f"- quote_match_rate: {_pct(quote_match_rate)} ({quote_match_source})",
        f"- schema_pass_rate: {_pct(schema_pass_rate)}",
        f"- duplicate_rate: {_pct(duplicate_rate)}",
        f"- confidence_range: {min_conf} - {max_conf}",
        "",
        "## Checks",
        "",
        _line(total >= 15, "evidence_count >= 15", str(total)),
        _line(
            bool(per_competitor)
            and all(count >= 4 for count in per_competitor.values()),
            "each competitor >= 4 evidence",
            str(per_competitor),
        ),
        _line(len(types) >= 3, "claim_type classes >= 3", str(types)),
        _line(
            bool(quote_lengths) and min_quote >= 50 and max_quote <= 500,
            "quote length 50-500",
            f"min={min_quote}, max={max_quote}",
        ),
        _line(
            quote_match_rate >= 0.90,
            "quote_match_rate >= 90%",
            _pct(quote_match_rate),
        ),
        _line(
            schema_pass_rate >= 0.80,
            "schema_pass_rate >= 80%",
            _pct(schema_pass_rate),
        ),
        _line(
            duplicate_rate <= 0.25,
            "duplicate_rate <= 25%",
            _pct(duplicate_rate),
        ),
        _line(
            bool(confidences)
            and not all_conf_one
            and min_conf is not None
            and min_conf >= 0.3
            and max_conf is not None
            and max_conf <= 0.95,
            "confidence range 0.3-0.95 and not all 1.0",
            f"{min_conf} - {max_conf}",
        ),
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_json", type=Path)
    args = parser.parse_args()

    output = evaluate(args.evidence_json)
    out_path = args.evidence_json.parent / "m2_eval.md"
    out_path.write_text(output, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
