# Changelog

All notable changes to this project will be documented in this file.

## [v1.2.3] - 2026-05-28

### Added
- **Vision LLM fallback**: When Playwright returns a skeleton screen (anti-scraping pages), automatically capture a screenshot and send it to a Vision LLM (Kimi / GPT-4V) for OCR extraction. Configure via `VISION_API_KEY` in `.env`.
- **`gap_fill` node**: Dynamic dimension supplement collection. After Analyst completes, scan claims for missing core dimensions (features / pricing / target_users / positioning) and issue targeted Tavily queries to fill gaps. Max 1 round, 3 URLs per competitor.

### Improved
- Playwright now scrolls page twice (50%, 100%) with 1–1.5s waits to trigger lazy-loaded content (pricing pages especially).

## [v1.2.2] - 2026-05-25

### Added
- **Dead-domain filtering**: Search layer now excludes known unscrapable domains (Zhihu, Baidu Baike, PingWest, WeChat MP, etc.) at the Tavily query level and at result post-processing.
- **Visual PPT export**: Each slide rendered as HTML/CSS → Playwright screenshot → embedded as full-page image in `report.pptx` (5 pages, ~540KB).
- **Comparison matrix**: HTML report now includes a competitor × dimension cross-comparison table.

### Improved
- Effective source rate jumped from 44% → 100% on identical AI writing assistant analysis (validated with same query).

## [v1.2.1] - 2026-05-24

### Added
- **Three-layer fetch fallback**: httpx → Playwright headless → (later v1.2.3) Vision LLM
- **PPT output (text version)**: 5-page `python-pptx` generated report bundled with each run
- **Real Run Metrics**: README table with measured cost, duration, claim count per analyzed topic
- **AI writing assistants case study**: Full walkthrough document at `docs/case_ai_writing_assistants.md`

## [v1.2.0] - 2026-05-22

### Added
- **QA Critic node**: Independent claim review before Writer, classifies each claim as accepted / risky / needs_revision
- **Analyst Revise node**: Bounded feedback loop (max 1 round) — needs_revision claims are rewritten per QA instruction
- **FastAPI Dashboard**: Web UI for run history, DAG visualization, QA audit, revision history, evidence library
- **HTML report**: Dark blue cover + 5 metric cards + 4 ECharts charts (bar / donut / horizontal bar / donut) + structured body

## [v1.1.0] - 2026-05-19

### Added
- Real web fetching via Tavily search + httpx
- Bilingual search query expansion (Chinese + English)

## [v1.0.0] - 2026-05

### Added
- Initial 5-node LangGraph DAG with mock data
- Core models: SourceRecord, EvidenceItem, AnalysisClaim
