"""M3 claim quality evaluation script.

Usage:
    python scripts/evaluate_claims.py runs/<task_id>/claims.json

Reads claims.json + evidence.json from the same directory and writes
m3_eval.md with PASS/FAIL checks against SDD M3 acceptance criteria.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


_DIMENSIONS = ("features", "pricing", "positioning", "swot")
_ENGLISH_TOKEN_RE = re.compile(r"[a-zA-Z]{3,}")
_COPILOT_LEAK_KEYWORDS = (
    "microsoft 365 copilot",
    "copilot studio",
    "copilot money",
)


def _load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _rate(num: int, den: int) -> float:
    return num / den if den else 0.0


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def _line(ok: bool, label: str, detail: str) -> str:
    return f"- {'PASS' if ok else 'FAIL'} {label}: {detail}"


def evaluate(claims_path: Path) -> str:
    run_dir = claims_path.parent
    claims = _load(claims_path, [])
    evidence = _load(run_dir / "evidence.json", [])
    stats = _load(run_dir / "analyst_stats.json", {})

    evidence_by_id = {e.get("evidence_id"): e for e in evidence}

    single = [c for c in claims if c.get("competitor_name")]
    cross = [c for c in claims if not c.get("competitor_name")]

    by_competitor: dict[str, int] = Counter()
    by_dimension: dict[str, int] = Counter()
    matrix: dict[tuple[str, str], int] = defaultdict(int)
    bilingual_count = 0
    statement_length_violations: list[tuple[str, int]] = []
    evidence_count_violations: list[tuple[str, int]] = []
    accepted = 0
    uncertain = 0
    dropped = 0

    for c in single:
        comp = c.get("competitor_name") or "?"
        dim = c.get("dimension") or "?"
        by_competitor[comp] += 1
        by_dimension[dim] += 1
        matrix[(comp, dim)] += 1
        stmt = c.get("statement") or ""
        if len(_ENGLISH_TOKEN_RE.findall(stmt)) >= 2:
            bilingual_count += 1
        if len(stmt) > 220:
            statement_length_violations.append((c.get("claim_id", "?"), len(stmt)))
        evidence_ids = c.get("evidence_ids") or []
        if not (1 <= len(evidence_ids) <= 3):
            evidence_count_violations.append((c.get("claim_id", "?"), len(evidence_ids)))
        score = c.get("support_score") or 0.0
        if score >= 0.6:
            accepted += 1
        elif score >= 0.3:
            uncertain += 1
        else:
            dropped += 1

    for c in cross:
        dim = c.get("dimension") or "?"
        by_dimension[dim] += 1
        stmt = c.get("statement") or ""
        if len(_ENGLISH_TOKEN_RE.findall(stmt)) >= 2:
            bilingual_count += 1
        if len(stmt) > 220:
            statement_length_violations.append((c.get("claim_id", "?"), len(stmt)))
        evidence_ids = c.get("evidence_ids") or []
        if not (1 <= len(evidence_ids) <= 3):
            evidence_count_violations.append((c.get("claim_id", "?"), len(evidence_ids)))
        score = c.get("support_score") or 0.0
        if score >= 0.6:
            accepted += 1
        elif score >= 0.3:
            uncertain += 1
        else:
            dropped += 1

    total = len(claims)
    competitors = sorted(by_competitor.keys())
    matrix_table = ["| competitor \\ dim | " + " | ".join(_DIMENSIONS) + " |"]
    matrix_table.append("|" + "---|" * (len(_DIMENSIONS) + 1))
    matrix_gaps: list[str] = []
    for comp in competitors:
        row = [comp]
        for dim in _DIMENSIONS:
            count = matrix.get((comp, dim), 0)
            cell = str(count) if count > 0 else "❌"
            row.append(cell)
            if count == 0:
                matrix_gaps.append(f"{comp}/{dim}")
        matrix_table.append("| " + " | ".join(row) + " |")

    # Copilot leak check
    leak_hits: list[str] = []
    for ev in evidence:
        comp = (ev.get("competitor_name") or "").lower()
        if "copilot" not in comp:
            continue
        quote_lc = (ev.get("quote") or "").lower()
        for kw in _COPILOT_LEAK_KEYWORDS:
            if kw in quote_lc and comp != kw:
                leak_hits.append(f"{ev.get('evidence_id')}: {kw}")
                break

    bilingual_rate = _rate(bilingual_count, total)
    accepted_rate = _rate(accepted, total)
    uncertain_rate = _rate(uncertain, total)

    lines = [
        "# M3 Claim Evaluation",
        "",
        f"- claims_path: `{claims_path}`",
        f"- total_claims: {total} (single={len(single)}, cross={len(cross)})",
        f"- per_competitor: {dict(by_competitor)}",
        f"- per_dimension: {dict(by_dimension)}",
        f"- bilingual_rate: {_pct(bilingual_rate)}",
        f"- accepted_rate (support>=0.6): {_pct(accepted_rate)}",
        f"- uncertain_rate (0.3-0.6): {_pct(uncertain_rate)}",
        f"- dropped (<0.3): {dropped}",
        f"- LLM cost: ${stats.get('llm_cost_usd', 0.0):.4f}",
        f"- model: {stats.get('model', '?')}",
        "",
        "## Dimension Coverage Matrix",
        "",
        *matrix_table,
        "",
        "## Checks",
        "",
        _line(len(single) >= 12, "single claims >= 12", str(len(single))),
        _line(len(cross) >= 2, "cross claims >= 2", str(len(cross))),
        _line(
            bool(by_competitor) and all(v >= 3 for v in by_competitor.values()),
            "each competitor >= 3 claims",
            str(dict(by_competitor)),
        ),
        _line(
            not matrix_gaps,
            "dimension coverage (no gaps)",
            f"gaps: {matrix_gaps}" if matrix_gaps else "no gaps",
        ),
        _line(accepted_rate >= 0.60, "accepted ratio >= 60%", _pct(accepted_rate)),
        _line(
            uncertain_rate <= 0.30,
            "uncertain ratio <= 30%",
            _pct(uncertain_rate),
        ),
        _line(
            bilingual_rate >= 1.0,
            "bilingual_rate == 100%",
            _pct(bilingual_rate),
        ),
        _line(
            not statement_length_violations,
            "statement length <= 220 chars",
            f"violations: {statement_length_violations[:5]}"
            if statement_length_violations
            else "all within limit",
        ),
        _line(
            not evidence_count_violations,
            "evidence_ids length in [1, 3]",
            f"violations: {evidence_count_violations[:5]}"
            if evidence_count_violations
            else "all within range",
        ),
        _line(
            not leak_hits,
            "no Microsoft 365 / Copilot Studio leak in Copilot evidence",
            f"leaks: {leak_hits[:5]}" if leak_hits else "clean",
        ),
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("claims_json", type=Path)
    args = parser.parse_args()
    output = evaluate(args.claims_json)
    out_path = args.claims_json.parent / "m3_eval.md"
    out_path.write_text(output, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
