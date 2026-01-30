"""Tests for per-obligation-type metrics in SummaryMetrics."""

from policybeats.policy import forbid_substring, require_tool, require_prior_tool
from policybeats.score import aggregate, score_episode
from policybeats.types import (
    EpisodeBundle, EpisodeMetadata, EventKind, ExposedState,
    ObligationType, PolicyPack, PolicyVerdict, SummaryMetrics, TraceEvent,
)


def make_trace(*events):
    return tuple(
        TraceEvent(i=i, kind=EventKind(kind), actor=actor, payload=payload)
        for i, (kind, actor, payload) in enumerate(events)
    )

def make_bundle(episode_id, trace, success=True, task_type="compliance"):
    return EpisodeBundle(
        episode_id=episode_id, trace=trace,
        exposed_state=ExposedState(success=success),
        metadata=EpisodeMetadata(domain="test", task_type=task_type),
    )

def make_policy(*rules):
    return PolicyPack(policy_pack_id="test", version="1.0", rules=rules)


def test_summary_metrics_has_per_obligation_field():
    trace = make_trace(("agent_message", "agent", {"content": "ok"}))
    bundle = make_bundle("ep-1", trace)
    policy = make_policy(forbid_substring("no-x", "XXX"))
    result = score_episode(bundle, policy)
    summary = aggregate((result,))
    assert hasattr(summary, "per_obligation_violation_rates")
    assert isinstance(summary.per_obligation_violation_rates, dict)


def test_obligation_type_exists_on_rule_spec():
    rule = forbid_substring("no-x", "XXX")
    assert rule.obligation == ObligationType.DONT


def test_per_obligation_rates_computed_correctly():
    trace_bad = make_trace(("agent_message", "agent", {"content": "SECRET leaked"}))
    trace_good = make_trace(
        ("user_message", "user", {"content": "go"}),
        ("tool_call", "agent", {"tool": "verify", "arguments": {}}),
        ("tool_result", "tool", {"result": "ok"}),
        ("tool_call", "agent", {"tool": "access", "arguments": {}}),
        ("tool_result", "tool", {"result": "data"}),
    )
    r1 = score_episode(make_bundle("ep-1", trace_bad), make_policy(forbid_substring("no-secret", "SECRET")))
    r2 = score_episode(make_bundle("ep-2", trace_good), make_policy(require_prior_tool("verify-first", "verify", "access")))
    summary = aggregate((r1, r2))
    assert summary.per_obligation_violation_rates["DONT"] == 0.5  # 1 of 2 episodes
    assert summary.per_obligation_violation_rates["ORDER"] == 0.0
