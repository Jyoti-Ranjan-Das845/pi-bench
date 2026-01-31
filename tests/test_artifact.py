"""
Tests for artifact creation and serialization.

Verifies that artifact creation is deterministic and produces valid JSON.
"""

from pi_bench.artifact import artifact_to_json, canonical_json_bytes, make_artifact
from pi_bench.policy import forbid_substring
from pi_bench.score import score_episode
from pi_bench.types import (
    EpisodeBundle,
    EpisodeMetadata,
    EventKind,
    ExposedState,
    PolicyPack,
    TraceEvent,
)


def make_test_bundle(episode_id: str, content: str, success: bool = True) -> EpisodeBundle:
    """Helper to create test episode bundles."""
    trace = (
        TraceEvent(
            i=0, kind=EventKind.AGENT_MESSAGE, actor="agent", payload={"content": content}
        ),
    )
    return EpisodeBundle(
        episode_id=episode_id,
        trace=trace,
        exposed_state=ExposedState(success=success),
        metadata=EpisodeMetadata(domain="test"),
    )


def test_canonical_json_bytes_is_deterministic():
    """Same object produces identical bytes every time."""
    obj = {"b": 2, "a": 1, "nested": {"z": 26, "a": 1}}

    bytes1 = canonical_json_bytes(obj)
    bytes2 = canonical_json_bytes(obj)

    assert bytes1 == bytes2
    # Keys should be sorted
    assert b'"a":1' in bytes1
    assert bytes1.index(b'"a"') < bytes1.index(b'"b"')


def test_make_artifact_creates_valid_artifact():
    """make_artifact produces a complete artifact with correct fields."""
    policy = PolicyPack(
        policy_pack_id="test-policy",
        version="1.0",
        rules=(forbid_substring("no-leak", "LEAK"),),
    )

    bundles = [
        make_test_bundle("ep-1", "safe content", success=True),
        make_test_bundle("ep-2", "LEAK detected", success=True),
    ]

    results = tuple(score_episode(b, policy) for b in bundles)
    artifact = make_artifact(results, policy)

    assert artifact.spec_version == "1.0"
    assert artifact.policy_pack_id == "test-policy"
    assert artifact.policy_version == "1.0"
    assert artifact.summary.episode_count == 2
    assert len(artifact.episodes) == 2


def test_artifact_serialization_is_deterministic():
    """Same artifact produces identical JSON every time."""
    policy = PolicyPack(
        policy_pack_id="determinism-test",
        version="1.0",
        rules=(),
    )

    bundle = make_test_bundle("ep-det", "hello")
    result = score_episode(bundle, policy)
    artifact = make_artifact((result,), policy)

    json1 = artifact_to_json(artifact)
    json2 = artifact_to_json(artifact)

    assert json1 == json2


def test_artifact_episodes_sorted_by_id():
    """Artifact episodes are sorted by episode_id for determinism."""
    policy = PolicyPack(
        policy_pack_id="sort-test",
        version="1.0",
        rules=(),
    )

    # Create bundles out of order
    bundles = [
        make_test_bundle("ep-c", "c"),
        make_test_bundle("ep-a", "a"),
        make_test_bundle("ep-b", "b"),
    ]

    results = tuple(score_episode(b, policy) for b in bundles)
    artifact = make_artifact(results, policy)

    # Episodes should be sorted by id
    episode_ids = [ep.episode_id for ep in artifact.episodes]
    assert episode_ids == ["ep-a", "ep-b", "ep-c"]
