from cs_mvp.agents.skill_card import AgentCapabilityContract, SkillCard


EXTRACTOR_CAPABILITY = AgentCapabilityContract(
    agent_name="extractor",
    skills=[
        SkillCard(
            name="chunked_evidence_extraction",
            purpose="Turn fetched source text into bounded EvidenceItem records.",
            inputs=["sources.json[*].raw_text", "sources.json[*].competitor_name"],
            outputs=["evidence.json", "evidence_summary.json"],
            tools=["TextChunker", "LLM", "Pydantic structured output"],
            quality_checks=[
                "Only fetched sources with non-empty raw_text are processed.",
                "Each emitted EvidenceItem keeps evidence_id, source_id, quote, and claim_type.",
            ],
            failure_modes=[
                "KNOWN_ISSUES#6: broad Chinese substring windows can hide weak quote alignment.",
            ],
            observability_signals=[
                "evidence.json[*].evidence_id",
                "evidence.json[*].quote",
                "evidence.json[*].confidence",
            ],
        ),
        SkillCard(
            name="quote_match_guard",
            purpose="Keep evidence auditable by checking that quotes can be traced to source text.",
            inputs=["SourceRecord.raw_text", "EvidenceItem.quote"],
            outputs=["extractor_failures.json", "evidence_summary.json"],
            tools=["quote normalizer", "schema validator"],
            quality_checks=[
                "quote_match_rate is reported even when no evidence is emitted.",
                "Quote mismatch failures are kept as extractor_failures records.",
            ],
            failure_modes=[
                "KNOWN_ISSUES#3: strict literal matching can under-score long synthesized claims.",
                "KNOWN_ISSUES#6: loose matching can over-credit weak bilingual evidence alignment.",
            ],
            observability_signals=[
                "extractor_failures.json[*].stage",
                "evidence_summary.json.quote_match_rate",
                "evidence_summary.json.schema_pass_rate",
            ],
        ),
        SkillCard(
            name="extraction_budget_guard",
            purpose="Stop extraction before LLM budget overrun while preserving partial artifacts.",
            inputs=["Extractor budget config", "source chunks"],
            outputs=["evidence.json", "extractor_failures.json"],
            tools=["cost estimator"],
            quality_checks=[
                "Budget guard stops new chunks rather than dropping already extracted evidence.",
                "Extractor stats are available for run_summary and cost_summary aggregation.",
            ],
            failure_modes=[
                "KNOWN_ISSUES#4: fallback pricing is not fully calibrated across providers.",
            ],
            observability_signals=[
                "cost_summary.json.by_node.extractor",
                "trace.json.node_runs[*].cost_usd",
                "trace.json.node_runs[*].latency_ms",
            ],
        ),
    ],
    quality_invariants=[
        "Extractor does not write analysis conclusions.",
        "Extractor emits only schema-valid EvidenceItem records.",
        "Extractor keeps quote and source_id for every evidence item.",
    ],
    failure_recovery={
        "quote_or_schema_failure": "Keep extractor_failures.json for quote and schema failures.",
        "manual_review": "Let review_queue surface quote mismatch and failed source cases.",
    },
    upstream_contract={"collector": "Provides sources.json with fetch_status and raw_text."},
    downstream_contract={"analyst": "Consumes evidence.json and evidence_summary.json."},
)
