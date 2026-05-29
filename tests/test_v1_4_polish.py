from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from cs_mvp.agents import analyst
from cs_mvp.agents.analyst_grouping import DIMENSIONS, group_evidence_by_dimension
from cs_mvp.agents.writer import render_report
from cs_mvp.models import (
    AnalysisClaim,
    AnalysisTask,
    CompetitorInput,
    EvidenceItem,
)
from cs_mvp.web.app import fastapi_app
from cs_mvp.web.services.artifact_reader import get_schema_view


class _FakeStructuredLLM:
    def __init__(self, owner: "_FakeLLM", schema_name: str) -> None:
        self.owner = owner
        self.schema_name = schema_name

    def invoke(self, prompt: str) -> Any:
        with self.owner._lock:
            for matcher, response in self.owner.by_match.get(self.schema_name, []):
                if matcher(prompt):
                    return response
        return {"items": []}


class _FakeLLM:
    model = "qwen-test"

    def __init__(self, by_match: dict[str, list[tuple]] | None = None) -> None:
        self.by_match = by_match or {}
        self._lock = threading.Lock()

    def with_structured_output(self, schema_cls: Any, **kwargs: Any) -> _FakeStructuredLLM:
        return _FakeStructuredLLM(self, schema_cls.__name__)


def _has(*needles: str):
    def matcher(prompt: str) -> bool:
        return all(needle in prompt for needle in needles)

    return matcher


def _ev(
    evidence_id: str,
    competitor: str = "Cursor",
    claim_type: str = "feature",
    quote: str | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        source_id=f"S-{evidence_id}",
        competitor_name=competitor,
        claim_type=claim_type,  # type: ignore[arg-type]
        quote=quote or "Cursor serves product managers with AI workflow.",
        confidence=0.85,
    )


def _insight_item(
    dimension: str = "target_users",
    evidence_ids: list[str] | None = None,
    statement: str | None = None,
) -> dict[str, Any]:
    return {
        "competitor_name": "Cursor",
        "dimension": dimension,
        "statement": statement
        or "Cursor targets product managers and AI workflow teams for planning.",
        "evidence_ids": evidence_ids or ["E1"],
        "confidence": 0.75,
    }


def test_analysis_claim_accepts_new_dimensions() -> None:
    claim = AnalysisClaim(
        claim_id="C-1",
        run_id="RUN-1",
        competitor_name="Cursor",
        dimension="target_users",
        statement="Cursor targets product managers and AI workflow teams.",
        evidence_ids=["E1"],
    )

    assert claim.dimension == "target_users"


def test_grouping_exposes_new_dimensions_but_keeps_them_empty() -> None:
    result = group_evidence_by_dimension([_ev("E1")], "Cursor")

    assert "target_users" in DIMENSIONS
    assert "strategic_implications" in DIMENSIONS
    assert result["target_users"] == []
    assert result["strategic_implications"] == []


def test_analyst_phase3_target_users_dimension_accepted(monkeypatch) -> None:
    fake = _FakeLLM(
        by_match={
            "LLMInsightClaimList": [
                (
                    _has("competitor_name: Cursor"),
                    {
                        "items": [
                            _insight_item("target_users"),
                            _insight_item(
                                "strategic_implications",
                                statement=(
                                    "Cursor implies a product roadmap focus on "
                                    "AI workflow depth."
                                ),
                            ),
                        ]
                    },
                )
            ]
        }
    )
    monkeypatch.setattr(analyst, "get_extractor_llm", lambda: fake)

    claims, failures, stats = analyst.real_analyze("RUN-abcdef", [_ev("E1")], ["Cursor"])

    dimensions = {claim.dimension for claim in claims}
    assert {"target_users", "strategic_implications"}.issubset(dimensions)
    assert stats["insight_claims"] == 2
    assert failures == []


def test_analyst_phase3_invalid_dimension_filtered(monkeypatch) -> None:
    fake = _FakeLLM(
        by_match={
            "LLMInsightClaimList": [
                (_has("competitor_name: Cursor"), {"items": [_insight_item("market_size")]})
            ]
        }
    )
    monkeypatch.setattr(analyst, "get_extractor_llm", lambda: fake)

    claims, failures, stats = analyst.real_analyze("RUN-abcdef", [_ev("E1")], ["Cursor"])

    assert claims == []
    assert stats["insight_claims"] == 0
    assert any("dimension_mismatch:market_size" in item["error"] for item in failures)


def test_analyst_phase3_no_valid_evidence_filtered(monkeypatch) -> None:
    fake = _FakeLLM(
        by_match={
            "LLMInsightClaimList": [
                (
                    _has("competitor_name: Cursor"),
                    {"items": [_insight_item(evidence_ids=["E-MISSING"])]},
                )
            ]
        }
    )
    monkeypatch.setattr(analyst, "get_extractor_llm", lambda: fake)

    claims, failures, stats = analyst.real_analyze("RUN-abcdef", [_ev("E1")], ["Cursor"])

    assert claims == []
    assert stats["insight_claims"] == 0
    assert any("invalid_evidence_ids" in item["error"] for item in failures)


def test_report_template_renders_target_users_section(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    task = AnalysisTask(
        task_id="T-v14",
        query="AI workflow competitor analysis",
        competitors=[CompetitorInput(name="Cursor")],
    )
    quote = "Cursor targets product managers and AI workflow teams for planning."
    evidence = [_ev("E1", quote=quote)]
    claim = AnalysisClaim(
        claim_id="C-TAR-1",
        run_id="RUN-v14",
        competitor_name="Cursor",
        dimension="target_users",
        statement=quote,
        evidence_ids=["E1"],
        confidence=0.8,
    )

    report_md, accepted, _risks, _discarded, _stats = render_report(
        task,
        "RUN-v14",
        [claim],
        evidence,
    )

    assert "目标用户洞察 (Target Users)" in report_md
    assert "Cursor targets product managers" in report_md
    assert any(item.dimension == "target_users" for item in accepted)


def test_schema_view_includes_all_5_models() -> None:
    schema = get_schema_view()
    model_names = {item["name"] for item in schema["models"]}

    assert schema["schema_version"] == "1.2.0"
    assert {
        "SourceRecord",
        "EvidenceItem",
        "AnalysisClaim",
        "QAFeedback",
        "RevisionRecord",
    }.issubset(model_names)


def test_schema_tab_renders_with_schema_version(tmp_path: Path, monkeypatch) -> None:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "T-schema"
    run_dir.mkdir(parents=True)
    monkeypatch.setenv("RUNS_DIR", str(runs_dir))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite"))
    (run_dir / "run_summary.json").write_text(
        json.dumps(
            {
                "task_id": "T-schema",
                "run_id": "RUN-schema",
                "query": "schema smoke",
                "competitors": ["Cursor"],
                "status": "completed",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "trace.json").write_text(json.dumps({"node_runs": []}), encoding="utf-8")
    (run_dir / "claims.json").write_text("[]", encoding="utf-8")
    (run_dir / "evidence.json").write_text("[]", encoding="utf-8")
    (run_dir / "sources.json").write_text("[]", encoding="utf-8")
    (run_dir / "report.md").write_text("# Report", encoding="utf-8")

    response = TestClient(fastapi_app).get("/runs/T-schema")

    assert response.status_code == 200
    assert "Schema Contract" in response.text
    assert "schema_version: <code>1.2.0</code>" in response.text
    assert "target_users" in response.text


def test_home_renders_capability_cards(tmp_path: Path, monkeypatch) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    monkeypatch.setenv("RUNS_DIR", str(runs_dir))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite"))

    response = TestClient(fastapi_app).get("/")

    assert response.status_code == 200
    assert "AI-powered competitive intelligence agent system" in response.text
    assert "Multi-Agent DAG" in response.text
    assert "Evidence-Backed Claims" in response.text
    assert "Schema" in response.text
