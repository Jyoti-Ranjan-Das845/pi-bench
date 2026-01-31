"""
A2A Protocol Types for PolicyBeats.

Simplified for GDPR-only assessment. Policy type is config-based
via scenario.toml, not discovered dynamically via Skills.

Types:
- Environment: Mutable state Purple can read/modify
- Scenario: Multi-turn test definition
- Evaluation: Turn-level and overall scoring
- A2A Messages: Green ↔ Purple communication
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar


# === Environment State ===


@dataclass
class Environment:
    """
    Mutable environment state for a scenario.

    Purple agent can read this state and request updates.
    Green agent validates updates and tracks changes.
    """
    # User context
    user_id: str = ""
    user_region: str = ""  # "EU", "US", etc.

    # Consent tracking
    consent_status: str | None = None  # None, "requested", "granted", "denied"
    consent_scope: list[str] = field(default_factory=list)

    # Data access tracking
    data_accessed: list[str] = field(default_factory=list)
    data_modified: list[str] = field(default_factory=list)
    data_deleted: list[str] = field(default_factory=list)

    # Session state
    session_disclosed_ai: bool = False
    session_escalated: bool = False
    session_secure_channel: bool = False

    # Custom fields
    extra: dict[str, Any] = field(default_factory=dict)

    # In-memory database: table_name -> {record_id -> record_dict}
    database: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for A2A transport.

        Extra fields are flattened into the top level so that
        state-based rule checkers (require_consent_flag, require_role,
        require_escalation_on) can find them via state.data[key].
        """
        d: dict[str, Any] = {
            "user_id": self.user_id,
            "user_region": self.user_region,
            "consent_status": self.consent_status,
            "consent_scope": self.consent_scope,
            "data_accessed": self.data_accessed,
            "data_modified": self.data_modified,
            "data_deleted": self.data_deleted,
            "session_disclosed_ai": self.session_disclosed_ai,
            "session_escalated": self.session_escalated,
            "session_secure_channel": self.session_secure_channel,
            "database": self.database,
        }
        # Flatten extra fields so rule checkers find them at top level
        d.update(self.extra)
        return d

    # Known typed field names (used by from_dict to route extras)
    _TYPED_FIELDS: ClassVar[frozenset[str]] = frozenset({
        "user_id", "user_region", "consent_status", "consent_scope",
        "data_accessed", "data_modified", "data_deleted",
        "session_disclosed_ai", "session_escalated", "session_secure_channel",
        "extra", "database",
    })

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Environment:
        """Create from dictionary, routing unknown keys to extra."""
        # Collect unknown keys into extra (merged with explicit extra)
        extra = dict(data.get("extra", {}))
        for key, value in data.items():
            if key not in cls._TYPED_FIELDS:
                extra[key] = value

        # Convert consent_scope from string to list if needed
        consent_scope_raw = data.get("consent_scope", [])
        if isinstance(consent_scope_raw, str):
            consent_scope = [consent_scope_raw]
        else:
            consent_scope = consent_scope_raw if consent_scope_raw else []

        return cls(
            user_id=data.get("user_id", ""),
            user_region=data.get("user_region", ""),
            consent_status=data.get("consent_status"),
            consent_scope=consent_scope,
            data_accessed=data.get("data_accessed", []),
            data_modified=data.get("data_modified", []),
            data_deleted=data.get("data_deleted", []),
            session_disclosed_ai=data.get("session_disclosed_ai", False),
            session_escalated=data.get("session_escalated", False),
            session_secure_channel=data.get("session_secure_channel", False),
            extra=extra,
            database=data.get("database", {}),
        )

    def apply_updates(self, updates: dict[str, Any]) -> list[str]:
        """Apply updates from Purple agent response."""
        updated_fields = []
        for key, value in updates.items():
            if hasattr(self, key):
                setattr(self, key, value)
                updated_fields.append(key)
            elif key not in ("extra",):
                self.extra[key] = value
                updated_fields.append(f"extra.{key}")
        return updated_fields


# === Scenario Definition ===


@dataclass(frozen=True)
class ScenarioTurn:
    """A single turn in a multi-turn scenario."""
    turn_number: int
    instruction: str

    # What to check after this turn
    expected_env_changes: tuple[str, ...] = ()
    rules_to_check: tuple[str, ...] = ()

    # Tool constraints
    required_tool_calls: tuple[str, ...] = ()
    forbidden_tool_calls: tuple[str, ...] = ()


@dataclass(frozen=True)
class MultiTurnScenario:
    """A multi-turn test scenario."""
    scenario_id: str
    name: str
    description: str

    # Initial state
    initial_environment: dict[str, Any]

    # Available tools (exposed via MCP)
    tools: tuple[str, ...]

    # Turn definitions
    turns: tuple[ScenarioTurn, ...]

    # Rules to evaluate
    rules_to_check: tuple[str, ...]

    # Metadata
    category: str = ""  # "transparency", "consent", "data-rights", etc.
    severity: str = "medium"  # "low", "medium", "high", "critical"
    task_type: str = ""  # 9-column leaderboard: compliance, understanding, robustness, process, restraint, conflict_resolution, detection, explainability, adaptation

    # Dynamic user simulation (§5.2): when True, an LLM-driven user sim
    # generates contextual messages instead of using static instructions.
    # Falls back to static instructions when no LLM is available.
    dynamic_user: bool = False


# === Evaluation Types ===


@dataclass
class RuleCheck:
    """Result of checking a single rule."""
    rule_id: str
    passed: bool
    evidence: str = ""
    turn_number: int = 0


@dataclass
class TurnEvaluation:
    """Evaluation result for a single turn."""
    turn_number: int
    rules_checked: list[RuleCheck] = field(default_factory=list)
    rules_passed: int = 0
    rules_failed: int = 0
    env_changes: list[str] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)

    @property
    def compliance_rate(self) -> float:
        total = self.rules_passed + self.rules_failed
        return self.rules_passed / total if total > 0 else 1.0


@dataclass
class ViolationRecord:
    """Record of a policy violation."""
    rule_id: str
    scenario_id: str
    turn_number: int
    severity: str
    evidence: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "scenario_id": self.scenario_id,
            "turn_number": self.turn_number,
            "severity": self.severity,
            "evidence": self.evidence,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class RunMetrics:
    """Counters for calls made during an assessment run."""
    a2a_calls: int = 0          # HTTP POST to purple agent (turn sends + tool-result sends)
    tool_executions: int = 0    # Green-side dummy tool executions
    user_driver_llm_calls: int = 0  # Dynamic user simulator LLM calls
    purple_llm_calls: int = 0   # Inferred: 1 per a2a_call (purple calls its LLM each time)

    def to_dict(self) -> dict[str, int]:
        return {
            "a2a_calls": self.a2a_calls,
            "tool_executions": self.tool_executions,
            "user_driver_llm_calls": self.user_driver_llm_calls,
            "purple_llm_calls": self.purple_llm_calls,
        }


@dataclass
class AssessmentReport:
    """Final assessment report."""
    # Metadata
    policy_type: str = "gdpr"  # Config-based, not discovered
    target_agent: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Scores
    overall_score: float = 0.0
    scores_by_rule: dict[str, float] = field(default_factory=dict)
    scores_by_category: dict[str, float] = field(default_factory=dict)
    scores_by_task_type: dict[str, float] = field(default_factory=dict)

    # Metrics
    total_scenarios: int = 0
    total_turns: int = 0
    total_rule_checks: int = 0
    total_violations: int = 0

    # Run metrics (call counts)
    run_metrics: RunMetrics = field(default_factory=RunMetrics)

    # Details
    violations: list[ViolationRecord] = field(default_factory=list)
    scenario_results: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON/leaderboard."""
        return {
            "policy_type": self.policy_type,
            "target_agent": self.target_agent,
            "timestamp": self.timestamp.isoformat(),
            "scores": {
                "overall": self.overall_score,
                "by_rule": self.scores_by_rule,
                "by_category": self.scores_by_category,
            },
            "metrics": {
                "total_scenarios": self.total_scenarios,
                "total_turns": self.total_turns,
                "total_rule_checks": self.total_rule_checks,
                "total_violations": self.total_violations,
                "compliance_rate": 1.0 - (self.total_violations / self.total_rule_checks)
                    if self.total_rule_checks > 0 else 1.0,
            },
            "run_metrics": self.run_metrics.to_dict(),
            "violations": [v.to_dict() for v in self.violations],
            "scenario_results": self.scenario_results,
        }


# === A2A Message Types ===


@dataclass
class ScenarioMessage:
    """Message sent to Purple agent for a scenario turn."""
    scenario_id: str
    turn_number: int
    instruction: str
    environment: dict[str, Any]
    tools: list[dict[str, Any]]
    max_turns: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "turn_number": self.turn_number,
            "instruction": self.instruction,
            "environment": self.environment,
            "tools": self.tools,
            "max_turns": self.max_turns,
        }


@dataclass
class PurpleResponse:
    """Response from Purple agent."""
    response_text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    env_updates: dict[str, Any] = field(default_factory=dict)
    done: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PurpleResponse:
        return cls(
            response_text=data.get("response", "") or data.get("response_text", ""),
            tool_calls=data.get("tool_calls", []),
            env_updates=data.get("env_updates", {}),
            done=data.get("done", False),
        )
