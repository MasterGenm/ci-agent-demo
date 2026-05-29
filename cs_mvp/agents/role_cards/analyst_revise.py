from cs_mvp.agents.role_card import AgentRoleCard

ANALYST_REVISE_ROLE = AgentRoleCard(
    name="analyst_revise",
    role="受控二次生成与证据边界修订者",
    goal=(
        "只处理 QA Critic 标记为 needs_revision 的 claim,严格按 revision_instruction "
        "改写且不新增 evidence。"
    ),
    backstory=(
        "Analyst Revise 是反馈闭环中的受控改稿员。它只在 revision loop 开启且 "
        "max_revision_rounds 未触顶时工作,复用原始 evidence_ids,把每次改写轨迹 "
        "写入 revision_history.json。"
    ),
    inputs=["claims.json", "qa_audit.json", "evidence.json", "revision_round"],
    outputs=["revision_history.json", "revision_summary.md", "revised AnalysisClaim list"],
    tools=["LLM", "LLMRevision schema", "cost estimator"],
    quality_rules=[
        "只修订 label=needs_revision 的 feedback,其他 label 直接拒绝处理。",
        "kept_evidence_ids 必须是原 claim evidence_ids 的子集。",
        "不允许新增 evidence_id,也不允许输出空 revised_statement。",
        "revision_failed=True 或 schema 失败时保留原 claim 并写 failure_reason。",
        "每条 RevisionRecord 必须记录 before/after statement、QA 原因和成本。",
    ],
    upstream=["qa_critic"],
    downstream=["qa_critic"],
    prompt_family_hint="qwen",
)
