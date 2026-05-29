from __future__ import annotations

import re
from pathlib import Path

from cs_mvp.agents.capability_contracts import AGENT_CAPABILITY_ORDER, CAPABILITY_CONTRACTS
from cs_mvp.agents.role_cards import AGENT_ROLE_ORDER, ROLE_CARDS
from cs_mvp.agents.skill_card import AgentCapabilityContract, SkillCard


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_NAMES = {"collector", "extractor", "analyst", "qa_critic", "analyst_revise", "writer"}
KNOWN_ISSUE_IDS = {str(i) for i in range(1, 13)}


def _repo_text() -> str:
    chunks: list[str] = []
    for base in (ROOT / "cs_mvp", ROOT / "tests", ROOT / "docs"):
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".md", ".txt", ".html", ".j2"}:
                chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(chunks)


def _field_tokens(signal: str) -> list[str]:
    cleaned = signal.replace("[*]", "")
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", ".", cleaned)
    tokens = [item for item in cleaned.split(".") if item and item != "json"]
    return [token for token in tokens if not token.endswith("json")]


def test_skill_card_model_construction() -> None:
    card = SkillCard(
        name="demo_skill",
        description="Demonstrate the SkillCard model.",
        inputs_schema=["sources.json"],
        outputs_schema=["evidence.json"],
        tools=["Pydantic"],
        quality_checks=["Keep evidence_id."],
        failure_modes=["KNOWN_ISSUES#1: demo failure mode."],
        observability_signals=["sources.json[*].source_id"],
    )

    assert card.short_metadata()["name"] == "demo_skill"
    assert card.short_metadata()["signals_count"] == 1


def test_capability_contract_model_construction() -> None:
    contract = AgentCapabilityContract(
        agent_name="collector",
        skills=[
            SkillCard(
                name="demo_skill",
                description="Demonstrate contract grouping.",
                inputs_schema=["task.query"],
                outputs_schema=["sources.json"],
                tools=[],
                quality_checks=["Keep source_id."],
                failure_modes=["KNOWN_ISSUES#1: demo failure mode."],
                observability_signals=["sources.json[*].source_id"],
            )
        ],
        quality_invariants=["Do not fabricate source text."],
        failure_recovery=["Expose failed fetches."],
    )

    assert contract.short_metadata()["skills_count"] == 1
    assert contract.short_metadata()["skill_names"] == ["demo_skill"]


def test_all_agents_have_capability_contracts_matching_role_cards() -> None:
    assert set(CAPABILITY_CONTRACTS) == EXPECTED_NAMES
    assert set(CAPABILITY_CONTRACTS) == set(ROLE_CARDS)
    assert AGENT_CAPABILITY_ORDER == AGENT_ROLE_ORDER


def test_contracts_are_complementary_to_role_cards() -> None:
    for name, contract in CAPABILITY_CONTRACTS.items():
        role = ROLE_CARDS[name]
        assert contract.agent_name == role.name
        assert contract.upstream_contract or not role.upstream
        assert contract.downstream_contract or not role.downstream


def test_each_contract_has_professional_skill_depth() -> None:
    for contract in CAPABILITY_CONTRACTS.values():
        assert len(contract.skills) >= 2
        assert len(contract.quality_invariants) >= 3
        assert contract.failure_recovery
        for skill in contract.skills:
            assert skill.inputs
            assert skill.outputs
            assert skill.inputs_schema
            assert skill.outputs_schema
            assert skill.quality_checks
            assert skill.failure_modes
            assert skill.observability_signals


def test_failure_modes_reference_known_issues() -> None:
    known_issues = (ROOT / "KNOWN_ISSUES.md").read_text(encoding="utf-8")

    for contract in CAPABILITY_CONTRACTS.values():
        for skill in contract.skills:
            for failure_mode in skill.failure_modes:
                match = re.search(r"KNOWN_ISSUES#(\d+)", failure_mode)
                assert match, failure_mode
                issue_id = match.group(1)
                assert issue_id in KNOWN_ISSUE_IDS
                assert f"## {issue_id}." in known_issues


def test_observability_signals_reference_real_artifact_fields() -> None:
    repo_text = _repo_text()

    for contract in CAPABILITY_CONTRACTS.values():
        for skill in contract.skills:
            for signal in skill.observability_signals:
                artifact = signal.split(".", 1)[0]
                assert f"{artifact}.json" in signal or artifact.endswith("_stats")
                tokens = _field_tokens(signal)
                assert tokens, signal
                assert any(token in repo_text for token in tokens), signal


def test_contracts_are_json_serializable() -> None:
    for contract in CAPABILITY_CONTRACTS.values():
        payload = contract.model_dump(mode="json")
        assert payload["agent_name"] == contract.agent_name
        assert isinstance(payload["skills"], list)
        assert payload["skills"][0]["observability_signals"]


def test_docs_exist_and_describe_skillcard_layer() -> None:
    doc = ROOT / "docs" / "AGENT_SKILLS.md"
    text = doc.read_text(encoding="utf-8")

    assert doc.exists()
    assert len(text.splitlines()) >= 300
    assert "SkillCards are a read-only capability contract" in text
    assert "KNOWN_ISSUES#10" in text


def test_readme_and_role_docs_link_skillcard_doc() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    roles = (ROOT / "docs" / "AGENT_ROLES.md").read_text(encoding="utf-8")

    assert "Agent SkillCards And CapabilityContracts" in readme
    assert "docs/AGENT_SKILLS.md" in readme
    assert "docs/AGENT_SKILLS.md" in roles
