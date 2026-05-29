from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from cs_mvp.models import (
    SCHEMA_VERSION,
    AgentRun,
    AnalysisTask,
    CompetitorInput,
    QAAudit,
    QAFeedback,
)


def test_schema_version_constant() -> None:
    assert SCHEMA_VERSION == "1.2.0"


def test_analysis_task_default_schema_version() -> None:
    task = AnalysisTask(
        task_id="T-1",
        query="AI IDE",
        competitors=[CompetitorInput(name="Cursor")],
    )

    assert task.schema_version == SCHEMA_VERSION


def test_agent_run_default_schema_version() -> None:
    run = AgentRun(run_id="RUN-1", task_id="T-1")

    assert run.schema_version == SCHEMA_VERSION


def test_qa_feedback_label_literal() -> None:
    with pytest.raises(ValidationError):
        QAFeedback(
            claim_id="C-1",
            label="unsupported",
            reason="not an allowed QA label",
        )


def test_qa_feedback_minimal_construction() -> None:
    feedback = QAFeedback(
        claim_id="C-1",
        label="risky",
        reason="Evidence alignment is weak.",
    )

    assert feedback.claim_id == "C-1"
    assert feedback.label == "risky"
    assert feedback.issue_tags == []
    assert feedback.suggested_revision is None


def test_qa_audit_full_construction() -> None:
    feedbacks = [
        QAFeedback(
            claim_id="C-1",
            label="accepted",
            reason="Claim is supported by cited evidence.",
        ),
        QAFeedback(
            claim_id="C-2",
            label="needs_revision",
            reason="Positioning wording overreaches.",
            issue_tags=["cross_claim_overreach"],
            suggested_revision="Narrow the claim to the cited feature evidence.",
        ),
    ]
    audit = QAAudit(
        run_id="RUN-1",
        total_claims_audited=2,
        accepted_count=1,
        needs_revision_count=1,
        risky_count=0,
        feedbacks=feedbacks,
        auditor_model="qwen3.6-plus",
        llm_cost_usd=0.001,
        notes="One claim needs revision.",
    )

    assert audit.schema_version == SCHEMA_VERSION
    assert len(audit.feedbacks) == 2
    assert audit.feedbacks[1].issue_tags == ["cross_claim_overreach"]
    assert audit.auditor_model == "qwen3.6-plus"


def test_qa_audit_default_audited_at() -> None:
    audit = QAAudit(
        run_id="RUN-1",
        total_claims_audited=0,
        accepted_count=0,
        needs_revision_count=0,
        risky_count=0,
    )

    assert isinstance(audit.audited_at, datetime)


def test_qa_audit_json_serialization() -> None:
    audit = QAAudit(
        run_id="RUN-1",
        total_claims_audited=1,
        accepted_count=1,
        needs_revision_count=0,
        risky_count=0,
        feedbacks=[
            QAFeedback(
                claim_id="C-1",
                label="accepted",
                reason="Supported.",
            )
        ],
    )

    payload = audit.model_dump(mode="json")

    assert payload["schema_version"] == SCHEMA_VERSION
    assert isinstance(payload["audited_at"], str)
    assert payload["feedbacks"][0]["label"] == "accepted"
