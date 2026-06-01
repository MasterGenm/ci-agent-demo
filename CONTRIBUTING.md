# Contributing to CI-Agent

Thanks for considering a contribution! This project is in active development; small, focused PRs are easiest to review.

## Quick Setup

```bash
git clone https://github.com/MasterGenm/ci-agent-demo.git
cd ci-agent
pip install -e ".[dev]"
cp .env.example .env
# Fill in TAVILY_API_KEY and your LLM provider keys

# Run tests
pytest tests/ -q

# Start dashboard for manual testing
python -m cs_mvp.cli serve --host 127.0.0.1 --port 8003
```

## Code Style

- **Formatter**: `ruff format` (4-space indent, line length 100)
- **Linter**: `ruff check`
- **Type checker**: `mypy cs_mvp/`
- **Pre-commit**: Install hooks with `pre-commit install`

## Pull Request Guidelines

1. **One concern per PR**. If you find a bug while adding a feature, file the bug fix separately.
2. **Tests required** for new logic. Mock external services (Tavily, LLM) — don't hit real APIs in CI.
3. **Update `CHANGELOG.md`** under an `[Unreleased]` section.
4. **No business logic changes** in formatting-only PRs.

## What to Work On

Good first issues:
- Adding a new LLM provider adapter in `cs_mvp/tools/llm.py`
- Improving HTML report styling in `cs_mvp/artifacts.py`
- Writing a new dimension prompt in `cs_mvp/prompts/`

Avoid for now (architectural changes need discussion first):
- Modifying the LangGraph DAG topology in `cs_mvp/graph.py`
- Changing Pydantic models in `cs_mvp/models.py` (downstream artifacts depend on schema)

## Reporting Issues

Please include:
- Python version and OS
- Full `.env` (with **secrets redacted**)
- The CLI command you ran
- Last 30 lines of stderr / `runs/<task_id>/run.log`

## License

By contributing, you agree your contributions are licensed under the MIT License.
