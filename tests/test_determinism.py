"""
Determinism tests.

Verifies that identical inputs produce identical outputs.
This is the core guarantee from AGENT_SPEC §5.
"""

from pi_bench.policy import forbid_substring
from pi_bench.score import score_episode
from pi_bench.trace import canonical_trace_json_bytes, trace_hash
from pi_bench.types import (
    EpisodeBundle,
    EpisodeMetadata,
    EventKind,
    ExposedState,
    PolicyPack,
    TraceEvent,
)


def make_fixed_bundle() -> EpisodeBundle:
    """Create a fixed bundle for determinism testing."""
    trace = (
        TraceEvent(
            i=0,
            kind=EventKind.USER_MESSAGE,
            actor="user",
            payload={"content": "What is the policy?"},
        ),
        TraceEvent(
            i=1,
            kind=EventKind.AGENT_MESSAGE,
            actor="agent",
            payload={"content": "I cannot reveal that information."},
        ),
    )
    return EpisodeBundle(
        episode_id="determinism-test-001",
        trace=trace,
        exposed_state=ExposedState(success=True, end_reason="completed"),
        metadata=EpisodeMetadata(domain="test", seed=42),
    )


def make_fixed_policy() -> PolicyPack:
    """Create a fixed policy for determinism testing."""
    return PolicyPack(
        policy_pack_id="determinism-policy",
        version="1.0.0",
        rules=(forbid_substring("no-secrets", "SECRET"),),
    )


# === Determinism Tests ===


def test_trace_hash_is_deterministic():
    """Same trace produces same hash every time."""
    bundle = make_fixed_bundle()

    hash1 = trace_hash(bundle.trace)
    hash2 = trace_hash(bundle.trace)
    hash3 = trace_hash(bundle.trace)

    assert hash1 == hash2 == hash3
    assert len(hash1) == 16  # truncated sha256


def test_canonical_json_bytes_are_deterministic():
    """Same trace produces identical bytes every time."""
    bundle = make_fixed_bundle()

    bytes1 = canonical_trace_json_bytes(bundle.trace)
    bytes2 = canonical_trace_json_bytes(bundle.trace)

    assert bytes1 == bytes2


def test_score_episode_is_deterministic():
    """Same bundle + policy produces identical result every time."""
    bundle = make_fixed_bundle()
    policy = make_fixed_policy()

    result1 = score_episode(bundle, policy)
    result2 = score_episode(bundle, policy)

    # All fields must match
    assert result1.episode_id == result2.episode_id
    assert result1.trace_hash == result2.trace_hash
    assert result1.task == result2.task
    assert result1.policy == result2.policy
    assert result1.validation == result2.validation


def test_repeated_scoring_n_times():
    """Score same episode N times, all results identical."""
    bundle = make_fixed_bundle()
    policy = make_fixed_policy()
    n = 10

    results = [score_episode(bundle, policy) for _ in range(n)]

    # All must equal the first
    first = results[0]
    for r in results[1:]:
        assert r.trace_hash == first.trace_hash
        assert r.policy.verdict == first.policy.verdict


def test_trace_hash_changes_with_content():
    """Different content produces different hash."""
    trace1 = (
        TraceEvent(
            i=0, kind=EventKind.AGENT_MESSAGE, actor="agent", payload={"content": "A"}
        ),
    )
    trace2 = (
        TraceEvent(
            i=0, kind=EventKind.AGENT_MESSAGE, actor="agent", payload={"content": "B"}
        ),
    )

    assert trace_hash(trace1) != trace_hash(trace2)
