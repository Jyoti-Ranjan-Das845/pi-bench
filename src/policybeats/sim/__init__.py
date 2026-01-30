"""
Simulation engine - functional core.

Provides pure functions for agent-user simulation.
Side effects are returned as data (effects) to be executed by the shell.
"""

from policybeats.sim.types import (
    DBSnapshot,
    DoneEffect,
    EffectKind,
    LLMCallEffect,
    MessageKind,
    SimEffect,
    SimMessage,
    SimState,
    SimulationResult,
    StepResult,
    TaskConfig,
    TerminationReason,
    ToolCallData,
    ToolExecEffect,
    UserInstruction,
)

from policybeats.sim.orchestration import (
    init_simulation,
    integrate_tool_result,
    step,
    to_episode_trace,
)

from policybeats.sim.tools import (
    ToolFn,
    crud_create,
    crud_delete,
    crud_list,
    crud_read,
    crud_update,
    execute_tool,
    read_tool,
    tool_schema,
    write_tool,
)

from policybeats.sim.user import (
    UserResponseAnalysis,
    UserState,
    analyze_user_response,
    build_user_prompt_from_trajectory,
    build_user_system_prompt,
    create_instruction,
    init_user_state,
    update_user_state,
)

from policybeats.sim.evaluation import (
    SimEvaluation,
    compute_reward,
    compute_step_reward,
    count_errors,
    count_tool_calls,
    evaluate_simulation,
    evaluate_success,
    verify_db_contains,
    verify_db_state,
)

__all__ = [
    # Types
    "DBSnapshot",
    "DoneEffect",
    "EffectKind",
    "LLMCallEffect",
    "MessageKind",
    "SimEffect",
    "SimEvaluation",
    "SimMessage",
    "SimState",
    "SimulationResult",
    "StepResult",
    "TaskConfig",
    "TerminationReason",
    "ToolCallData",
    "ToolExecEffect",
    "ToolFn",
    "UserInstruction",
    "UserResponseAnalysis",
    "UserState",
    # Orchestration
    "init_simulation",
    "integrate_tool_result",
    "step",
    "to_episode_trace",
    # Tools
    "crud_create",
    "crud_delete",
    "crud_list",
    "crud_read",
    "crud_update",
    "execute_tool",
    "read_tool",
    "tool_schema",
    "write_tool",
    # User
    "analyze_user_response",
    "build_user_prompt_from_trajectory",
    "build_user_system_prompt",
    "create_instruction",
    "init_user_state",
    "update_user_state",
    # Evaluation
    "compute_reward",
    "compute_step_reward",
    "count_errors",
    "count_tool_calls",
    "evaluate_simulation",
    "evaluate_success",
    "verify_db_contains",
    "verify_db_state",
]
