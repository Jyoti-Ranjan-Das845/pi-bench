"""Orchestrator core — the complete simulation engine.

One module, seven functions, each does one thing:

    classify_event    Look at a message, say what happened.
    next_role         Given what happened, say who goes next.
    handle_generate   Make agent/user produce a message.
    handle_env        Execute tool calls against environment.
    step              One turn of the simulation.
    run               Full simulation loop.
    init              Build the starting SimState.
"""

import time
import uuid
from typing import Any, Union  # noqa: F401 — Any used in observer type hint

from pi_bench.environment import make_tool_call, get_tool_schemas, get_policy
from pi_bench.observer import observed_tool_call
from pi_bench.local import AgentProtocol, UserProtocol
from pi_bench.types import is_stop_signal, validate_message
from pi_bench.orchestrator.state import SimState, GeneratorRole, Event, Message


# --- Termination reasons ---

TERMINATION_REASONS: dict[tuple[GeneratorRole, str], str] = {
    ("agent", "stop"):  "agent_stop",
    ("agent", "error"): "agent_error",
    ("user",  "stop"):  "user_stop",
    ("user",  "error"): "user_error",
}

# Maps state machine role → message role string
_MESSAGE_ROLES: dict[GeneratorRole, str] = {
    "agent": "assistant",
    "user": "user",
}


# ── classify ─────────────────────────────────────────────

def classify_event(
    msg: Message | None,
    role: GeneratorRole,
    protocol: Union[AgentProtocol, UserProtocol],
    solo: bool,
) -> Event:
    """Look at a message, say what happened.

    Classification order (first match wins):
        None or invalid        → "error"
        stop signal            → "stop"
        has tool_calls         → "tool_calls"
        otherwise              → "text"

    In solo mode, text from the agent is allowed (models often produce
    planning/acknowledgement text before tool calls). The step() function
    routes solo text back to the agent for another turn.
    """
    if msg is None:
        return "error"
    if not validate_message(msg):
        return "error"
    if protocol.is_stop(msg) or is_stop_signal(msg):
        return "stop"
    if msg.get("tool_calls"):
        return "tool_calls"
    return "text"


def next_role(current: GeneratorRole, event: Event) -> str | None:
    """Given what happened, say who goes next.

    Returns a Role string or None (terminal).

        stop/error   → None (done)
        tool_calls   → environment
        text         → the other party
    """
    if event in ("stop", "error"):
        return None
    if event == "tool_calls":
        return "environment"
    return "user" if current == "agent" else "agent"


# ── handlers ─────────────────────────────────────────────

def handle_generate(
    state: SimState,
    protocol: Union[AgentProtocol, UserProtocol],
    role: GeneratorRole,
) -> tuple[SimState, Event]:
    """Make agent/user produce a message.

    Calls protocol.generate(), appends to trajectory, classifies event.
    Does NOT decide the next routing target — that's step()'s job.
    """
    role_state = state.agent_state if role == "agent" else state.user_state

    try:
        msg, new_role_state = protocol.generate(state.current_message, role_state)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "generate() failed for %s: %s: %s", role, type(exc).__name__, exc
        )
        return state, "error"

    if role == "agent":
        state.agent_state = new_role_state
    else:
        state.user_state = new_role_state

    state.trajectory.append(msg)
    state.current_message = msg

    event = classify_event(msg, role, protocol, state.solo)
    return state, event


def handle_env(
    state: SimState,
    env: dict,
    observer: dict[str, Any] | None = None,
) -> SimState:
    """Execute tool calls against the environment.

    Loops over tool_calls, executes each, wraps results into a message,
    appends to trajectory. Returns updated state.

    When observer is provided, routes calls through observed_tool_call()
    for trace recording and optional policy gating.

    No routing decision — caller handles that via state.env_caller.
    """
    msg = state.current_message
    tool_calls = msg.get("tool_calls", [])
    requestor = _MESSAGE_ROLES.get(state.env_caller, "assistant")

    results = []
    for tc in tool_calls:
        if observer is not None:
            result = observed_tool_call(
                observer,
                tool_name=tc["name"],
                call_id=tc.get("id", "call"),
                arguments=tc.get("arguments", {}),
                requestor=requestor,
            )
        else:
            result = make_tool_call(
                env,
                tool_name=tc["name"],
                call_id=tc.get("id", "call"),
                arguments=tc.get("arguments", {}),
                requestor=requestor,
            )
        result["name"] = tc["name"]
        if result.get("error"):
            state.error_count += 1
        results.append(result)

    # Wrap results into a message
    if len(results) == 1:
        tool_msg: Message = {"role": "tool", **results[0]}
    else:
        tool_msg = {
            "role": "multi_tool",
            "tool_messages": [{"role": "tool", **r} for r in results],
        }

    state.trajectory.append(tool_msg)
    state.current_message = tool_msg
    state.tools = get_tool_schemas(env)

    return state


# ── step ─────────────────────────────────────────────────

def step(
    state: SimState,
    agent: AgentProtocol,
    user: UserProtocol | None,
    env: dict,
    observer: dict[str, Any] | None = None,
) -> SimState:
    """One turn of the simulation.

    If environment's turn: execute tools, route back to caller.
    If agent/user's turn: generate message, classify, route.
    """
    if state.to_role == "environment":
        state = handle_env(state, env, observer=observer)
        state.to_role = state.env_caller
        state.env_caller = None
    else:
        role: GeneratorRole = state.to_role
        protocol = agent if role == "agent" else user
        state, event = handle_generate(state, protocol, role)

        target = next_role(role, event)
        if target is None:
            state.done = True
            state.termination_reason = TERMINATION_REASONS.get(
                (role, event), "unknown"
            )
        elif target == "environment":
            state.env_caller = role
            state.to_role = "environment"
            state.solo_text_count = 0  # tool call breaks the text-only streak
        elif state.solo and target == "user":
            # Solo mode: no user, route text back to agent for another turn.
            # Cap consecutive text-only messages to prevent infinite spin.
            state.solo_text_count += 1
            if state.solo_text_count >= 5:
                state.done = True
                state.termination_reason = "agent_error"
            else:
                state.to_role = "agent"
        else:
            state.to_role = target

    state.step_count += 1
    return state


# ── run ──────────────────────────────────────────────────

def run(
    agent: AgentProtocol,
    user: UserProtocol | None,
    env: dict,
    task: dict,
    max_steps: int = 50,
    max_errors: int = 10,
    seed: int | None = None,
    solo: bool = False,
    observer: dict[str, Any] | None = None,
) -> dict:
    """Full simulation loop. Returns a SimulationRun dict."""
    if not solo and user is None:
        raise ValueError("user is required unless solo=True")

    start_time = time.time()

    state = init(agent, user, env, task, seed=seed, solo=solo)

    while not state.done:
        state = step(state, agent, user, env, observer=observer)
        if not state.done and state.to_role != "environment":
            if state.step_count >= max_steps:
                state.done = True
                state.termination_reason = "max_steps"
            elif state.error_count >= max_errors:
                state.done = True
                state.termination_reason = "too_many_errors"

    # Cleanup
    try:
        agent.stop(state.current_message, state.agent_state)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("agent.stop() failed: %s", exc)
    if not solo and user is not None:
        try:
            user.stop(state.current_message, state.user_state)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("user.stop() failed: %s", exc)

    end_time = time.time()

    # Assign turn indices
    for i, msg in enumerate(state.trajectory):
        msg["turn_index"] = i

    return {
        "id": str(uuid.uuid4()),
        "task_id": task["id"],
        "start_time": start_time,
        "end_time": end_time,
        "duration": end_time - start_time,
        "termination_reason": state.termination_reason,
        "messages": state.trajectory,
        "trial": 0,
        "seed": state.seed,
        "step_count": state.step_count,
    }


# ── init ─────────────────────────────────────────────────

def init(
    agent: AgentProtocol,
    user: UserProtocol | None,
    env: dict,
    task: dict,
    seed: int | None = None,
    solo: bool = False,
) -> SimState:
    """Build the starting SimState.

    Three paths:
        solo=True:  Agent works from a ticket, no user.
        history:    Resume from previous message history.
        default:    Fresh start with greeting → user.
    """
    if not solo and user is None:
        raise ValueError("user is required unless solo=True")

    if seed is not None:
        agent.set_seed(seed)
        if not solo and user is not None:
            user.set_seed(seed)

    tools = get_tool_schemas(env)
    benchmark_context = build_benchmark_context(env, task)
    history = task.get("initial_state", {}).get("message_history")

    if solo:
        agent_state = agent.init_state(
            benchmark_context=benchmark_context,
            tools=tools,
            message_history=history,
        )
        # Use role "user" for the trigger so providers like Anthropic that
        # require at least one non-system message can process it.
        trigger: Message = {"role": "user", "content": _solo_trigger_content(task)}
        return SimState(
            to_role="agent",
            current_message=trigger,
            trajectory=[trigger] if not history else list(history),
            agent_state=agent_state,
            tools=tools,
            solo=True,
            seed=seed,
        )

    if history:
        history_errors = validate_message_history(history)
        if history_errors:
            raise ValueError(f"Invalid message history: {'; '.join(history_errors)}")
        agent_history = _filter_history(history, "agent")
        user_history = _filter_history(history, "user")
        agent_state = agent.init_state(
            benchmark_context=benchmark_context,
            tools=tools,
            message_history=agent_history,
        )
        user_state = user.init_state(task.get("user_scenario", {}), message_history=user_history)
        last = history[-1]
        return SimState(
            to_role=_role_from_message(last),
            current_message=last,
            trajectory=list(history),
            agent_state=agent_state,
            user_state=user_state,
            tools=tools,
            seed=seed,
        )

    # Fresh start: greeting → user
    greeting: Message = {"role": "assistant", "content": "Hi! How can I help you today?"}
    agent_state = agent.init_state(
        benchmark_context=benchmark_context,
        tools=tools,
        message_history=[greeting],
    )
    user_state = user.init_state(task.get("user_scenario", {}))
    return SimState(
        to_role="user",
        current_message=greeting,
        trajectory=[greeting],
        agent_state=agent_state,
        user_state=user_state,
        tools=tools,
        seed=seed,
    )


# ── init helpers ─────────────────────────────────────────

def build_benchmark_context(env: dict, task: dict) -> list[dict]:
    """Build the public benchmark context passed to tested agents.

    The orchestrator provides policy/task context as structured data. Agent
    implementations decide whether to place it in a system prompt, memory, or
    another context store.
    """
    metadata = {
        "scenario_id": task.get("scenario_id", task.get("id", "")),
        "domain": task.get("domain", ""),
        "domain_name": task.get("domain_name", ""),
        "policy_version": task.get("policy_version", ""),
    }

    context: list[dict] = []
    policy = get_policy(env)
    if policy:
        context.append(
            {
                "kind": "policy",
                "content": policy,
                "metadata": metadata,
            }
        )

    context.append(
        {
            "kind": "task",
            "content": task["description"],
            "metadata": metadata,
        }
    )
    return context


def _solo_trigger_content(task: dict) -> str:
    """Return the startup message for solo runs.

    Prefer a prepared ticket when the caller provides one. Otherwise use the
    scenario's initial user message so solo runs start from the same customer
    request as non-solo scripted-user runs. Keep task description only as a
    final fallback for minimal/legacy tasks.
    """
    ticket = task.get("ticket")
    if isinstance(ticket, str) and ticket.strip():
        return ticket

    initial_message = task.get("user_scenario", {}).get("initial_user_message")
    if isinstance(initial_message, str) and initial_message.strip():
        return initial_message

    return task["description"]


def _filter_history(history: list[dict], role: str) -> list[dict]:
    """Filter message history per-role for resume.

    For multi_tool messages, builds a NEW wrapper containing only the
    sub-messages belonging to the requested role's requestor. This prevents
    leaking the other side's tool results.
    """
    filtered = []
    for msg in history:
        msg_role = msg.get("role")
        if msg_role == "system":
            filtered.append(msg)
        elif role == "agent":
            if msg_role == "assistant":
                filtered.append(msg)
            elif msg_role == "tool" and msg.get("requestor") == "assistant":
                filtered.append(msg)
            elif msg_role == "multi_tool":
                subs = [m for m in msg.get("tool_messages", []) if m.get("requestor") == "assistant"]
                if subs:
                    filtered.append({"role": "multi_tool", "tool_messages": subs})
        elif role == "user":
            if msg_role == "user":
                filtered.append(msg)
            elif (
                msg_role == "assistant"
                and msg.get("content")
                and not msg.get("tool_calls")
            ):
                filtered.append(msg)
            elif msg_role == "tool" and msg.get("requestor") == "user":
                filtered.append(msg)
            elif msg_role == "multi_tool":
                subs = [m for m in msg.get("tool_messages", []) if m.get("requestor") == "user"]
                if subs:
                    filtered.append({"role": "multi_tool", "tool_messages": subs})
    return filtered


def validate_message_history(history: list[dict]) -> list[str]:
    """Validate a message history for resume. Returns list of errors (empty = valid).

    Checks:
        - Every tool call has a matching tool result (by call ID).
        - Every tool result has a matching tool call.
        - Messages have valid roles.
        - Assistant/user messages have content and/or tool_calls.
        - If tool_calls exist, routing goes to the environment.
    """
    errors = []
    pending_tool_calls: dict[str, str] = {}  # call_id → tool_name

    for i, msg in enumerate(history):
        role = msg.get("role")

        if role in ("assistant", "user"):
            if not validate_message(msg):
                errors.append(f"Message {i}: invalid message shape")
            for tc in msg.get("tool_calls", []):
                call_id = tc.get("id", "")
                pending_tool_calls[call_id] = tc.get("name", "unknown")

        elif role == "tool":
            call_id = msg.get("id", "")
            if call_id in pending_tool_calls:
                del pending_tool_calls[call_id]
            else:
                errors.append(f"Message {i}: tool result for unknown call ID '{call_id}'")

        elif role == "multi_tool":
            for sub in msg.get("tool_messages", []):
                call_id = sub.get("id", "")
                if call_id in pending_tool_calls:
                    del pending_tool_calls[call_id]
                else:
                    errors.append(f"Message {i}: tool result for unknown call ID '{call_id}'")

        elif role not in ("system",):
            errors.append(f"Message {i}: unknown role '{role}'")

    for call_id, name in pending_tool_calls.items():
        errors.append(f"Unresolved tool call '{name}' (ID: {call_id})")

    return errors


def _role_from_message(msg: dict) -> str:
    """Determine the next routing target from the last message in history."""
    role = msg.get("role")
    if role == "assistant":
        return "environment" if msg.get("tool_calls") else "user"
    if role == "user":
        return "environment" if msg.get("tool_calls") else "agent"
    if role == "tool":
        requestor = msg.get("requestor", "assistant")
        return "agent" if requestor == "assistant" else "user"
    if role == "multi_tool":
        # Wrapper has no top-level requestor — derive from first sub-message
        subs = msg.get("tool_messages", [])
        requestor = subs[0].get("requestor", "assistant") if subs else "assistant"
        return "agent" if requestor == "assistant" else "user"
    return "agent"
