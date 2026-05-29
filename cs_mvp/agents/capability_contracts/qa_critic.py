from cs_mvp.agents.skill_card import AgentCapabilityContract, SkillCard


QA_CRITIC_CAPABILITY = AgentCapabilityContract(
    agent_name="qa_critic",
    skills=[
        SkillCard(
            name="three_state_claim_audit",
            purpose="Classify claims as accepted, needs_revision, or risky using evidence context.",
            inputs=["claims.json", "evidence.json", "rescue_outcomes.json"],
            outputs=["qa_audit.json", "qa_summary.md", "review_queue.json"],
            tools=["LLM", "QAFeedback schema", "semantic judge context"],
            quality_checks=[
                "Every feedback item uses an allowed label and non-empty reason.",
                "risky and needs_revision claims remain visible for review.",
            ],
            failure_modes=[
                "KNOWN_ISSUES#3: long cross claims can receive overly strict evidence alignment judgement.",
                "KNOWN_ISSUES#9: verifier false-injury counts are not fully quantified for all cases.",
            ],
            observability_signals=[
                "qa_audit.json.feedbacks[*].label",
                "qa_audit.json.needs_revision_count",
                "qa_audit.json.risky_count",
            ],
        ),
        SkillCard(
            name="revision_instruction_generation",
            purpose="Create bounded revision instructions for claims that should enter the feedback loop.",
            inputs=["QAFeedback", "AnalysisClaim", "EvidenceItem"],
            outputs=["qa_audit.json", "revision_history.json"],
            tools=["LLM", "revision_instruction policy"],
            quality_checks=[
                "Only needs_revision feedback can keep suggested_revision or revision_instruction.",
                "The instruction must not request new evidence or new competitor research.",
            ],
            failure_modes=[
                "KNOWN_ISSUES#10: revision requests can reveal claims that over-interpret the evidence.",
            ],
            observability_signals=[
                "qa_audit.json.feedbacks[*].revision_instruction",
                "qa_audit.json.feedbacks[*].issue_tags",
                "revision_history.json.revisions[*].qa_label_before",
            ],
        ),
    ],
    quality_invariants=[
        "QA Critic never creates new market evidence.",
        "QA labels stay in accepted, needs_revision, or risky.",
        "Schema failure degrades to risky instead of blocking the run.",
    ],
    failure_recovery={
        "needs_revision": "Route needs_revision to Analyst Revise when revision loop is enabled.",
        "risky": "Route risky feedback to review_queue for human follow-up.",
    },
    upstream_contract={"analyst": "Provides claims with evidence_ids."},
    downstream_contract={
        "analyst_revise": "Consumes only needs_revision instructions.",
        "writer": "Reads qa_audit as context.",
    },
)
