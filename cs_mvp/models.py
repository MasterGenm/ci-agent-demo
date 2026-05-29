from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# v1.2 Schema 显式化:所有 run artifact 在产生时记录此版本。
# Bump 规则:Pydantic 模型字段非向后兼容变化(删字段/改语义)时升 major;
# 新增可选字段升 minor;文档/comment 修订不升。
SCHEMA_VERSION = "1.2.0"


class TaskScope(BaseModel):
    geography: str = "global"
    language: str = "zh-CN"
    time_window: str = "last_12_months"


class CompetitorInput(BaseModel):
    name: str
    website: Optional[str] = None
    # M3 前置修复:消歧用。例如 GitHub Copilot vs Microsoft 365 Copilot:
    #   name="GitHub Copilot"
    #   aliases=["copilot"] (统一 evidence_id 用 name,但搜索时 alias 用作补充关键词)
    #   exclude_keywords=["microsoft 365", "copilot studio", "copilot money"]
    # search 阶段把 exclude_keywords 通过否定关键词加进 Tavily query
    # collector 阶段对 URL/title/snippet 含 exclude 词的结果过滤
    aliases: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    seed_urls: list[str] = Field(default_factory=list)


class AnalysisTask(BaseModel):
    task_id: str
    query: str
    competitors: list[CompetitorInput]
    schema_version: str = SCHEMA_VERSION
    scope: TaskScope = Field(default_factory=TaskScope)
    status: Literal["planned", "running", "completed", "failed"] = "planned"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


class AgentRun(BaseModel):
    run_id: str
    task_id: str
    schema_version: str = SCHEMA_VERSION
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None
    status: Literal["running", "completed", "failed"] = "running"
    total_cost_usd: float = 0.0
    total_tokens: int = 0


class AgentNodeRun(BaseModel):
    node_run_id: str
    run_id: str
    node_name: Literal[
        "task_init",
        "collector",
        "extractor",
        "analyst",
        "gap_fill",
        "analyst_revise",
        "qa_critic",
        "writer",
        "finalize",
    ]
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    input_json: Optional[str] = None
    output_json: Optional[str] = None
    llm_model: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    latency_ms: Optional[int] = None
    error_message: Optional[str] = None


class SourceRecord(BaseModel):
    source_id: str
    run_id: str
    competitor_name: str
    url: str
    title: Optional[str] = None
    source_type: Literal["official_site", "pricing", "docs", "blog", "news", "other"] = (
        "other"
    )
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)
    published_at: Optional[datetime] = None
    content_hash: Optional[str] = None
    raw_text: Optional[str] = None
    reliability_score: float = 0.5
    fetch_status: Literal["fetched", "failed", "skipped", "empty"] = "skipped"
    failure_reason: Optional[
        Literal[
            "timeout",
            "non_200",
            "parse_empty",
            "too_short",
            "blocked",
            "duplicate",
            "unknown",
        ]
    ] = None
    raw_text_length: int = 0


class EvidenceItem(BaseModel):
    evidence_id: str
    source_id: str
    competitor_name: str
    claim_type: Literal["feature", "pricing", "positioning", "metric", "other"] = "other"
    quote: str
    normalized_fact: Optional[str] = None
    confidence: Optional[float] = None
    extracted_at: datetime = Field(default_factory=datetime.utcnow)
    source_chunk_index: Optional[int] = None


class AnalysisClaim(BaseModel):
    claim_id: str
    run_id: str
    competitor_name: Optional[str] = None
    dimension: Literal[
        "features",
        "pricing",
        "positioning",
        "swot",
        "target_users",
        "strategic_implications",
    ]
    statement: str
    evidence_ids: list[str]
    support_score: Optional[float] = None
    confidence: Optional[float] = None
    accepted: bool = True
    rescued_by_llm_judge: bool = False
    rescue_judge_verdict: Optional[str] = None
    rescue_judge_confidence: Optional[float] = None
    rescue_gates_passed: Optional[list[str]] = None
    rescue_original_score: Optional[float] = None
    interpretive_risk: bool = False
    interpretive_hits: Optional[list[str]] = None
    insight_candidate: bool = False


class DiscardedClaim(BaseModel):
    claim_id: str
    statement: str
    evidence_ids: list[str]
    support_score: float
    verdict: Literal["fail", "uncertain"]
    reason: str
    dropped_at: datetime = Field(default_factory=datetime.utcnow)


class Report(BaseModel):
    report_id: str
    run_id: str
    format: Literal["md", "json"]
    file_path: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class QAFeedback(BaseModel):
    """单条 claim 的质检判定(Batch 2 由 QA Critic Agent 产生)。

    label 语义:
      - accepted:claim 经 QA Critic 审查通过,可进入主报告
      - needs_revision:claim 有问题,v1.2 仅标记,不触发自动重生成
      - risky:claim 边缘可疑,建议人工复核
    """

    claim_id: str
    label: Literal["accepted", "needs_revision", "risky"]
    reason: str
    issue_tags: list[str] = Field(default_factory=list)
    suggested_revision: Optional[str] = None
    revision_instruction: Optional[str] = None


class QAAudit(BaseModel):
    """整个 run 的质检 audit 报告(写盘到 qa_audit.json)。"""

    run_id: str
    schema_version: str = SCHEMA_VERSION
    audited_at: datetime = Field(default_factory=datetime.utcnow)
    total_claims_audited: int
    accepted_count: int
    needs_revision_count: int
    risky_count: int
    feedbacks: list[QAFeedback] = Field(default_factory=list)
    auditor_model: Optional[str] = None
    llm_cost_usd: float = 0.0
    notes: Optional[str] = None


class RevisionRecord(BaseModel):
    """v1.3 feedback-loop audit record for a single revised claim."""

    claim_id: str
    revision_round: int
    original_statement: str
    original_evidence_ids: list[str]
    qa_label_before: Literal["needs_revision", "risky"]
    qa_reason: str
    qa_issue_tags: list[str] = Field(default_factory=list)
    suggested_revision: Optional[str] = None
    revision_instruction: Optional[str] = None
    revised_statement: str
    revised_evidence_ids: list[str]
    revision_explanation: Optional[str] = None
    revision_failed: bool = False
    failure_reason: Optional[str] = None
    qa_label_after: Literal["accepted", "needs_revision", "risky"] = "needs_revision"
    max_revision_reached: bool = False
    revise_cost_usd: float = 0.0
    revised_at: datetime = Field(default_factory=datetime.utcnow)


class GraphState(BaseModel):
    task: AnalysisTask
    run_id: str
    sources: list[SourceRecord] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    claims: list[AnalysisClaim] = Field(default_factory=list)
    discarded_claims: list[DiscardedClaim] = Field(default_factory=list)
    qa_audit: Optional[dict[str, Any]] = None
    gap_fill_round: int = 0
    revision_round: int = 0
    revision_history: list[dict[str, Any]] = Field(default_factory=list)
    report_md: str = ""
    error: Optional[str] = None
