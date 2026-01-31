"""
Pure orchestration functions for simulation.

All functions are pure: step(state, response) -> StepResult(state, effects).
No side effects - I/O happens in the imperative shell.

The simulation flow:
1. init_simulation(task) -> initial state + effects to get first user message
2. step(state, response) -> new state + next effects
3. Repeat until done
"""

from __future__ import annotations

from pi_bench.sim.types import (
    DBSnapshot,
    DoneEffect,
    LLMCallEffect,
    MessageKind,
    SimMessage,
    SimState,
    StepResult,
    TaskConfig,
    TerminationReason,
    ToolCallData,
    ToolExecEffect,
)


# === Initialization ===


def init_simulation(task: TaskConfig) -> StepResult:
    """
    Initialize simulation state from task. Pure.

    Returns initial state and effect to get first user message.
    """
    initial_db = DBSnapshot(data=task.initial_db, version=0)

    state = SimState(
        trajectory=(),
        db=initial_db,
        step_count=0,
        error_count=0,
        done=False,
        termination_reason=None,
        task_id=task.task_id,
        domain=task.domain,
    )

    # First effect: generate initial user message
    # User simulator needs the instruction
    user_effect = LLMCallEffect(
        role="user",
        messages=(),  # No prior messages for first turn
        system_prompt=_user_system_prompt(task),
        tools=None,
    )

    return StepResult(state=state, effects=(user_effect,))


def _user_system_prompt(task: TaskConfig) -> str:
    """Build user simulator system prompt. Pure."""
    constraints_str = ""
    if task.user_instruction.constraints:
        constraints_str = "\n\nConstraints:\n" + "\n".join(
            f"- {c}" for c in task.user_instruction.constraints
        )

    context_str = ""
    if task.user_instruction.context:
        context_str = f"\n\nContext: {task.user_instruction.context}"

    return f"""You are simulating a user interacting with an AI assistant.

Your goal: {task.user_instruction.goal}{context_str}{constraints_str}

Guidelines:
- Stay in character as the user
- Be concise and natural
- If the assistant completes your goal, say "TASK_COMPLETE" to end
- If something goes wrong or you can't proceed, say "TASK_FAILED" to end
- Do not reveal you are a simulation"""


# === Main Step Function ===


def step(state: SimState, response: SimMessage | None) -> StepResult:
    """
    Pure step function.

    Given current state and optional response (from previous effect),
    returns new state and next effects.

    Flow:
    1. Integrate response into state
    2. Check termination conditions
    3. Determine next action (route to agent, user, or tools)
    4. Return new state + effects
    """
    if state.done:
        return StepResult(state=state, effects=())

    # Integrate response if provided
    if response is not None:
        state = _integrate_response(state, response)

    # Check termination
    term_result = _check_termination(state)
    if term_result is not None:
        return term_result

    # Route to next action
    return _route_next(state)


# === Response Integration ===


def _integrate_response(state: SimState, response: SimMessage) -> SimState:
    """Add response to trajectory. Pure."""
    return state.with_message(response).with_step()


# === Termination Checking ===


def _check_termination(state: SimState) -> StepResult | None:
    """
    Check if simulation should terminate. Pure.

    Returns StepResult with done state if terminated, else None.
    """
    # Check max steps
    if state.step_count >= 50:  # Default, could parameterize via state
        done_state = state.terminated(TerminationReason.MAX_STEPS)
        return StepResult(
            state=done_state,
            effects=(DoneEffect(reason=TerminationReason.MAX_STEPS),),
        )

    # Check max errors
    if state.error_count >= 3:  # Default
        done_state = state.terminated(TerminationReason.MAX_ERRORS)
        return StepResult(
            state=done_state,
            effects=(DoneEffect(reason=TerminationReason.MAX_ERRORS),),
        )

    # Check for completion markers in last message
    if state.trajectory:
        last_msg = state.trajectory[-1]
        if last_msg.kind == MessageKind.USER and last_msg.content:
            content_upper = last_msg.content.upper()
            if "TASK_COMPLETE" in content_upper:
                done_state = state.terminated(TerminationReason.SUCCESS)
                return StepResult(
                    state=done_state,
                    effects=(DoneEffect(reason=TerminationReason.SUCCESS),),
                )
            if "TASK_FAILED" in content_upper:
                done_state = state.terminated(TerminationReason.USER_DONE)
                return StepResult(
                    state=done_state,
                    effects=(DoneEffect(reason=TerminationReason.USER_DONE),),
                )

    return None


# === Routing ===


def _route_next(state: SimState) -> StepResult:
    """
    Determine next action based on current state. Pure.

    Routing logic:
    - No messages yet or last is tool_result after agent tools -> agent turn
    - Last message is user -> agent turn
    - Last message is agent with tool_calls -> execute tools
    - Last message is agent without tool_calls -> user turn
    """
    if not state.trajectory:
        # No messages - this shouldn't happen after init, but handle it
        # The init_simulation already returns an effect for first user message
        return StepResult(state=state, effects=())

    last_msg = state.trajectory[-1]

    # After user message -> agent responds
    if last_msg.kind == MessageKind.USER:
        return _create_agent_turn(state)

    # After agent message with tool calls -> execute tools
    if last_msg.kind == MessageKind.AGENT and last_msg.tool_calls:
        return _create_tool_executions(state, last_msg.tool_calls)

    # After agent message without tool calls -> user responds
    if last_msg.kind == MessageKind.AGENT:
        return _create_user_turn(state)

    # After tool result -> check if more tools pending, else agent continues
    if last_msg.kind == MessageKind.TOOL_RESULT:
        # Find the last agent message with tool calls
        pending_tools = _find_pending_tools(state)
        if pending_tools:
            return _create_tool_executions(state, pending_tools)
        # All tools done, agent continues
        return _create_agent_turn(state)

    # Fallback: agent turn
    return _create_agent_turn(state)


def _find_pending_tools(state: SimState) -> tuple[ToolCallData, ...]:
    """
    Find tool calls that haven't been executed yet. Pure.

    Looks backwards from end of trajectory to find agent message with tool_calls,
    then checks which call_ids have results.
    """
    # Find last agent message with tool calls
    last_agent_tools: tuple[ToolCallData, ...] = ()
    for msg in reversed(state.trajectory):
        if msg.kind == MessageKind.AGENT and msg.tool_calls:
            last_agent_tools = msg.tool_calls
            break
        # If we hit a user message before finding agent tools, no pending
        if msg.kind == MessageKind.USER:
            break

    if not last_agent_tools:
        return ()

    # Find which have results
    executed_ids = set()
    for msg in state.trajectory:
        if msg.kind == MessageKind.TOOL_RESULT and msg.call_id:
            executed_ids.add(msg.call_id)

    pending = tuple(tc for tc in last_agent_tools if tc.call_id not in executed_ids)
    return pending


# === Turn Creation ===


def _create_agent_turn(state: SimState) -> StepResult:
    """Create effect for agent to respond. Pure."""
    effect = LLMCallEffect(
        role="agent",
        messages=state.trajectory,
        system_prompt=None,  # Set by adapter from task config
        tools=None,  # Set by adapter from tool registry
    )
    return StepResult(state=state, effects=(effect,))


def _create_user_turn(state: SimState) -> StepResult:
    """Create effect for user to respond. Pure."""
    effect = LLMCallEffect(
        role="user",
        messages=state.trajectory,
        system_prompt=None,  # Set by adapter
        tools=None,
    )
    return StepResult(state=state, effects=(effect,))


def _create_tool_executions(
    state: SimState, tool_calls: tuple[ToolCallData, ...]
) -> StepResult:
    """Create effects for tool execution. Pure."""
    if not tool_calls:
        return StepResult(state=state, effects=())

    # Execute first pending tool (sequential for determinism)
    tc = tool_calls[0]
    effect = ToolExecEffect(
        call_id=tc.call_id,
        tool_name=tc.name,
        arguments=tc.arguments,
        db=state.db,
    )
    return StepResult(state=state, effects=(effect,))


# === Tool Result Integration ===


def integrate_tool_result(
    state: SimState,
    call_id: str,
    result: str,
    new_db: DBSnapshot,
    is_error: bool = False,
) -> SimState:
    """
    Integrate tool execution result into state. Pure.

    Used by the runner after executing a tool effect.
    """
    tool_result_msg = SimMessage(
        kind=MessageKind.TOOL_RESULT,
        content=result,
        call_id=call_id,
        error=is_error,
    )

    new_state = state.with_message(tool_result_msg).with_db(new_db)

    if is_error:
        new_state = new_state.with_error()

    return new_state


# === Conversion to Scorer Types ===


def to_episode_trace(state: SimState) -> list[dict]:
    """
    Convert simulation trajectory to scorer trace format. Pure.

    Returns list of dicts suitable for TraceEvent conversion.
    """
    from pi_bench.types import EventKind

    events = []
    for i, msg in enumerate(state.trajectory):
        kind_map = {
            MessageKind.USER: EventKind.USER_MESSAGE,
            MessageKind.AGENT: EventKind.AGENT_MESSAGE,
            MessageKind.TOOL_CALL: EventKind.TOOL_CALL,
            MessageKind.TOOL_RESULT: EventKind.TOOL_RESULT,
            MessageKind.SYSTEM: EventKind.STATE_CHANGE,
        }

        actor_map = {
            MessageKind.USER: "user",
            MessageKind.AGENT: "agent",
            MessageKind.TOOL_CALL: "agent",
            MessageKind.TOOL_RESULT: "tool",
            MessageKind.SYSTEM: "env",
        }

        payload: dict = {}
        if msg.content:
            payload["content"] = msg.content
        if msg.tool_calls:
            payload["tool_calls"] = [
                {"call_id": tc.call_id, "name": tc.name, "arguments": tc.arguments}
                for tc in msg.tool_calls
            ]
        if msg.error:
            payload["error"] = True

        event = {
            "i": i,
            "kind": kind_map[msg.kind].value,
            "actor": actor_map[msg.kind],
            "payload": payload,
        }

        if msg.call_id:
            event["call_id"] = msg.call_id

        events.append(event)

    return events
