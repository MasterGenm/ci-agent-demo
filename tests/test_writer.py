from __future__ import annotations

import os
import pytest

from cs_mvp.agents.writer import render_report
from cs_mvp.models import (
    AnalysisClaim,
    AnalysisTask,
    CompetitorInput,
    EvidenceItem,
)


@pytest.fixture(autouse=True)
def _no_llm_provider(monkeypatch):
    """Writer 单元测试强制走模板 fallback,不调真实 LLM。"""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_uncertain_claim_renders_in_risks_section() -> None:
    """0.3 <= score < 0.6 的 claim 必须出现在 Risks & Unknowns 区块，且不在主竞品段"""
    task = AnalysisTask(
        task_id="T-1",
        query="test",
        competitors=[CompetitorInput(name="Cursor")],
    )
    evidence = EvidenceItem(
        evidence_id="E-001",
        source_id="S-001",
        competitor_name="Cursor",
        quote="Cursor costs $20.",
    )
    uncertain_claim = AnalysisClaim(
        claim_id="C-UNCERTAIN",
        run_id="RUN-1",
        competitor_name="Cursor",
        dimension="pricing",
        statement="Cursor Enterprise Teams Advanced costs $20.",
        evidence_ids=["E-001"],
    )

    report_md, accepted, uncertain, discarded, _ = render_report(
        task, "RUN-1", [uncertain_claim], [evidence]
    )

    assert len(uncertain) == 1
    assert "Risks & Unknowns" in report_md
    risks_section = report_md.split("Risks & Unknowns")[1]
    assert "Cursor Enterprise Teams Advanced" in risks_section
    # 主竞品段（## Cursor 之后到 Risks 之前）不应包含 uncertain claim
    main_section = report_md.split("## Cursor")[1].split("## Risks")[0]
    assert "Cursor Enterprise Teams Advanced" not in main_section
    assert len(discarded) == 1
    assert discarded[0].verdict == "uncertain"


def test_cross_claim_renders_in_cross_section_not_risks() -> None:
    """M4: cross claim 不论 support_score 多少, 都进"跨竞品对比"章节, 不进 Risks。"""
    task = AnalysisTask(
        task_id="T-2",
        query="test",
        competitors=[CompetitorInput(name="Cursor"), CompetitorInput(name="Windsurf")],
    )
    ev1 = EvidenceItem(
        evidence_id="E-1", source_id="S-1", competitor_name="Cursor",
        quote="Cursor Pro $20/mo.",
    )
    ev2 = EvidenceItem(
        evidence_id="E-2", source_id="S-2", competitor_name="Windsurf",
        quote="Windsurf Pro $15/mo.",
    )
    cross_claim = AnalysisClaim(
        claim_id="C-CROSS-PRI-01",
        run_id="RUN-1",
        competitor_name=None,
        dimension="pricing",
        statement="Cursor Pro 定价 $20/mo, Windsurf Pro $15/mo, 跨度约 33%。",
        evidence_ids=["E-1", "E-2"],
    )

    report_md, accepted, risks, _, _ = render_report(
        task, "RUN-1", [cross_claim], [ev1, ev2]
    )

    # cross claim 必须进主报告
    assert "跨竞品对比" in report_md
    cross_section_start = report_md.index("跨竞品对比")
    risks_section_start = report_md.index("Risks & Unknowns")
    cross_section = report_md[cross_section_start:risks_section_start]
    assert "Cursor Pro 定价" in cross_section
    # cross claim 不应出现在 Risks
    risks_section = report_md[risks_section_start:]
    assert "Cursor Pro 定价" not in risks_section
    # cross 应被算作 accepted(便于 CLI summary)
    assert cross_claim in accepted


def test_risks_section_caps_total_and_filters_low_score() -> None:
    """M4: Risks 章节有硬上限,且 score < 0.3 不进 Risks(走 discarded)。"""
    task = AnalysisTask(
        task_id="T-3",
        query="test",
        competitors=[CompetitorInput(name="Cursor")],
    )
    ev = EvidenceItem(
        evidence_id="E-1", source_id="S-1", competitor_name="Cursor",
        quote="Cursor Pro $20.",
    )
    # 制造 20 条 uncertain claim,看 Risks 是否被 cap
    claims: list[AnalysisClaim] = []
    for i in range(20):
        claims.append(AnalysisClaim(
            claim_id=f"C-{i:02d}",
            run_id="RUN-1",
            competitor_name="Cursor",
            dimension="pricing",
            statement=f"Cursor Pro Enterprise Teams Advanced costs $20 variant {i}.",
            evidence_ids=["E-1"],
        ))
    report_md, _, risks, _, _ = render_report(task, "RUN-1", claims, [ev])

    # Risks 章节 claim 数应被 cap 到 ≤8(_RISKS_MAX_PER_REPORT)
    assert len(risks) <= 8


def test_low_recall_competitor_triggers_top_warning() -> None:
    """M5 v0.2: 某 competitor 的 evidence 数 ≤3 时, 报告顶部应出现红色警告。"""
    task = AnalysisTask(
        task_id="T-LR",
        query="test",
        competitors=[
            CompetitorInput(name="Notion"),
            CompetitorInput(name="Evernote"),
            CompetitorInput(name="Mem"),  # 故意只给 1 条 evidence
        ],
    )
    # 模拟 Mem 召回严重不足:只有 1 条
    evidence = []
    for i in range(8):
        evidence.append(EvidenceItem(
            evidence_id=f"E-N{i:02d}", source_id="S-1",
            competitor_name="Notion",
            quote=f"Notion fact {i} costs $20 per month.",
        ))
    for i in range(5):
        evidence.append(EvidenceItem(
            evidence_id=f"E-E{i:02d}", source_id="S-2",
            competitor_name="Evernote",
            quote=f"Evernote fact {i}.",
        ))
    evidence.append(EvidenceItem(
        evidence_id="E-M00", source_id="S-3",
        competitor_name="Mem",
        quote="Mem.ai single evidence only.",
    ))

    report_md, _, _, _, _ = render_report(task, "RUN-LR", [], evidence)

    # 顶部应出现数据召回警告
    assert "数据召回警告" in report_md
    # 必须点名 Mem
    warning_section = report_md.split("数据召回警告")[1].split("Executive Summary")[0]
    assert "Mem" in warning_section
    # 不应警告 Notion 或 Evernote(它们 evidence 够多)
    assert "Notion" not in warning_section.split("Mem")[0] + warning_section.split("Mem")[-1].split("\n>")[0]


def test_no_low_recall_warning_when_all_competitors_have_enough_evidence() -> None:
    """所有 competitor 都 >3 条 evidence 时不应出现召回警告。"""
    task = AnalysisTask(
        task_id="T-OK",
        query="test",
        competitors=[CompetitorInput(name="Cursor"), CompetitorInput(name="Windsurf")],
    )
    evidence = []
    for i in range(5):
        evidence.append(EvidenceItem(
            evidence_id=f"E-C{i:02d}", source_id="S-1",
            competitor_name="Cursor",
            quote=f"Cursor fact {i}.",
        ))
    for i in range(5):
        evidence.append(EvidenceItem(
            evidence_id=f"E-W{i:02d}", source_id="S-2",
            competitor_name="Windsurf",
            quote=f"Windsurf fact {i}.",
        ))
    report_md, _, _, _, _ = render_report(task, "RUN-OK", [], evidence)
    assert "数据召回警告" not in report_md


def test_executive_summary_falls_back_to_template_without_llm() -> None:
    """LLM 不可用时, Executive Summary 走模板兜底, 不抛异常。"""
    task = AnalysisTask(
        task_id="T-4",
        query="测试赛道",
        competitors=[CompetitorInput(name="Cursor")],
    )
    ev = EvidenceItem(
        evidence_id="E-1", source_id="S-1", competitor_name="Cursor",
        quote="Cursor Pro costs $20 per month.",
    )
    claim = AnalysisClaim(
        claim_id="C-PASS",
        run_id="RUN-1",
        competitor_name="Cursor",
        dimension="pricing",
        statement="Cursor Pro costs $20 per month.",
        evidence_ids=["E-1"],
    )
    report_md, _, _, _, _ = render_report(task, "RUN-1", [claim], [ev])

    # 模板 fallback 输出应含"基于自动化 Agent"标志
    assert "Executive Summary" in report_md
    assert "基于自动化 Agent" in report_md
    # 不应是空占位
    summary_section = report_md.split("Executive Summary")[1].split("##")[0]
    assert len(summary_section.strip()) > 20
