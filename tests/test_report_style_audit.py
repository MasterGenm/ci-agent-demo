from __future__ import annotations

import json
from pathlib import Path

from cs_mvp.report_style_audit import (
    AI_TONE_RULES,
    REQUIRED_SECTIONS,
    evaluate_report_style,
    render_report_style_audit_markdown,
    write_report_style_audit,
)


def _sample_report() -> str:
    sections = {key: heading for key, heading in REQUIRED_SECTIONS}
    ai_phrase = AI_TONE_RULES[0][1]
    return "\n\n".join(
        [
            "# PM Report",
            f"{sections['one_page_summary']}\n\n- Qdrant has focused vector-search evidence [E-1].",
            f"{sections['competitor_matrix']}\n\n| Competitor | Signal |\n|---|---|\n| Qdrant | Vector search [E-1] |",
            f"{sections['top_findings']}\n\nQdrant highlights vector search and filtering [E-1].",
            f"{sections['competitor_profiles']}\n\n### Qdrant\n\n- Profile: documented vector filtering [E-1].",
            f"{sections['recommendations']}\n\n- **R-01** Prioritize benchmark docs  \n  Evidence: use Qdrant docs [E-1]\n- **R-02** Validate pricing assumptions _(needs validation)_",
            f"{sections['risks_and_unknowns']}\n\nA claim says {ai_phrase} without citation.",
            f"{sections['evidence_digest']}\n\n- **E-1** Qdrant documentation quote.",
        ]
    )


def test_evaluate_report_style_returns_complete_payload() -> None:
    audit = evaluate_report_style(
        task_id="T-style",
        run_id="RUN-style",
        report_md=_sample_report(),
        report_pm_summary={"recommendation_count": 2, "top_finding_count": 1},
        report_plan={"sections": [{"id": key} for key, _ in REQUIRED_SECTIONS]},
        evidence_digest={"items": [{"claim_id": "C-1"}]},
    )

    assert audit["schema_version"] == "1.7.0"
    assert all(audit["section_coverage"].values())
    assert audit["actionability"]["recommendation_count"] == 2
    assert audit["actionability"]["recommendations_with_evidence"] == 1
    assert audit["actionability"]["recommendations_needing_validation"] == 1
    assert audit["evidence_density"]["citation_count"] >= 4
    assert audit["score"]["overall_score"] > 0


def test_missing_section_is_reported() -> None:
    report = _sample_report().replace(REQUIRED_SECTIONS[-1][1], "## Missing Digest")

    audit = evaluate_report_style(
        task_id="T-style",
        run_id=None,
        report_md=report,
        report_pm_summary={},
        report_plan={"sections": [{"id": key} for key, _ in REQUIRED_SECTIONS]},
        evidence_digest={"items": [{"claim_id": "C-1"}]},
    )

    assert audit["section_coverage"]["evidence_digest"] is False
    assert audit["score"]["readability_score"] < 1.0


def test_ai_tone_flags_include_examples() -> None:
    audit = evaluate_report_style(
        task_id="T-style",
        run_id=None,
        report_md=_sample_report(),
        report_pm_summary={},
        report_plan={"sections": [{"id": key} for key, _ in REQUIRED_SECTIONS]},
        evidence_digest={"items": [{"claim_id": "C-1"}]},
    )

    flags = audit["ai_tone_flags"]
    assert flags
    assert flags[0]["examples"]


def test_write_report_style_audit_writes_json_and_markdown(tmp_path: Path) -> None:
    run_dir = tmp_path / "T-style"
    run_dir.mkdir()
    (run_dir / "report_pm.md").write_text(_sample_report(), encoding="utf-8")
    (run_dir / "report_pm_summary.json").write_text(
        json.dumps(
            {
                "task_id": "T-style",
                "run_id": "RUN-style",
                "recommendation_count": 2,
                "top_finding_count": 1,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "report_plan.json").write_text(
        json.dumps({"sections": [{"id": key} for key, _ in REQUIRED_SECTIONS]}),
        encoding="utf-8",
    )
    (run_dir / "evidence_digest.json").write_text(
        json.dumps({"items": [{"claim_id": "C-1"}]}),
        encoding="utf-8",
    )

    paths = write_report_style_audit(run_dir)

    assert paths["json"].exists()
    assert paths["markdown"].exists()
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["task_id"] == "T-style"
    assert "# Report Style Audit" in paths["markdown"].read_text(encoding="utf-8")


def test_render_report_style_audit_markdown_includes_required_sections() -> None:
    audit = evaluate_report_style(
        task_id="T-style",
        run_id="RUN-style",
        report_md=_sample_report(),
        report_pm_summary={"recommendation_count": 2, "top_finding_count": 1},
        report_plan={"sections": [{"id": key} for key, _ in REQUIRED_SECTIONS]},
        evidence_digest={"items": [{"claim_id": "C-1"}]},
    )

    markdown = render_report_style_audit_markdown(audit)

    assert "## Section Coverage" in markdown
    assert "## Actionability" in markdown
    assert "## Evidence Grounding" in markdown
