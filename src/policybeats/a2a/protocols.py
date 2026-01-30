"""
Port definitions for the PolicyBeats assessment pipeline (hexagonal architecture).

Ports are Callable type aliases — pure functions, no classes.
Adapters provide concrete implementations.

Ports:
    RunScenario   — runs a multi-turn scenario, returns evaluations + env
    EvaluateTurn  — evaluates a single turn against policy rules
    FormatReport  — formats an AssessmentReport into output dict
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

from policybeats.a2a.protocol import (
    AssessmentReport,
    Environment,
    MultiTurnScenario,
    PurpleResponse,
    ScenarioTurn,
    TurnEvaluation,
)

# Policy function returned by compile_policy_pack
PolicyFn = Any  # Callable[[Trace, ExposedState], PolicyScore]

# --- Ports (function signatures) ---

RunScenario = Callable[
    [aiohttp.ClientSession, str, MultiTurnScenario, PolicyFn],
    Awaitable[tuple[list[TurnEvaluation], Environment]],
]

EvaluateTurn = Callable[
    [ScenarioTurn, PurpleResponse, Environment, PolicyFn],
    TurnEvaluation,
]

FormatReport = Callable[
    [AssessmentReport, str, float],
    dict[str, Any],
]
