"""
PolicyBeats type definitions.

All types are frozen dataclasses (immutable data only).
No behavior - keep functions in separate modules.

Invariants:
- All types are JSON-serializable (no lambdas, no callables stored)
- Trace is append-only, ordered by event index
- Evidence pointers reference trace events by index
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# === Enums ===


class EventKind(str, Enum):
    """Valid event kinds for TraceEvent."""

    USER_MESSAGE = "user_message"
    AGENT_MESSAGE = "agent_message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    STATE_CHANGE = "state_change"
    TERMINATION = "termination"


class PolicyVerdict(str, Enum):
    """Policy scoring outcomes."""

    COMPLIANT = "COMPLIANT"
    VIOLATION = "VIOLATION"
    AMBIGUOUS_POLICY = "AMBIGUOUS_POLICY"
    AMBIGUOUS_STATE = "AMBIGUOUS_STATE"
    AMBIGUOUS_CONFLICT = "AMBIGUOUS_CONFLICT"


class AmbiguityKind(str, Enum):
    """Ambiguity categories."""

    AMBIGUOUS_POLICY = "AMBIGUOUS_POLICY"
    AMBIGUOUS_STATE = "AMBIGUOUS_STATE"
    AMBIGUOUS_CONFLICT = "AMBIGUOUS_CONFLICT"


class RuleScope(str, Enum):
    """What evidence a rule can inspect."""

    TRACE = "trace"
    EXPOSED_STATE = "exposed_state"
    BOTH = "both"


class ObligationType(str, Enum):
    """Obligation types per policy clause."""
    DO = "DO"
    DONT = "DONT"
    ORDER = "ORDER"
    ACHIEVE = "ACHIEVE"


class ResolutionStrategy(str, Enum):
    """Policy resolution strategies."""

    DENY_OVERRIDES = "deny_overrides"


# === Trace Types ===


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """Single event in a trace. Immutable."""

    i: int  # 0-based contiguous index
    kind: EventKind
    actor: str  # user|adversary|agent|env|tool
    payload: dict[str, Any]
    # For tool_call/tool_result events only
    call_id: str | None = None


# Trace is a tuple (immutable sequence) of events
Trace = tuple[TraceEvent, ...]


@dataclass(frozen=True, slots=True)
class ValidationError:
    """Single validation error."""

    code: str  # stable error code
    message: str
    event_i: int | None = None  # which event caused it, if applicable


@dataclass(frozen=True, slots=True)
class TraceValidation:
    """Result of trace validation."""

    valid: bool
    errors: tuple[ValidationError, ...] = ()


# === Evidence Pointers ===


@dataclass(frozen=True, slots=True)
class EvidencePointer:
    """Points to evidence in the trace for a violation."""

    event_i: int  # required
    field_path: tuple[str | int, ...] | None = None  # e.g., ('payload', 'content')
    span: tuple[int, int] | None = None  # substring indices
    note: str | None = None  # short, non-interpretive


# === Policy Types ===


@dataclass(frozen=True, slots=True)
class RuleSpec:
    """
    Specification for a single policy clause encoding.

    PolicyBeats is POLICY-LITERAL: these are mechanical encodings of
    explicit policy clauses, not invented rules.

    Resolution metadata enables layered governance:
    - priority: higher priority rules are evaluated first
    - exception_of: this rule is a scoped exception to another rule
    - override_mode: how this rule interacts with others (deny/allow/require)
    """

    rule_id: str
    kind: str  # forbid_substring, require_tool, sequence, etc.
    params: dict[str, Any]
    scope: RuleScope = RuleScope.TRACE
    description: str | None = None  # documentation only, not executable
    obligation: ObligationType = ObligationType.DO

    # Resolution metadata (for layered governance)
    priority: int = 0  # higher = evaluated first, used for conflict resolution
    exception_of: str | None = None  # rule_id this is an exception to
    override_mode: str = "deny"  # "deny" | "allow" | "require"


@dataclass(frozen=True, slots=True)
class ResolutionSpec:
    """How to resolve multiple rule results."""

    strategy: ResolutionStrategy = ResolutionStrategy.DENY_OVERRIDES


@dataclass(frozen=True, slots=True)
class PolicyPack:
    """Operational policy definition."""

    policy_pack_id: str
    version: str
    rules: tuple[RuleSpec, ...]
    resolution: ResolutionSpec = field(default_factory=ResolutionSpec)


# === Episode Types ===


@dataclass(frozen=True, slots=True)
class ExposedState:
    """Environment state explicitly exposed for scoring."""

    success: bool
    end_reason: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EpisodeMetadata:
    """Episode metadata (must be deterministic)."""

    domain: str | None = None
    seed: int | None = None
    task_type: str = ""  # 9-column leaderboard task type
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EpisodeBundle:
    """All inputs for scoring a single episode."""

    episode_id: str
    trace: Trace
    exposed_state: ExposedState
    metadata: EpisodeMetadata = field(default_factory=EpisodeMetadata)


# === Scoring Output Types ===


@dataclass(frozen=True, slots=True)
class TaskScore:
    """Task success result."""

    success: bool
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Violation:
    """A single policy violation."""

    rule_id: str
    kind: str  # rule kind (e.g. "forbid_substring", "require_tool")
    evidence: tuple[EvidencePointer, ...]


@dataclass(frozen=True, slots=True)
class Ambiguity:
    """Ambiguity details when verdict is AMBIGUOUS_*."""

    kind: AmbiguityKind
    reason: str  # stable string token
    missing: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PolicyScore:
    """Policy compliance result."""

    verdict: PolicyVerdict
    violations: tuple[Violation, ...] = ()
    ambiguity: Ambiguity | None = None


@dataclass(frozen=True, slots=True)
class EpisodeResult:
    """Complete result for one episode."""

    episode_id: str
    trace_hash: str
    task: TaskScore
    policy: PolicyScore
    validation: TraceValidation
    metadata: EpisodeMetadata = field(default_factory=EpisodeMetadata)


# === Aggregate Types ===


@dataclass(frozen=True, slots=True)
class SummaryMetrics:
    """
    Aggregate metrics over all episodes.

    LEADERBOARD (9 task-type columns, MTEB-style):
    - compliance: Follow explicit policy rules (1 - violation_rate)
    - understanding: Correctly act on nuanced policies requiring interpretation
    - robustness: Maintain compliance under adversarial pressure
    - process: Follow required procedural ordering and escalation
    - restraint: Don't over-refuse permitted actions (1 - over_refusal_rate)
    - conflict_resolution: Recognize ambiguity, follow precedence
    - detection: Correctly judge whether traces violate policy
    - explainability: Justify policy decisions with correct reasoning
    - adaptation: Adapt behavior when conditions trigger new rules
    - overall: Mean of 9 columns

    DRILL-DOWN:
    - rule_violation_rates: per-rule breakdown {rule_id: rate}
    - diagnostics: ambiguity rates, trace stats, etc.

    LEGACY (4-dimension, kept for backward compatibility):
    - safety, precision mapped from rule kinds
    """

    # 9-column leaderboard (0-1, higher = better)
    compliance: float
    understanding: float
    robustness: float
    process: float
    restraint: float
    conflict_resolution: float
    detection: float
    explainability: float
    adaptation: float
    overall: float

    # Metadata
    episode_count: int

    # Legacy 4-dimension scores (computed from rule kinds)
    safety: float = 1.0
    precision: float = 1.0

    # Drill-down (optional, default empty)
    rule_violation_rates: dict[str, float] = field(default_factory=dict)
    per_obligation_violation_rates: dict[str, float] = field(default_factory=dict)
    diagnostics: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RunMetadata:
    """Metadata for the evaluation run (deterministic only)."""

    evaluator_version: str
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Artifact:
    """Final output artifact."""

    spec_version: str
    policy_pack_id: str
    policy_version: str
    run_metadata: RunMetadata
    summary: SummaryMetrics
    episodes: tuple[EpisodeResult, ...]
