"""Agent and User protocols — structural typing contracts for pi-bench."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class AgentProtocol(Protocol):
    """Any object with these methods can serve as an agent.

    Convention: generate() may include an "input_messages" key in the
    returned message dict containing the exact messages array sent to
    the LLM. This enables full prompt debugging in simulation output.
    """

    model_name: str

    def init_state(
        self,
        benchmark_context: list[dict],
        tools: list[dict],
        message_history: list[dict] | None = None,
    ) -> dict: ...

    def generate(self, message: dict, state: dict) -> tuple[dict, dict]: ...

    def is_stop(self, message: dict) -> bool: ...

    def set_seed(self, seed: int) -> None: ...

    def stop(self, message: dict | None, state: dict | None) -> None: ...


@runtime_checkable
class UserProtocol(Protocol):
    """Any object with these methods can serve as a user simulator.

    Convention: generate() may include an "input_messages" key in the
    returned message dict containing the exact messages array sent to
    the LLM. This enables full prompt debugging in simulation output.
    """

    model_name: str

    def init_state(
        self,
        scenario: dict,
        message_history: list[dict] | None = None,
    ) -> dict: ...

    def generate(self, message: dict, state: dict) -> tuple[dict, dict]: ...

    def is_stop(self, message: dict) -> bool: ...

    def set_seed(self, seed: int) -> None: ...

    def stop(self, message: dict | None, state: dict | None) -> None: ...
