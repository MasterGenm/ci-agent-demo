from cs_mvp.agents.role_card import AgentRoleCard
from cs_mvp.agents.role_cards import AGENT_ROLE_ORDER, ROLE_CARDS


EXPECTED_NAMES = {
    "collector",
    "extractor",
    "analyst",
    "qa_critic",
    "analyst_revise",
    "writer",
}

EXPECTED_EDGES = {
    "collector": ([], ["extractor"]),
    "extractor": (["collector"], ["analyst"]),
    "analyst": (["extractor"], ["qa_critic", "writer"]),
    "qa_critic": (["analyst"], ["analyst_revise", "writer"]),
    "analyst_revise": (["qa_critic"], ["qa_critic"]),
    "writer": (["qa_critic"], []),
}


def test_role_card_model_construction():
    card = AgentRoleCard(
        name="collector",
        role="公开信息采集与网页抓取者",
        goal="把竞品调研问题转化为公开来源 artifact。",
        backstory="用于测试的 Collector RoleCard,只表达角色契约不改变运行逻辑。",
        inputs=["task.query"],
        outputs=["sources.json"],
        tools=["Tavily"],
        quality_rules=["必须保留 source_id。"],
    )

    assert card.name == "collector"
    assert card.short_metadata()["role"] == card.role


def test_all_6_agents_have_role_cards():
    assert set(ROLE_CARDS) == EXPECTED_NAMES
    assert AGENT_ROLE_ORDER == [
        "collector",
        "extractor",
        "analyst",
        "qa_critic",
        "analyst_revise",
        "writer",
    ]


def test_role_card_inputs_outputs_non_empty():
    for card in ROLE_CARDS.values():
        assert card.inputs
        assert card.outputs


def test_role_card_quality_rules_min_4():
    for card in ROLE_CARDS.values():
        assert len(card.quality_rules) >= 4


def test_role_card_upstream_downstream_consistency():
    for name, (upstream, downstream) in EXPECTED_EDGES.items():
        card = ROLE_CARDS[name]
        assert card.upstream == upstream
        assert card.downstream == downstream


def test_role_card_prompt_family_hint_valid():
    allowed = {None, "qwen", "openai", "anthropic"}
    for card in ROLE_CARDS.values():
        assert card.prompt_family_hint in allowed


def test_role_card_field_lengths():
    for card in ROLE_CARDS.values():
        assert 10 <= len(card.role) <= 80
        assert 20 <= len(card.goal) <= 200
        assert 30 <= len(card.backstory) <= 400


def test_role_card_json_serializable():
    for card in ROLE_CARDS.values():
        payload = card.model_dump(mode="json")
        assert payload["name"] == card.name
        assert isinstance(payload["quality_rules"], list)


def test_role_card_outputs_match_expected_artifacts():
    assert "sources.json" in ROLE_CARDS["collector"].outputs
    assert "evidence.json" in ROLE_CARDS["extractor"].outputs
    assert "claims.json" in ROLE_CARDS["analyst"].outputs
    assert "qa_audit.json" in ROLE_CARDS["qa_critic"].outputs
    assert "revision_history.json" in ROLE_CARDS["analyst_revise"].outputs
    assert "report.md" in ROLE_CARDS["writer"].outputs
