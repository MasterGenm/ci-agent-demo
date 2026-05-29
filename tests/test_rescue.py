from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from cs_mvp.agents.writer import render_report
from cs_mvp.models import AnalysisClaim, AnalysisTask, CompetitorInput, EvidenceItem
from cs_mvp.review_queue import build_review_queue
from cs_mvp.tools.interpretive_guard import scan_interpretive_risk
from cs_mvp.tools.rescue import rescue_uncertain_with_llm


def _claim(
    *,
    claim_id: str = "C-1",
    dimension: str = "features",
    statement: str = "Cursor supports AI coding.",
    support_score: float = 0.42,
) -> AnalysisClaim:
    return AnalysisClaim(
        claim_id=claim_id,
        run_id="RUN-1",
        competitor_name="Cursor",
        dimension=dimension,  # type: ignore[arg-type]
        statement=statement,
        evidence_ids=["E-1"],
        support_score=support_score,
    )


def _evidence() -> EvidenceItem:
    return EvidenceItem(
        evidence_id="E-1",
        source_id="S-1",
        competitor_name="Cursor",
        quote="Cursor supports AI coding.",
    )


def _task() -> AnalysisTask:
    return AnalysisTask(
        task_id="T-1",
        query="test",
        competitors=[CompetitorInput(name="Cursor")],
    )


def _supported(confidence: float = 0.9) -> dict:
    return {
        "semantic_verdict": "supported",
        "semantic_confidence": confidence,
        "reasoning": "all elements match",
        "_llm_cost_usd": 0.0002,
    }


def test_rescue_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("ENABLE_LLM_RESCUE", raising=False)
    evidence = EvidenceItem(
        evidence_id="E-1",
        source_id="S-1",
        competitor_name="Cursor",
        quote="Cursor costs $20.",
    )
    claim = AnalysisClaim(
        claim_id="C-UNCERTAIN",
        run_id="RUN-1",
        competitor_name="Cursor",
        dimension="pricing",
        statement="Cursor Enterprise Teams Advanced costs $20.",
        evidence_ids=["E-1"],
    )

    with patch("cs_mvp.agents.writer.rescue_uncertain_with_llm") as rescue_mock:
        _report, _accepted, risks, _discarded, stats = render_report(
            _task(),
            "RUN-1",
            [claim],
            [evidence],
        )

    rescue_mock.assert_not_called()
    assert len(risks) == 1
    assert "_rescue_outcomes_payload" not in stats


def test_rescue_verdict_gate_blocks_partial() -> None:
    with patch(
        "cs_mvp.tools.rescue.judge_one_claim",
        return_value={
            "semantic_verdict": "partial",
            "semantic_confidence": 0.95,
            "reasoning": "only partial support",
        },
    ):
        auto, review, outcomes = rescue_uncertain_with_llm(
            [_claim()],
            {"E-1": _evidence()},
            llm=object(),
        )

    assert auto == []
    assert review == []
    assert outcomes[0].action == "keep_uncertain"
    assert outcomes[0].gates_passed == []


def test_rescue_confidence_gate_blocks_low_confidence() -> None:
    with patch("cs_mvp.tools.rescue.judge_one_claim", return_value=_supported(0.7)):
        auto, review, outcomes = rescue_uncertain_with_llm(
            [_claim()],
            {"E-1": _evidence()},
            llm=object(),
        )

    assert auto == []
    assert review == []
    assert outcomes[0].action == "keep_uncertain"
    assert outcomes[0].gates_passed == ["verdict"]


def test_rescue_auto_for_features_claim() -> None:
    with patch("cs_mvp.tools.rescue.judge_one_claim", return_value=_supported(0.91)):
        auto, review, outcomes = rescue_uncertain_with_llm(
            [_claim(dimension="features")],
            {"E-1": _evidence()},
            llm=object(),
        )

    assert review == []
    assert outcomes[0].action == "rescue_auto"
    assert auto[0].accepted is True
    assert auto[0].rescued_by_llm_judge is True
    assert auto[0].rescue_judge_verdict == "supported"
    assert auto[0].rescue_judge_confidence == 0.91
    assert auto[0].rescue_gates_passed == ["verdict", "confidence", "dimension"]


def test_rescue_to_review_for_swot_claim() -> None:
    with patch("cs_mvp.tools.rescue.judge_one_claim", return_value=_supported(0.9)):
        auto, review, outcomes = rescue_uncertain_with_llm(
            [_claim(dimension="swot")],
            {"E-1": _evidence()},
            llm=object(),
        )

    assert auto == []
    assert outcomes[0].action == "rescue_to_review"
    assert review[0].insight_candidate is True
    assert review[0].rescued_by_llm_judge is True


def test_judge_failed_keeps_claim_uncertain() -> None:
    with patch(
        "cs_mvp.tools.rescue.judge_one_claim",
        side_effect=RuntimeError("transport failed"),
    ):
        auto, review, outcomes = rescue_uncertain_with_llm(
            [_claim()],
            {"E-1": _evidence()},
            llm=object(),
        )

    assert auto == []
    assert review == []
    assert outcomes[0].action == "judge_failed"
    assert outcomes[0].gate_failed_reason == "exception:RuntimeError"


def test_interpretive_guard_only_scans_swo_pos() -> None:
    is_risk, hits = scan_interpretive_risk(
        _claim(
            dimension="features",
            statement="Cursor 试图推动 AI coding adoption.",
        )
    )

    assert is_risk is False
    assert hits == []


def test_interpretive_guard_hits_swot_terms() -> None:
    is_risk, hits = scan_interpretive_risk(
        _claim(
            dimension="swot",
            statement="Cursor 旨在推动团队采用 AI coding.",
        )
    )

    assert is_risk is True
    assert hits == ["旨在", "推动"]


def test_interpretive_guard_demotes_accepted_claim_to_insight(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_LLM_RESCUE", "1")
    evidence = EvidenceItem(
        evidence_id="E-1",
        source_id="S-1",
        competitor_name="Cursor",
        quote="Cursor 旨在推动团队采用 AI coding.",
        normalized_fact="Cursor 旨在推动团队采用 AI coding.",
    )
    claim = AnalysisClaim(
        claim_id="C-SWO-1",
        run_id="RUN-1",
        competitor_name="Cursor",
        dimension="swot",
        statement="Cursor 旨在推动团队采用 AI coding.",
        evidence_ids=["E-1"],
    )

    report, accepted, risks, _discarded, _stats = render_report(
        _task(),
        "RUN-1",
        [claim],
        [evidence],
    )

    assert risks == []
    assert accepted[0].claim_id == "C-SWO-1"
    assert accepted[0].insight_candidate is True
    assert accepted[0].interpretive_hits == ["旨在", "推动"]
    main_section = report.split("## Cursor")[1].split("## Insight Candidates")[0]
    assert "旨在推动" not in main_section
    insight_section = report.split("## Insight Candidates")[1].split("## Risks")[0]
    assert "旨在推动" in insight_section


def test_review_queue_builds_insight_candidate_entry(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "claims.json").write_text(
        json.dumps(
            [
                {
                    "claim_id": "C-INSIGHT",
                    "competitor_name": "Cursor",
                    "dimension": "swot",
                    "statement": "Cursor 旨在推动团队采用 AI coding.",
                    "evidence_ids": ["E-1"],
                    "support_score": 0.65,
                    "accepted": True,
                    "interpretive_risk": True,
                    "interpretive_hits": ["旨在", "推动"],
                    "insight_candidate": True,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    for name, value in {
        "discarded_claims.json": [],
        "sources.json": [],
        "extractor_failures.json": [],
        "run_summary.json": {"quality_gates": {"low_recall_competitors": []}},
        "evidence.json": [{"evidence_id": "E-1", "competitor_name": "Cursor"}],
    }.items():
        (run_dir / name).write_text(
            json.dumps(value, ensure_ascii=False),
            encoding="utf-8",
        )

    queue = build_review_queue(run_dir)

    assert queue[0]["type"] == "insight_candidate"
    assert queue[0]["severity"] == "info"
    assert queue[0]["source"] == "interpretive_risk"
    assert queue[0]["interpretive_hits"] == ["旨在", "推动"]
