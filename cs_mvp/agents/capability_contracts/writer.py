from cs_mvp.agents.skill_card import AgentCapabilityContract, SkillCard


WRITER_CAPABILITY = AgentCapabilityContract(
    agent_name="writer",
    skills=[
        SkillCard(
            name="report_template_render",
            purpose="Assemble accepted claims, evidence appendix, risks, and metadata into report artifacts.",
            inputs=["claims.json", "evidence.json", "task", "node_modes"],
            outputs=["report.md", "report.html", "writer_stats.json"],
            tools=["Jinja2", "CitationVerifier", "HTML exporter"],
            quality_checks=[
                "Single-competitor claims pass verifier before entering main report sections.",
                "Cross claims remain visible with support_score context.",
            ],
            failure_modes=[
                "KNOWN_ISSUES#3: strict verification can injure long cross-competitor claims.",
            ],
            observability_signals=[
                "writer_stats.json.llm_cost_usd",
                "claims.json[*].accepted",
                "claims.json[*].support_score",
            ],
        ),
        SkillCard(
            name="executive_summary_fallback",
            purpose="Generate or fallback the Executive Summary without blocking report creation.",
            inputs=["claims.json", "writer_stats.json"],
            outputs=["report.md", "writer_stats.json"],
            tools=["LLM", "template fallback"],
            quality_checks=[
                "LLM summary failure falls back to a deterministic template summary.",
                "Summary cost is routed into writer_stats and cost_summary.",
            ],
            failure_modes=[
                "KNOWN_ISSUES#7: Executive Summary fallback can look simple or template-like.",
                "KNOWN_ISSUES#4: fallback pricing is not fully calibrated across providers.",
            ],
            observability_signals=[
                "writer_stats.json.mode",
                "writer_stats.json.model",
                "cost_summary.json.by_node.writer",
            ],
        ),
        SkillCard(
            name="risk_and_review_export",
            purpose="Keep uncertain, risky, low-recall, and insight-candidate cases visible after writing.",
            inputs=["discarded_claims.json", "qa_audit.json", "run_summary.json"],
            outputs=["review_queue.json", "report.md"],
            tools=["review_queue", "risk section renderer"],
            quality_checks=[
                "Risks and Unknowns does not silently promote weak claims.",
                "review_queue keeps uncertain, failed, low_recall, and qa_critic entries.",
            ],
            failure_modes=[
                "KNOWN_ISSUES#8: simulated PM validation means review_queue still needs real human review.",
            ],
            observability_signals=[
                "review_queue.json[*].severity",
                "review_queue.json[*].qa_label",
                "run_summary.json.quality_gates.has_report",
            ],
        ),
    ],
    quality_invariants=[
        "Writer never invents new sources or evidence.",
        "Writer keeps evidence-backed claims linked to Evidence Appendix.",
        "Writer surfaces risks instead of hiding unsupported claims.",
    ],
    failure_recovery={
        "summary_llm_failure": "Fallback Executive Summary keeps report generation available.",
        "human_follow_up": "review_queue preserves human follow-up items.",
    },
    upstream_contract={
        "qa_critic": "Provides audited claim state.",
        "analyst_revise": "May provide revised claims.",
    },
    downstream_contract={},
)
