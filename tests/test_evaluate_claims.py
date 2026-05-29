from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.evaluate_claims as evaluate_claims_module


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return tmp_path


def _write(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _claim(
    cid: str,
    competitor: str | None,
    dim: str,
    statement: str = "Cursor 提供 (inline) 体验",
    evidence_ids: list[str] | None = None,
    support_score: float = 0.7,
) -> dict:
    return {
        "claim_id": cid,
        "competitor_name": competitor,
        "dimension": dim,
        "statement": statement,
        "evidence_ids": evidence_ids or ["E1"],
        "support_score": support_score,
        "confidence": 0.8,
        "accepted": support_score >= 0.6,
    }


def _evidence(eid: str, competitor: str, quote: str = "test quote") -> dict:
    return {
        "evidence_id": eid,
        "source_id": f"S-{eid}",
        "competitor_name": competitor,
        "claim_type": "feature",
        "quote": quote,
        "normalized_fact": "fact",
        "confidence": 0.8,
    }


def test_eval_passes_when_all_criteria_met(run_dir: Path) -> None:
    claims = []
    for comp in ("Cursor", "Windsurf", "Copilot"):
        for dim in ("features", "pricing", "positioning", "swot"):
            claims.append(_claim(f"C-{comp[:3]}-{dim[:3]}", comp, dim))
    # 2 个 cross claim
    claims.append(_claim("C-CROSS-FEA", None, "features", evidence_ids=["E1", "E2"]))
    claims.append(_claim("C-CROSS-PRI", None, "pricing", evidence_ids=["E1", "E2"]))

    evidence = [_evidence("E1", "Cursor"), _evidence("E2", "Windsurf")]

    _write(run_dir / "claims.json", claims)
    _write(run_dir / "evidence.json", evidence)
    _write(run_dir / "analyst_stats.json", {"llm_cost_usd": 0.15, "model": "qwen3.6-plus"})

    output = evaluate_claims_module.evaluate(run_dir / "claims.json")

    assert "PASS single claims >= 12" in output
    assert "PASS cross claims >= 2" in output
    assert "PASS each competitor >= 3 claims" in output
    assert "PASS dimension coverage (no gaps)" in output
    assert "PASS bilingual_rate == 100%" in output


def test_eval_detects_monolingual_statement(run_dir: Path) -> None:
    claims = [
        _claim("C1", "Cursor", "features", statement="这是纯中文 statement 没有英文")
    ]
    _write(run_dir / "claims.json", claims)
    _write(run_dir / "evidence.json", [_evidence("E1", "Cursor")])
    _write(run_dir / "analyst_stats.json", {})

    output = evaluate_claims_module.evaluate(run_dir / "claims.json")

    # 没有英文 token, bilingual rate < 100% → FAIL
    assert "FAIL bilingual_rate == 100%" in output


def test_eval_detects_dimension_coverage_gap(run_dir: Path) -> None:
    # Cursor 只有 features 维度, 缺 pricing/positioning/swot
    claims = [_claim("C1", "Cursor", "features")]
    _write(run_dir / "claims.json", claims)
    _write(run_dir / "evidence.json", [_evidence("E1", "Cursor")])
    _write(run_dir / "analyst_stats.json", {})

    output = evaluate_claims_module.evaluate(run_dir / "claims.json")

    assert "FAIL dimension coverage" in output
    assert "Cursor/pricing" in output


def test_eval_detects_copilot_microsoft_365_leak(run_dir: Path) -> None:
    claims = [_claim("C1", "Copilot", "features")]
    evidence = [
        _evidence(
            "E1",
            "Copilot",
            quote="Microsoft 365 Copilot Business 提供完整办公套件集成体验",
        )
    ]
    _write(run_dir / "claims.json", claims)
    _write(run_dir / "evidence.json", evidence)
    _write(run_dir / "analyst_stats.json", {})

    output = evaluate_claims_module.evaluate(run_dir / "claims.json")

    assert "FAIL no Microsoft 365" in output
    assert "microsoft 365 copilot" in output.lower()


def test_eval_detects_statement_too_long(run_dir: Path) -> None:
    long_stmt = "Cursor (inline) " + "x" * 230
    claims = [_claim("C1", "Cursor", "features", statement=long_stmt)]
    _write(run_dir / "claims.json", claims)
    _write(run_dir / "evidence.json", [_evidence("E1", "Cursor")])
    _write(run_dir / "analyst_stats.json", {})

    output = evaluate_claims_module.evaluate(run_dir / "claims.json")

    assert "FAIL statement length <= 220 chars" in output


def test_eval_detects_evidence_count_violation(run_dir: Path) -> None:
    claims = [_claim("C1", "Cursor", "features", evidence_ids=["E1", "E2", "E3", "E4"])]
    _write(run_dir / "claims.json", claims)
    _write(run_dir / "evidence.json", [_evidence("E1", "Cursor")])
    _write(run_dir / "analyst_stats.json", {})

    output = evaluate_claims_module.evaluate(run_dir / "claims.json")

    assert "FAIL evidence_ids length in [1, 3]" in output
