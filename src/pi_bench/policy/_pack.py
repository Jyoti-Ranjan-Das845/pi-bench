"""
Policy pack compilation: compile a PolicyPack into a single PolicyFn.

Resolution semantics (per GOAL.md):
1. Rules are evaluated in priority order (higher first)
2. Exception relationships: if rule A is exception_of rule B,
   and A passes, B's violation is suppressed
3. Conflict detection: if rules with same priority contradict
   without explicit precedence → AMBIGUOUS_CONFLICT
"""

from __future__ import annotations

from pi_bench.types import (
    Ambiguity,
    AmbiguityKind,
    ExposedState,
    PolicyPack,
    PolicyScore,
    PolicyVerdict,
    RuleSpec,
    Trace,
    Violation,
)

from ._compilers import RULE_COMPILERS
from ._types import PolicyFn, RuleFn, RuleResult


def compile_rule(spec: RuleSpec) -> tuple[RuleFn, str | None]:
    """
    Compile a RuleSpec to an executable RuleFn.

    Returns:
        Tuple of (compiled function, error message if unknown kind)
    """
    compiler = RULE_COMPILERS.get(spec.kind)
    if compiler is None:
        # Unknown rule kind - return function that always returns ambiguous

        def unknown_rule(_trace: Trace, _state: ExposedState) -> RuleResult:
            return RuleResult(
                passed=True,  # Don't fail, just ambiguous
                ambiguous=True,
                ambiguity_reason=f"unknown_rule_kind:{spec.kind}",
            )

        return unknown_rule, f"unknown_rule_kind:{spec.kind}"

    return compiler(spec), None


def compile_policy_pack(pack: PolicyPack) -> tuple[PolicyFn, list[str]]:
    """
    Compile a PolicyPack to a single PolicyFn.

    Returns:
        Tuple of (compiled policy function, list of compilation errors)
    """
    compiled_rules: list[tuple[RuleSpec, RuleFn]] = []
    errors: list[str] = []

    # Sort rules by priority (descending - higher priority first)
    sorted_specs = sorted(pack.rules, key=lambda s: s.priority, reverse=True)

    for spec in sorted_specs:
        fn, err = compile_rule(spec)
        compiled_rules.append((spec, fn))
        if err:
            errors.append(err)

    # Build exception graph: exception_rule_id -> base_rule_id
    exception_graph: dict[str, str] = {}
    for spec in sorted_specs:
        if spec.exception_of:
            exception_graph[spec.rule_id] = spec.exception_of

    def evaluate(trace: Trace, state: ExposedState) -> PolicyScore:
        # Evaluate all rules and collect results
        rule_results: dict[str, tuple[RuleSpec, RuleResult]] = {}
        for spec, fn in compiled_rules:
            result = fn(trace, state)
            rule_results[spec.rule_id] = (spec, result)

        # Collect violations, ambiguities, and check for conflicts
        violations: list[Violation] = []
        suppressed_violations: set[str] = set()
        has_ambiguity = False
        ambiguity_reasons: list[str] = []
        has_conflict = False
        conflict_rules: list[str] = []

        # First pass: identify which violations are suppressed by exceptions
        for rule_id, (spec, result) in rule_results.items():
            if spec.exception_of and result.passed:
                # This exception passed, suppress the base rule's violation
                suppressed_violations.add(spec.exception_of)

        # Second pass: collect violations and ambiguities
        for rule_id, (spec, result) in rule_results.items():
            if result.ambiguous:
                has_ambiguity = True
                if result.ambiguity_reason:
                    ambiguity_reasons.append(result.ambiguity_reason)

            if not result.passed and not result.ambiguous:
                # Check if this violation is suppressed by an exception
                if rule_id not in suppressed_violations:
                    violations.append(
                        Violation(
                            rule_id=spec.rule_id,
                            kind=spec.kind,
                            evidence=result.evidence,
                        )
                    )

        # Third pass: detect conflicts (same priority, contradictory results)
        # Group rules by priority
        priority_groups: dict[int, list[tuple[str, RuleSpec, RuleResult]]] = {}
        for rule_id, (spec, result) in rule_results.items():
            if spec.priority not in priority_groups:
                priority_groups[spec.priority] = []
            priority_groups[spec.priority].append((rule_id, spec, result))

        # Check for conflicts within each priority group
        for priority, group in priority_groups.items():
            if len(group) < 2:
                continue

            # Look for deny vs allow conflicts at same priority
            deny_rules = [
                (rid, s, r) for rid, s, r in group
                if s.override_mode == "deny" and not r.passed and not r.ambiguous
            ]
            allow_rules = [
                (rid, s, r) for rid, s, r in group
                if s.override_mode == "allow" and r.passed
            ]

            # If we have both deny and allow at same priority with no exception relationship
            if deny_rules and allow_rules:
                for deny_rid, _, _ in deny_rules:
                    for allow_rid, _, _ in allow_rules:
                        # Check if one is exception of the other
                        if (exception_graph.get(allow_rid) != deny_rid and
                            exception_graph.get(deny_rid) != allow_rid):
                            has_conflict = True
                            conflict_rules.extend([deny_rid, allow_rid])

        # Determine verdict
        if has_conflict:
            return PolicyScore(
                verdict=PolicyVerdict.AMBIGUOUS_CONFLICT,
                ambiguity=Ambiguity(
                    kind=AmbiguityKind.AMBIGUOUS_CONFLICT,
                    reason="conflicting_rules_same_priority",
                    missing=tuple(set(conflict_rules)),
                ),
            )

        if violations:
            return PolicyScore(
                verdict=PolicyVerdict.VIOLATION,
                violations=tuple(sorted(violations, key=lambda v: v.rule_id)),
            )

        if has_ambiguity:
            # Determine ambiguity kind from reasons
            if any("unknown_rule_kind" in r for r in ambiguity_reasons):
                kind = AmbiguityKind.AMBIGUOUS_POLICY
            elif any("missing_state_field" in r for r in ambiguity_reasons):
                kind = AmbiguityKind.AMBIGUOUS_STATE
            else:
                kind = AmbiguityKind.AMBIGUOUS_STATE

            return PolicyScore(
                verdict=PolicyVerdict(kind.value),
                ambiguity=Ambiguity(
                    kind=kind,
                    reason=ambiguity_reasons[0] if ambiguity_reasons else "unknown",
                    missing=tuple(ambiguity_reasons),
                ),
            )

        return PolicyScore(verdict=PolicyVerdict.COMPLIANT)

    return evaluate, errors
