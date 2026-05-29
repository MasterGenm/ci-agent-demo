from cs_mvp.agents.skill_card import AgentCapabilityContract, SkillCard


ANALYST_REVISE_CAPABILITY = AgentCapabilityContract(
    agent_name="analyst_revise",
    skills=[
        SkillCard(
            name="controlled_claim_rewrite",
            purpose="Rewrite only claims that QA Critic marked needs_revision.",
            inputs=["claims.json", "qa_audit.json", "revision_instruction"],
            outputs=["revision_history.json", "revised AnalysisClaim list"],
            tools=["LLM", "LLMRevision schema"],
            quality_checks=[
                "Only needs_revision feedback is processed.",
                "The original claim is kept if schema validation fails.",
            ],
            failure_modes=[
                "KNOWN_ISSUES#11: rescue-path write semantics were previously inconsistent and require regression coverage.",
            ],
            observability_signals=[
                "revision_history.json.total_revisions",
                "revision_history.json.revisions[*].revision_round",
                "revision_history.json.revisions[*].revision_failed",
            ],
        ),
        SkillCard(
            name="evidence_scope_guard",
            purpose="Prevent revision from adding evidence that was not attached to the original claim.",
            inputs=["original_evidence_ids", "revised_evidence_ids"],
            outputs=["revision_history.json"],
            tools=["evidence whitelist", "RevisionRecord schema"],
            quality_checks=[
                "revised_evidence_ids must be a subset of original_evidence_ids.",
                "Invalid evidence references set revision_failed=True.",
            ],
            failure_modes=[
                "KNOWN_ISSUES#10: model rewrites can still try to widen the evidence boundary.",
            ],
            observability_signals=[
                "revision_history.json.revisions[*].original_evidence_ids",
                "revision_history.json.revisions[*].revised_evidence_ids",
                "revision_history.json.revisions[*].failure_reason",
            ],
        ),
    ],
    quality_invariants=[
        "Analyst Revise never performs new collection or extraction.",
        "Max revision rounds are enforced outside this metadata layer.",
        "Every revision is auditable through RevisionRecord fields.",
    ],
    failure_recovery={
        "invalid_revised_evidence": "Keep the original claim on invalid revised evidence IDs.",
        "revision_failed": "Write revision_failed and failure_reason for manual audit.",
    },
    upstream_contract={"qa_critic": "Provides needs_revision feedback with instruction."},
    downstream_contract={"qa_critic": "Rechecks revised claims."},
)
