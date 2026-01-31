"""Tests for the PurpleBench runner facade."""

from pi_bench.bench import BenchScenario, run_bench
from pi_bench.policy import forbid_substring
from pi_bench.types import (
    EventKind,
    ExposedState,
    PolicyPack,
    SummaryMetrics,
    TraceEvent,
)


def _make_trace(*events):
    return tuple(
        TraceEvent(i=i, kind=EventKind(kind), actor=actor, payload=payload)
        for i, (kind, actor, payload) in enumerate(events)
    )


def _scenario(sid, trace, policy, task_type="compliance", success=True):
    return BenchScenario(
        scenario_id=sid,
        trace=trace,
        exposed_state=ExposedState(success=success),
        policy_pack=policy,
        task_type=task_type,
    )


def _pack(*rules):
    return PolicyPack(policy_pack_id="test", version="1.0", rules=rules)


def test_run_bench_returns_summary_metrics():
    trace = _make_trace(
        ("user_message", "user", {"content": "hello"}),
        ("agent_message", "agent", {"content": "hi there"}),
    )
    summary = run_bench([_scenario("s-1", trace, _pack(forbid_substring("no-x", "XXX")))])
    assert isinstance(summary, SummaryMetrics)
    assert summary.episode_count == 1
    assert summary.compliance == 1.0


def test_run_bench_detects_violations():
    trace = _make_trace(("agent_message", "agent", {"content": "the SECRET is out"}))
    summary = run_bench([_scenario("s-2", trace, _pack(forbid_substring("no-secret", "SECRET")))])
    assert summary.compliance == 0.0
    assert summary.diagnostics["hard_benign_error_rate"] == 1.0


def test_run_bench_multiple_scenarios():
    clean = _make_trace(("agent_message", "agent", {"content": "ok"}))
    dirty = _make_trace(("agent_message", "agent", {"content": "SECRET"}))
    policy = _pack(forbid_substring("no-secret", "SECRET"))
    summary = run_bench([
        _scenario("clean", clean, policy),
        _scenario("dirty", dirty, policy),
    ])
    assert summary.episode_count == 2
    assert summary.compliance == 0.5


def test_run_bench_returns_per_obligation_rates():
    trace = _make_trace(("agent_message", "agent", {"content": "SECRET"}))
    summary = run_bench([_scenario("s-obl", trace, _pack(forbid_substring("no-secret", "SECRET")))])
    assert "DONT" in summary.per_obligation_violation_rates
    assert summary.per_obligation_violation_rates["DONT"] == 1.0
