from cs_mvp.agents.skill_card import AgentCapabilityContract, SkillCard


COLLECTOR_CAPABILITY = AgentCapabilityContract(
    agent_name="collector",
    skills=[
        SkillCard(
            name="seed_url_priority_fetch",
            purpose="Prefer user-provided competitor URLs and preserve fetch outcomes as source artifacts.",
            inputs=[
                "task.query",
                "task.competitors[*].seed_urls",
                "task.competitors[*].exclude_keywords",
            ],
            outputs=["sources.json", "source_summary.json"],
            tools=["httpx", "BeautifulSoup", "lxml"],
            quality_checks=[
                "Every SourceRecord keeps source_id, competitor_name, url, and fetch_status.",
                "Failed and empty pages keep failure_reason instead of disappearing.",
            ],
            failure_modes=[
                "KNOWN_ISSUES#1: short or niche competitor names can pollute recall before seed URLs are added.",
                "KNOWN_ISSUES#5: Chinese Tavily queries can drift toward unrelated URLs.",
            ],
            observability_signals=[
                "sources.json[*].fetch_status",
                "sources.json[*].failure_reason",
                "sources.json[*].raw_text_length",
            ],
        ),
        SkillCard(
            name="search_result_filtering",
            purpose="Search, normalize, filter, and rank public URLs before downstream extraction.",
            inputs=["task.query", "task.competitors[*].name", "exclude_keywords"],
            outputs=["sources.json"],
            tools=["Tavily", "url_utils", "source_type scoring"],
            quality_checks=[
                "Exclude keywords are applied before URL normalization and deduplication.",
                "source_type and reliability_score are retained for later quality summaries.",
            ],
            failure_modes=[
                "KNOWN_ISSUES#2: Chinese query plus English niche brand can reduce useful recall.",
                "KNOWN_ISSUES#1: generic brand names such as Mem or Box need stronger disambiguation.",
            ],
            observability_signals=[
                "sources.json[*].source_type",
                "sources.json[*].reliability_score",
                "run_summary.json.quality_gates.low_recall_competitors",
            ],
        ),
        SkillCard(
            name="low_recall_audit",
            purpose="Expose weak collection coverage so the report can warn instead of overclaim.",
            inputs=["sources.json", "evidence.json"],
            outputs=["run_summary.json", "review_queue.json"],
            tools=["quality_gates", "review_queue"],
            quality_checks=[
                "Low recall competitors are surfaced in run_summary quality_gates.",
                "Review queue can include low_recall_competitor entries for manual follow-up.",
            ],
            failure_modes=[
                "KNOWN_ISSUES#8: validation can remain simulated unless a real reviewer acts on low-recall warnings.",
            ],
            observability_signals=[
                "run_summary.json.quality_gates.low_recall_competitors",
                "review_queue.json[*].type",
                "review_queue.json[*].severity",
            ],
        ),
    ],
    quality_invariants=[
        "Collector never fabricates source content.",
        "Collector records failed fetches with fetch_status and failure_reason.",
        "Collector output stays scoped to SourceRecord artifacts.",
    ],
    failure_recovery={
        "noisy_search_recall": "Use seed_urls when search recall is noisy.",
        "low_recall": "Move failed or low-recall cases to review_queue instead of suppressing them.",
    },
    upstream_contract={},
    downstream_contract={"extractor": "Consumes only fetched sources with raw_text."},
)
