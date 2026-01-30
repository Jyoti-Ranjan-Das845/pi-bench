"""
Simulation type definitions.

All types are frozen dataclasses (immutable data only).
No behavior - keep functions in separate modules.

Invariants:
- All types are JSON-serializable
- SimState is the complete simulation state (fully reconstructible)
- Effects describe side effects to execute in the shell
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


# === Enums ===


class MessageKind(str, Enum):
    """Valid message kinds in simulation."""

    USER = "user"
    AGENT = "agent"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    SYSTEM = "system"


class EffectKind(str, Enum):
    """Effect types to execute in imperative shell."""

    LLM_CALL = "llm_call"
    TOOL_EXEC = "tool_exec"
    DONE = "done"


class TerminationReason(str, Enum):
    """Reasons simulation can terminate."""

    SUCCESS = "success"
    MAX_STEPS = "max_steps"
    MAX_ERRORS = "max_errors"
    AGENT_DONE = "agent_done"
    USER_DONE = "user_done"
    ERROR = "error"


# === Tool Call Data ===


@dataclass(frozen=True, slots=True)
class ToolCallData:
    """Single tool call from agent."""

    call_id: str
    name: str
    arguments: dict[str, Any]


# === Messages ===


@dataclass(frozen=True, slots=True)
class SimMessage:
    """Single message in simulation. Immutable."""

    kind: MessageKind
    content: str | None = None
    tool_calls: tuple[ToolCallData, ...] = ()
    call_id: str | None = None  # for tool results, references the tool call
    error: bool = False
    # metadata (optional, for tracing)
    model: str | None = None


# === Database State ===


@dataclass(frozen=True, slots=True)
class DBSnapshot:
    """Immutable database state."""

    data: dict[str, Any] = field(default_factory=dict)
    version: int = 0

    def with_data(self, new_data: dict[str, Any]) -> DBSnapshot:
        """Return new snapshot with updated data."""
        return DBSnapshot(data=new_data, version=self.version + 1)


# === Task Configuration ===


@dataclass(frozen=True, slots=True)
class UserInstruction:
    """User's goal/instruction for the task."""

    goal: str
    context: str | None = None
    constraints: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TaskConfig:
    """Task configuration for simulation."""

    task_id: str
    domain: str
    system_prompt: str
    user_instruction: UserInstruction
    initial_db: dict[str, Any] = field(default_factory=dict)
    available_tools: tuple[str, ...] = ()
    max_steps: int = 50
    max_errors: int = 3
    seed: int | None = None
    # Additional config
    extra: dict[str, Any] = field(default_factory=dict)


# === Simulation State ===


@dataclass(frozen=True, slots=True)
class SimState:
    """Complete simulation state. Immutable."""

    # Core state
    trajectory: tuple[SimMessage, ...] = ()
    db: DBSnapshot = field(default_factory=DBSnapshot)

    # Counters
    step_count: int = 0
    error_count: int = 0

    # Termination
    done: bool = False
    termination_reason: TerminationReason | None = None

    # Task reference (for context)
    task_id: str | None = None
    domain: str | None = None

    def with_message(self, msg: SimMessage) -> SimState:
        """Return new state with message appended."""
        return SimState(
            trajectory=self.trajectory + (msg,),
            db=self.db,
            step_count=self.step_count,
            error_count=self.error_count,
            done=self.done,
            termination_reason=self.termination_reason,
            task_id=self.task_id,
            domain=self.domain,
        )

    def with_db(self, new_db: DBSnapshot) -> SimState:
        """Return new state with updated db."""
        return SimState(
            trajectory=self.trajectory,
            db=new_db,
            step_count=self.step_count,
            error_count=self.error_count,
            done=self.done,
            termination_reason=self.termination_reason,
            task_id=self.task_id,
            domain=self.domain,
        )

    def with_step(self) -> SimState:
        """Return new state with incremented step count."""
        return SimState(
            trajectory=self.trajectory,
            db=self.db,
            step_count=self.step_count + 1,
            error_count=self.error_count,
            done=self.done,
            termination_reason=self.termination_reason,
            task_id=self.task_id,
            domain=self.domain,
        )

    def with_error(self) -> SimState:
        """Return new state with incremented error count."""
        return SimState(
            trajectory=self.trajectory,
            db=self.db,
            step_count=self.step_count,
            error_count=self.error_count + 1,
            done=self.done,
            termination_reason=self.termination_reason,
            task_id=self.task_id,
            domain=self.domain,
        )

    def terminated(self, reason: TerminationReason) -> SimState:
        """Return new state marked as done."""
        return SimState(
            trajectory=self.trajectory,
            db=self.db,
            step_count=self.step_count,
            error_count=self.error_count,
            done=True,
            termination_reason=reason,
            task_id=self.task_id,
            domain=self.domain,
        )


# === Effects ===


@dataclass(frozen=True, slots=True)
class LLMCallEffect:
    """Effect: call LLM for agent or user response."""

    role: Literal["agent", "user"]
    messages: tuple[SimMessage, ...]
    system_prompt: str | None = None
    tools: tuple[dict[str, Any], ...] | None = None  # tool schemas for agent


@dataclass(frozen=True, slots=True)
class ToolExecEffect:
    """Effect: execute a tool call."""

    call_id: str
    tool_name: str
    arguments: dict[str, Any]
    db: DBSnapshot  # current db state for tool execution


@dataclass(frozen=True, slots=True)
class DoneEffect:
    """Effect: simulation is complete."""

    reason: TerminationReason


# Union of all effects
SimEffect = LLMCallEffect | ToolExecEffect | DoneEffect


# === Step Result ===


@dataclass(frozen=True, slots=True)
class StepResult:
    """Pure step output: new state + effects to execute."""

    state: SimState
    effects: tuple[SimEffect, ...]


# === Simulation Result ===


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """Final result of a simulation run."""

    task_id: str
    domain: str
    trajectory: tuple[SimMessage, ...]
    final_db: DBSnapshot
    step_count: int
    termination_reason: TerminationReason
    # Computed fields
    success: bool
    error: str | None = None


# === Task Specification Types (τ²-bench compatible) ===


@dataclass(frozen=True, slots=True)
class UserScenarioInstructions:
    """
    Detailed instructions for user simulator (Green agent).

    This mirrors τ²-bench's user_scenario.instructions format,
    supporting conditional behavior and adversarial testing.
    """

    # What the user wants to accomplish (may include conditional steps)
    task_instructions: str | None = None
    # Domain context (airline, retail, mock, etc.)
    domain: str | None = None
    # Why the user is calling
    reason_for_call: str | None = None
    # Facts the user knows (identity, reservation numbers, etc.)
    known_info: str | None = None
    # Facts the user doesn't know (tests that agent provides)
    unknown_info: str | None = None


@dataclass(frozen=True, slots=True)
class UserScenario:
    """
    Complete user scenario for simulation.

    Combines persona and conditional instructions for the user simulator.
    """

    # User's personality/communication style
    persona: str | None = None
    # Detailed instructions (can be string or structured)
    instructions: str | UserScenarioInstructions | None = None


@dataclass(frozen=True, slots=True)
class ExpectedAction:
    """
    An action the agent is expected to perform.

    Used to verify that the agent called required tools with correct arguments.
    """

    # Unique identifier for this expected action
    action_id: str
    # Tool/function name
    name: str
    # Expected arguments (subset matching - agent may provide more)
    arguments: dict[str, Any] = field(default_factory=dict)
    # Arguments to skip when comparing (e.g., flexible parameters)
    compare_args: tuple[str, ...] | None = None
    # Human-readable description
    info: str | None = None


@dataclass(frozen=True, slots=True)
class EnvAssertion:
    """
    An environment/database assertion to check.

    Used to verify final state of the environment.
    """

    # Environment type (assistant, user, etc.)
    env_type: str
    # Function to call for assertion
    func_name: str
    # Arguments for the assertion function
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvaluationCriteria:
    """
    Criteria for evaluating agent performance on a task.

    Supports action matching, NL assertions, and environment assertions.
    """

    # Expected tool calls (order may or may not matter)
    actions: tuple[ExpectedAction, ...] = ()
    # Natural language assertions to check with LLM judge
    nl_assertions: tuple[str, ...] = ()
    # Environment state assertions
    env_assertions: tuple[EnvAssertion, ...] = ()
    # Information agent should communicate to user
    communicate_info: tuple[str, ...] = ()
    # What to base reward on: DB, ACTION, ENV_ASSERTION, NL_ASSERTION
    reward_basis: tuple[str, ...] = ("ACTION", "NL_ASSERTION")


@dataclass(frozen=True, slots=True)
class InitialState:
    """
    Initial state for a task, including message history and DB setup.
    """

    # Pre-existing message history
    message_history: tuple[dict[str, Any], ...] = ()
    # Data to initialize in the DB
    initialization_data: dict[str, Any] = field(default_factory=dict)
    # Actions to run before the task starts
    initialization_actions: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class TaskDescription:
    """
    Description and metadata for a task.
    """

    purpose: str
    notes: str | None = None
    relevant_policies: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """
    Complete task specification for simulation (τ²-bench compatible).

    This is the rich task format that includes:
    - User scenario with conditional instructions
    - Evaluation criteria with expected actions and assertions
    - Initial state setup
    """

    # Unique task identifier
    id: str
    # Task description and metadata
    description: TaskDescription | None = None
    # User scenario (persona + instructions)
    user_scenario: UserScenario | None = None
    # Simple ticket/summary (alternative to full user_scenario)
    ticket: str | None = None
    # Initial state (message history, DB, pre-actions)
    initial_state: InitialState | None = None
    # How to evaluate agent performance
    evaluation_criteria: EvaluationCriteria | None = None
    # Domain (for loading domain-specific tools/policies)
    domain: str = "mock"
    # Annotations (for analysis)
    annotations: dict[str, Any] | None = None


# === Conversion helpers ===


def taskspec_to_taskconfig(
    spec: TaskSpec,
    system_prompt: str,
    initial_db: dict[str, Any] | None = None,
    available_tools: tuple[str, ...] = (),
    max_steps: int = 50,
    max_errors: int = 3,
) -> TaskConfig:
    """
    Convert TaskSpec to TaskConfig for simulation.

    TaskSpec is the rich task format (τ²-bench compatible).
    TaskConfig is the simpler format used by the simulation engine.
    """
    # Extract user instruction from scenario
    goal = ""
    context = None
    constraints: tuple[str, ...] = ()

    if spec.ticket:
        goal = spec.ticket
    elif spec.user_scenario and spec.user_scenario.instructions:
        instr = spec.user_scenario.instructions
        if isinstance(instr, str):
            goal = instr
        else:
            # Build goal from structured instructions
            parts = []
            if instr.reason_for_call:
                parts.append(instr.reason_for_call)
            if instr.task_instructions:
                parts.append(instr.task_instructions)
            goal = "\n\n".join(parts) if parts else "Complete the task."
            context = instr.known_info

    # Get initial DB from initial_state
    db = initial_db or {}
    if spec.initial_state and spec.initial_state.initialization_data:
        db = {**db, **spec.initial_state.initialization_data}

    return TaskConfig(
        task_id=spec.id,
        domain=spec.domain,
        system_prompt=system_prompt,
        user_instruction=UserInstruction(
            goal=goal,
            context=context,
            constraints=constraints,
        ),
        initial_db=db,
        available_tools=available_tools,
        max_steps=max_steps,
        max_errors=max_errors,
        extra={"task_spec": spec},  # Keep original spec for evaluation
    )
