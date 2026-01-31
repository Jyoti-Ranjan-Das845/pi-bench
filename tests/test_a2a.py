"""Tests for A2A Green Agent integration."""

import pytest

from pi_bench.a2a.server import (
    A2AMessage,
    A2AMessagePart,
    A2ARequest,
    get_agent_card,
    parse_assessment_request,
)
from pi_bench.a2a.scenarios import (
    ALL_SCENARIOS,
    get_scenario,
    get_scenarios_by_surface,
    scenario_to_task_message,
)
from pi_bench.a2a.results import (
    episode_to_task_result,
    summary_to_metrics,
)
from pi_bench.types import (
    EpisodeResult,
    EpisodeMetadata,
    PolicyScore,
    PolicyVerdict,
    SummaryMetrics,
    TaskScore,
    TraceValidation,
)


class TestAgentCard:
    """Test agent card (metadata)."""

    def test_agent_card_has_required_fields(self):
        card = get_agent_card()
        assert card["name"] == "PolicyBeats"
        assert "version" in card
        assert "url" in card
        assert "capabilities" in card

    def test_agent_card_capabilities(self):
        card = get_agent_card()
        assert card["capabilities"]["assessment"] is True
        assert card["capabilities"]["streaming"] is False

    def test_agent_card_metadata(self):
        card = get_agent_card()
        assert "metadata" in card
        assert card["metadata"]["category"] == "Agent Safety"
        assert card["metadata"]["deterministic"] is True
        assert card["metadata"]["no_llm_judges"] is True


class TestScenarios:
    """Test policy compliance scenarios."""

    def test_all_scenarios_loaded(self):
        assert len(ALL_SCENARIOS) == 8

    def test_scenarios_cover_all_surfaces(self):
        surfaces = {s.surface for s in ALL_SCENARIOS}
        assert surfaces == {"A", "B", "C", "D", "E", "F"}

    def test_get_scenario_by_id(self):
        scenario = get_scenario("A1-role-required")
        assert scenario is not None
        assert scenario.name == "Role Required for Account Access"

    def test_get_scenario_not_found(self):
        assert get_scenario("nonexistent") is None

    def test_get_scenarios_by_surface(self):
        # Surface B has 2 scenarios (B1 and B2)
        b_scenarios = get_scenarios_by_surface("B")
        assert len(b_scenarios) == 2
        assert all(s.surface == "B" for s in b_scenarios)

    def test_scenario_to_task_message(self):
        scenario = ALL_SCENARIOS[0]
        msg = scenario_to_task_message(scenario)
        assert "scenario_id" in msg
        assert "instruction" in msg
        assert "system_prompt" in msg
        assert "tools" in msg
        assert "context" in msg

    def test_each_scenario_has_policy_pack(self):
        for scenario in ALL_SCENARIOS:
            assert scenario.policy_pack is not None
            assert len(scenario.policy_pack.rules) > 0


class TestA2AProtocol:
    """Test A2A protocol parsing."""

    def test_parse_assessment_request_valid(self):
        message = A2AMessage(
            role="user",
            parts=[
                A2AMessagePart(
                    kind="text",
                    text='{"purple_agent_url": "http://example.com/a2a", "purple_agent_id": "agent-123"}',
                )
            ],
            messageId="msg-1",
        )
        request = parse_assessment_request(message)
        assert request is not None
        assert request.purple_agent_url == "http://example.com/a2a"
        assert request.purple_agent_id == "agent-123"

    def test_parse_assessment_request_with_config(self):
        message = A2AMessage(
            role="user",
            parts=[
                A2AMessagePart(
                    kind="text",
                    text='{"purple_agent_url": "http://example.com", "purple_agent_id": "agent-1", "config": {"num_tasks": 4}}',
                )
            ],
            messageId="msg-2",
        )
        request = parse_assessment_request(message)
        assert request is not None
        assert request.config.num_tasks == 4

    def test_parse_assessment_request_missing_url(self):
        message = A2AMessage(
            role="user",
            parts=[
                A2AMessagePart(
                    kind="text",
                    text='{"purple_agent_id": "agent-123"}',
                )
            ],
            messageId="msg-3",
        )
        assert parse_assessment_request(message) is None

    def test_parse_assessment_request_invalid_json(self):
        message = A2AMessage(
            role="user",
            parts=[
                A2AMessagePart(
                    kind="text",
                    text="not valid json",
                )
            ],
            messageId="msg-4",
        )
        assert parse_assessment_request(message) is None

    def test_parse_assessment_request_empty_parts(self):
        message = A2AMessage(
            role="user",
            parts=[],
            messageId="msg-5",
        )
        assert parse_assessment_request(message) is None


class TestResults:
    """Test results conversion to AgentBeats format."""

    def test_episode_to_task_result_compliant(self):
        episode = EpisodeResult(
            episode_id="ep-1",
            trace_hash="hash-1",
            policy=PolicyScore(
                verdict=PolicyVerdict.COMPLIANT,
                violations=(),
            ),
            task=TaskScore(success=True),
            validation=TraceValidation(valid=True, errors=()),
        )
        result = episode_to_task_result(episode, 0)
        assert result["score"] == 1.0
        assert result["verdict"] == "COMPLIANT"
        assert result["violations"] == []

    def test_episode_to_task_result_violation(self):
        from pi_bench.types import Violation, EvidencePointer

        episode = EpisodeResult(
            episode_id="ep-2",
            trace_hash="hash-2",
            policy=PolicyScore(
                verdict=PolicyVerdict.VIOLATION,
                violations=(
                    Violation(
                        rule_id="test-rule",
                        kind="forbid_substring",
                        evidence=(EvidencePointer(event_i=0, note="test"),),
                    ),
                ),
            ),
            task=TaskScore(success=False),
            validation=TraceValidation(valid=True, errors=()),
        )
        result = episode_to_task_result(episode, 1)
        assert result["score"] == 0.0
        assert result["verdict"] == "VIOLATION"
        assert result["violations"] == ["test-rule"]

    def test_episode_to_task_result_ambiguous(self):
        episode = EpisodeResult(
            episode_id="ep-3",
            trace_hash="hash-3",
            policy=PolicyScore(
                verdict=PolicyVerdict.AMBIGUOUS_POLICY,
                violations=(),
            ),
            task=TaskScore(success=True),
            validation=TraceValidation(valid=True, errors=()),
        )
        result = episode_to_task_result(episode, 2)
        assert result["score"] == 0.5
        assert result["verdict"] == "AMBIGUOUS_POLICY"

    def test_summary_to_metrics(self):
        summary = SummaryMetrics(
            compliance=0.8,
            understanding=0.9,
            robustness=0.85,
            process=0.9,
            restraint=0.95,
            conflict_resolution=0.9,
            detection=0.9,
            explainability=0.9,
            adaptation=0.9,
            overall=0.875,
            episode_count=100,
            safety=0.9,
            precision=0.95,
            diagnostics={"task_success_rate": 0.9},
        )
        metrics = summary_to_metrics(summary)
        assert metrics["safety"] == 0.9
        assert metrics["compliance"] == 0.8
        assert metrics["overall"] == 0.875
        assert metrics["episode_count"] == 100.0
        assert metrics["task_success_rate"] == 0.9
