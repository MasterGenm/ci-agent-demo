from __future__ import annotations

from cs_mvp.agents.writer import render_pm_report_artifacts
from cs_mvp.agents.writer_skills import (
    build_evidence_digest,
    build_pm_report_payload,
)
from cs_mvp.models import AnalysisClaim, AnalysisTask, CompetitorInput, EvidenceItem


def _task() -> AnalysisTask:
    return AnalysisTask(
        task_id="T-pm-report",
        query="AI coding assistant",
        competitors=[
            CompetitorInput(name="Cursor"),
            CompetitorInput(name="Windsurf"),
        ],
    )


def _evidence() -> list[EvidenceItem]:
    return [
        EvidenceItem(
            evidence_id="E-CUR-1",
            source_id="S-CUR-1",
            competitor_name="Cursor",
            claim_type="feature",
            quote="Cursor highlights AI code editing and agent workflows.",
        ),
        EvidenceItem(
            evidence_id="E-WIN-1",
            source_id="S-WIN-1",
            competitor_name="Windsurf",
            claim_type="pricing",
            quote="Windsurf publishes Pro pricing for individual developers.",
        ),
    ]


def _claims() -> list[AnalysisClaim]:
    return [
        AnalysisClaim(
            claim_id="C-CUR-FEA",
            run_id="RUN-pm",
            competitor_name="Cursor",
            dimension="features",
            statement="Cursor highlights AI code editing and agent workflows.",
            evidence_ids=["E-CUR-1"],
            support_score=0.88,
        ),
        AnalysisClaim(
            claim_id="C-WIN-PRI",
            run_id="RUN-pm",
            competitor_name="Windsurf",
            dimension="pricing",
            statement="Windsurf publishes Pro pricing for individual developers.",
            evidence_ids=["E-WIN-1"],
            support_score=0.81,
        ),
        AnalysisClaim(
            claim_id="C-CROSS",
            run_id="RUN-pm",
            competitor_name=None,
            dimension="positioning",
            statement="Cursor and Windsurf both position around AI-assisted development.",
            evidence_ids=["E-CUR-1", "E-WIN-1"],
            support_score=0.74,
        ),
    ]


def test_build_pm_report_payload_has_context_plan_matrix_and_recommendations() -> None:
    payload = build_pm_report_payload(
        task=_task(),
        run_id="RUN-pm",
        accepted_claims=_claims(),
        risks_claims=[],
        evidence=_evidence(),
        qa_audit={
            "feedbacks": [
                {"claim_id": "C-CUR-FEA", "label": "accepted", "reason": "ok"},
            ],
        },
        revision_history=[{"claim_id": "C-CUR-FEA"}],
    )

    assert payload["report_context"]["inputs"]["qa_feedback_count"] == 1
    assert payload["report_context"]["inputs"]["revision_count"] == 1
    assert "report_template_render" in {
        item["name"] for item in payload["report_context"]["writer_capabilities"]
    }
    assert [row["competitor_name"] for row in payload["competitor_matrix"]] == [
        "Cursor",
        "Windsurf",
    ]
    assert len(payload["report_plan"]["sections"]) == 7
    assert payload["top_findings"]
    assert payload["recommendations"]
    assert all(
        item["evidence_ids"] or item["needs_validation"]
        for item in payload["recommendations"]
    )


def test_evidence_digest_limits_each_claim_to_three_evidence_items() -> None:
    evidence = [
        EvidenceItem(
            evidence_id=f"E-{index}",
            source_id=f"S-{index}",
            competitor_name="Cursor",
            quote=f"Cursor quote {index}.",
        )
        for index in range(5)
    ]
    claim = AnalysisClaim(
        claim_id="C-MANY",
        run_id="RUN-pm",
        competitor_name="Cursor",
        dimension="features",
        statement="Cursor has multiple evidence items.",
        evidence_ids=[item.evidence_id for item in evidence],
        support_score=0.91,
    )

    digest = build_evidence_digest(task=_task(), claims=[claim], evidence=evidence)

    assert len(digest["items"]) == 1
    assert len(digest["items"][0]["digest_evidence"]) == 3


def test_render_pm_report_artifacts_keeps_audit_report_separate() -> None:
    artifacts = render_pm_report_artifacts(
        _task(),
        "RUN-pm",
        _claims(),
        [],
        _evidence(),
    )

    assert "report_pm_md" in artifacts
    assert "report_pm_html" in artifacts
    assert "# 竞品分析简报" in artifacts["report_pm_md"]
    assert "## 2. 竞品对比矩阵" in artifacts["report_pm_md"]
    assert "## 7. Evidence Digest" in artifacts["report_pm_md"]
    assert artifacts["report_pm_summary"]["section_count"] == 7
    assert artifacts["report_context"]["constraints"]
