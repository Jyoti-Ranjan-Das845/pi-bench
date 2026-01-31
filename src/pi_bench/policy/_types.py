"""Rule result types and type aliases for compiled checkers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pi_bench.types import (
    EvidencePointer,
    ExposedState,
    PolicyScore,
    Trace,
)


@dataclass(frozen=True, slots=True)
class RuleResult:
    """Result of evaluating a single rule."""

    passed: bool
    evidence: tuple[EvidencePointer, ...] = ()
    ambiguous: bool = False
    ambiguity_reason: str | None = None


# Type aliases for compiled functions
RuleFn = Callable[[Trace, ExposedState], RuleResult]
PolicyFn = Callable[[Trace, ExposedState], PolicyScore]
