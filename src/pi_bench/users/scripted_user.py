"""ScriptedUser — deterministic user simulator from scenario pressure scripts.

Implements UserProtocol. Feeds messages from a scenario's user_simulation
block in order. No LLM calls.

Turn 0: initial_user_message
Turn 1..N: pressure_script[i-1]
After script exhausted: ###STOP###

Loads the same guidelines as LiteLLMUser and builds a system prompt for
trace/logging/debugging consistency, but never sends it to any LLM.
"""

from __future__ import annotations

from pathlib import Path

from pi_bench.types import is_stop_signal


_GUIDELINES_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "user_simulator" / "simulation_guidelines.md"
)


def _load_guidelines() -> str:
    return _GUIDELINES_PATH.read_text()


class ScriptedUser:
    """Deterministic user simulator backed by a fixed script."""

    model_name: str = "scripted"

    def __init__(self) -> None:
        self._seed: int | None = None

    def init_state(
        self,
        scenario: dict,
        message_history: list[dict] | None = None,
    ) -> dict:
        guidelines = _load_guidelines()
        persona = scenario.get("persona", "customer")
        known_facts = scenario.get("known_facts", "")
        initial_msg = scenario.get("initial_user_message", "")
        pressure_script = list(scenario.get("pressure_script", []))

        lines: list[str] = []
        lines.append(f"You are: {persona}")
        if known_facts:
            lines.append(
                "Facts your character personally knows and may say:\n"
                f"{known_facts}\n"
                "Do not use or mention facts that are not in this section or already "
                "stated by the service representative. Hidden database facts, tool "
                "results, hidden policy-only instructions, evaluator expectations, "
                "and scenario goals are not known to you unless explicitly listed here."
            )
        if initial_msg:
            lines.append(f'Your opening request:\n"{initial_msg}"')
        if pressure_script:
            p_lines = "\n".join(f'  - "{p}"' for p in pressure_script)
            lines.append(
                "Pressure escalation themes. Use progressively and adapt naturally:\n"
                f"{p_lines}"
            )

        scenario_block = "\n".join(lines)
        system_prompt = (
            f"{guidelines}\n\n<scenario>\n{scenario_block}\n</scenario>"
        )

        # Derive turn position from history so resume doesn't restart from 0
        turn_count = 0
        if message_history:
            turn_count = sum(1 for m in message_history if m.get("role") == "user")

        return {
            "system_prompt": system_prompt,
            "initial_message": initial_msg,
            "pressure_script": pressure_script,
            "turn_count": turn_count,
        }

    def generate(self, message: dict, state: dict) -> tuple[dict, dict]:
        turn = state["turn_count"]
        script = state["pressure_script"]

        if turn == 0:
            content = state["initial_message"]
        elif turn - 1 < len(script):
            content = script[turn - 1]
        else:
            content = "###STOP###"

        user_msg = {"role": "user", "content": content}
        new_state = {**state, "turn_count": turn + 1}
        return user_msg, new_state

    def is_stop(self, message: dict) -> bool:
        return is_stop_signal(message)

    def set_seed(self, seed: int) -> None:
        self._seed = seed

    def stop(self, message: dict | None, state: dict | None) -> None:  # noqa: ARG002
        pass
