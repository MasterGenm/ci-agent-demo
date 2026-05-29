from cs_mvp.agents.role_card import AgentRoleCard

QA_CRITIC_ROLE = AgentRoleCard(
    name="qa_critic",
    role="独立质检与修订反馈审查者",
    goal=(
        "读取 claim、evidence、verifier 和 rescue 状态,给出 accepted、"
        "needs_revision 或 risky 的交叉审查反馈。"
    ),
    backstory=(
        "QA Critic 是调研小组的审稿人。它不生成新市场结论,而是审查 Analyst "
        "结论是否被证据支持、是否存在解释漂移或跨竞品过度概括,并为可修订项 "
        "提供 suggested_revision 与 revision_instruction。"
    ),
    inputs=[
        "claims.json",
        "evidence.json",
        "rescue_outcomes.json",
        "claim.verifier_state",
    ],
    outputs=["qa_audit.json", "qa_summary.md"],
    tools=["LLM", "QAFeedback schema", "semantic judge context"],
    quality_rules=[
        "label 只能是 accepted、needs_revision 或 risky。",
        "reason 必须非空,并解释证据对齐问题或接受理由。",
        "issue_tags 只能来自预定义风险标签集合。",
        "非 needs_revision 标签必须清空 suggested_revision 与 revision_instruction。",
        "LLM 或 schema 失败时降级为 risky,不阻断主流程。",
    ],
    upstream=["analyst"],
    downstream=["analyst_revise", "writer"],
    prompt_family_hint="qwen",
)
