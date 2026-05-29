from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_exists():
    assert (ROOT / "Dockerfile").exists()


def test_docker_compose_exists():
    assert (ROOT / "docker-compose.yml").exists()


def test_github_workflow_exists():
    assert (ROOT / ".github" / "workflows" / "ci.yml").exists()


def test_screenshots_dir_with_guide():
    sc_dir = ROOT / "docs" / "screenshots"

    assert sc_dir.exists()
    assert (sc_dir / "README.md").exists()
    assert (sc_dir / ".gitkeep").exists()


def test_readme_contains_v1_5_keywords():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    must_have = [
        "Langfuse",
        "Docker",
        "GitHub Actions",
        "Pydantic v2",
        "LangGraph",
        "v1.5",
    ]

    for keyword in must_have:
        assert keyword in readme, f"README missing keyword: {keyword}"


def test_readme_contains_required_sections():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    required_headings = [
        "## Problem",
        "## Solution",
        "## Who It Is For",
        "## ROI",
        "## Quick Start",
        "## Architecture And Tech Stack",
        "## Demo Screenshots",
        "## What Is Special",
        "## Open Source Peer Comparison",
        "## Status And License",
    ]

    for heading in required_headings:
        assert heading in readme


def test_readme_contains_mermaid_diagram():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "```mermaid" in readme
    assert "Langfuse Cloud" in readme


def test_readme_references_all_screenshot_placeholders():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    expected = [
        "docs/screenshots/01-home.png",
        "docs/screenshots/02-dag.png",
        "docs/screenshots/03-qa-critic.png",
        "docs/screenshots/04-revision.png",
        "docs/screenshots/05-report.png",
        "docs/screenshots/06-schema.png",
        "docs/screenshots/07-langfuse.png",
    ]

    for image_path in expected:
        assert image_path in readme


def test_env_example_includes_langfuse_cloud_keys():
    env = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "LANGFUSE_PUBLIC_KEY" in env
    assert "LANGFUSE_SECRET_KEY" in env
    assert "https://cloud.langfuse.com" in env


def test_pyproject_includes_langfuse_dependency():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "langfuse>=2.50" in pyproject
    assert "langfuse>=2.50,<3" in pyproject
