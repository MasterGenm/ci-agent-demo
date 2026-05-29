from cs_mvp.agents.skill_card import AgentCapabilityContract, SkillCard


ANALYST_CAPABILITY = AgentCapabilityContract(
    agent_name="analyst",
    skills=[
        SkillCard(
            name="single_competitor_claim_generation",
            purpose="Generate evidence-backed claims per competitor and business dimension.",
            inputs=["evidence.json", "task.competitors", "analysis dimensions"],
            outputs=["claims.json", "discarded_claims.json"],
            tools=["LLM", "Pydantic structured output", "bilingual validator"],
            quality_checks=[
                "All evidence_ids must exist in the run evidence map.",
                "Generated claims keep dimension, statement, evidence_ids, and accepted state.",
            ],
            failure_modes=[
                "KNOWN_ISSUES#10: Analyst can still produce interpretive claims that are not literal in evidence.",
            ],
            observability_signals=[
                "claims.json[*].claim_id",
                "claims.json[*].support_score",
                "claims.json[*].interpretive_risk",
            ],
        ),
        SkillCard(
            name="cross_competitor_claim_generation",
            purpose="Build comparison claims across competitors while keeping evidence linkage explicit.",
            inputs=["grouped EvidenceItem records", "competitor set"],
            outputs=["claims.json", "discarded_claims.json"],
            tools=["evidence grouping", "LLM"],
            quality_checks=[
                "Cross claims cite evidence from at least two different competitors.",
                "Unsupported cross claims are discarded or marked uncertain by downstream verification.",
            ],
            failure_modes=[
                "KNOWN_ISSUES#3: long cross-competitor claims are vulnerable to strict verifier under-credit.",
            ],
            observability_signals=[
                "claim_summary.json.cross_claims",
                "claims.json[*].evidence_ids",
                "discarded_claims.json[*].verdict",
            ],
        ),
        SkillCard(
            name="phase3_insight_candidates",
            purpose="Create lightweight strategic insight candidates without forcing them into accepted claims.",
            inputs=["claims.json", "evidence.json"],
            outputs=["claims.json", "review_queue.json"],
            tools=["interpretive guard", "review_queue"],
            quality_checks=[
                "Insight candidates stay accepted=False until independently supported.",
                "Risky interpretation is flagged for review rather than promoted silently.",
            ],
            failure_modes=[
                "KNOWN_ISSUES#10: strategic implications can drift beyond the literal source text.",
            ],
            observability_signals=[
                "claims.json[*].insight_candidate",
                "review_queue.json[*].type",
                "review_queue.json[*].claim_id",
            ],
        ),
    ],
    quality_invariants=[
        "Analyst claims must reference existing evidence_ids.",
        "Analyst failures are recorded instead of entering accepted claims.",
        "Interpretive claims must remain visible through risk or review artifacts.",
    ],
    failure_recovery={
        "schema_invalid_output": "Drop schema-invalid outputs into analyst_failures.json.",
        "weak_claim": "Use QA Critic and Writer guards to prevent weak claims from becoming final conclusions.",
    },
    upstream_contract={"extractor": "Provides evidence.json with source-linked quotes."},
    downstream_contract={"qa_critic": "Audits claims before writer presentation."},
)
