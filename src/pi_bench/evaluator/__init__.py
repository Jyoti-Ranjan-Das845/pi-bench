"""Evaluator — reward composition dispatcher."""

import logging

from pi_bench.decision import CanonicalDecision, InvalidRun, resolve
from pi_bench.evaluator.action import evaluate_actions, evaluate_actions_rich
from pi_bench.evaluator.communicate import evaluate_communicate, evaluate_communicate_rich
from pi_bench.evaluator.db import evaluate_db, evaluate_db_checks, evaluate_db_rich
from pi_bench.evaluator.env_assertion import evaluate_env_assertions, evaluate_env_assertions_rich
from pi_bench.evaluator.nl_assertion import evaluate_nl_assertions, evaluate_nl_judge_checks
from pi_bench.evaluator.policy import evaluate_policy, evaluate_policy_rich
from pi_bench.evaluator.report import classify_dimensions

logger = logging.getLogger(__name__)

# Tier-2 evaluator types: NL/semantic judges. These contribute to
# semantic_score but do NOT affect all_passed or reward.
_TIER2_TYPES = frozenset({"NL_ASSERTION", "NL_JUDGE"})


def evaluate(task: dict, simulation: dict, domain: dict) -> dict:
    """Run all evaluators, compose reward. Returns RewardInfo dict.

    RewardInfo = {
        "reward": float,           # 1.0 if all tier1 passed, else 0.0
        "reward_basis": list,      # which evaluators ran
        "reward_breakdown": dict,  # per-evaluator details
        "all_passed": bool,        # tier1 checks only
        "semantic_score": float,   # tier2 (NL judge) pass-rate
        "outcome_results": list,   # per-check results
        "dimensions": dict,        # per-dimension pass/fail summary
    }

    Dispatches to evaluators based on reward_basis list in evaluation_criteria.
    Tier1 evaluators (ACTION, DB, COMMUNICATE, ENV_ASSERTION, POLICY,
    STATE_FIELD) determine all_passed and reward. Tier2 evaluators
    (NL_ASSERTION, NL_JUDGE) only affect semantic_score.
    """
    termination = simulation.get("termination_reason", "")
    normal_endings = ("agent_stop", "user_stop", "max_steps", "agent_error")
    decision_result = _resolve_decision(simulation)
    decision_info = _decision_info(decision_result)

    if termination not in normal_endings:
        return {
            "reward": 0.0,
            "reward_basis": [],
            "reward_breakdown": {"reason": f"abnormal_termination:{termination}"},
            "all_passed": False,
            "semantic_score": 0.0,
            "outcome_results": [],
            "dimensions": classify_dimensions([]),
            **decision_info,
        }

    criteria = task.get("evaluation_criteria", {})
    if not criteria:
        return {
            "reward": 1.0,
            "reward_basis": [],
            "reward_breakdown": {},
            "all_passed": True,
            "semantic_score": 1.0,
            "outcome_results": [],
            "dimensions": classify_dimensions([]),
            **decision_info,
        }

    reward_basis = criteria.get("reward_basis", [])
    if not reward_basis:
        return {
            "reward": 1.0,
            "reward_basis": [],
            "reward_breakdown": {},
            "all_passed": True,
            "semantic_score": 1.0,
            "outcome_results": [],
            "dimensions": classify_dimensions([]),
            **decision_info,
        }

    breakdown = {}
    rewards = []
    outcome_results = []
    judge_cache: dict[tuple[str, str], tuple[bool, str]] = {}

    for evaluator_type in reward_basis:
        if evaluator_type == "ACTION":
            expected = criteria.get("expected_actions", [])
            action_results = evaluate_actions_rich(expected, simulation.get("messages", []))
            r = 1.0 if all(x["passed"] for x in action_results) else 0.0
            breakdown["ACTION"] = r
            rewards.append(r)
            outcome_results.extend(action_results)

        elif evaluator_type == "DB":
            db_results = evaluate_db_rich(task, simulation, domain)
            r = 1.0 if all(x["passed"] for x in db_results) else 0.0
            breakdown["DB"] = r
            rewards.append(r)
            outcome_results.extend(db_results)

        elif evaluator_type == "COMMUNICATE":
            info = criteria.get("communicate_info", [])
            communicate_results = evaluate_communicate_rich(
                info, simulation.get("messages", [])
            )
            r = 1.0 if all(x["passed"] for x in communicate_results) else 0.0
            breakdown["COMMUNICATE"] = r
            rewards.append(r)
            outcome_results.extend(communicate_results)

        elif evaluator_type == "ENV_ASSERTION":
            assertions = criteria.get("env_assertions", [])
            env_results = evaluate_env_assertions_rich(assertions, domain)
            r = 1.0 if all(x["passed"] for x in env_results) else 0.0
            breakdown["ENV_ASSERTION"] = r
            rewards.append(r)
            outcome_results.extend(env_results)

        elif evaluator_type == "NL_ASSERTION":
            nl_assertions = criteria.get("nl_assertions", [])
            r = evaluate_nl_assertions(
                nl_assertions,
                simulation.get("messages", []),
                cache=judge_cache,
            )
            breakdown["NL_ASSERTION"] = r
            rewards.append(r)
            outcome_results.append({
                "type": "NL_ASSERTION", "passed": r == 1.0, "detail": f"score={r}",
            })

        elif evaluator_type == "POLICY":
            policy_checks = criteria.get("policy_checks", [])
            trace = simulation.get("trace")
            if trace is not None:
                # Use rich evaluation to get per-check results
                check_results = evaluate_policy_rich(
                    policy_checks, trace, simulation.get("messages", [])
                )
                r = 1.0 if all(x["passed"] for x in check_results) else 0.0
                outcome_results.extend(check_results)
            else:
                logger.warning("POLICY: no trace in simulation — scoring 0.0")
                r = 0.0
            breakdown["POLICY"] = r
            rewards.append(r)

        elif evaluator_type == "STATE_FIELD":
            state_checks = criteria.get("state_field_checks", [])
            env = simulation.get("env", {})
            results = evaluate_db_checks(state_checks, env)
            r = 1.0 if all(x["passed"] for x in results) else 0.0
            breakdown["STATE_FIELD"] = r
            rewards.append(r)
            outcome_results.extend(results)

        elif evaluator_type == "NL_JUDGE":
            judge_checks = criteria.get("nl_judge_checks", [])
            msgs = simulation.get("messages", [])
            results = evaluate_nl_judge_checks(
                judge_checks,
                msgs,
                cache=judge_cache,
            )
            r = 1.0 if all(x["passed"] for x in results) else 0.0
            breakdown["NL_JUDGE"] = r
            rewards.append(r)
            outcome_results.extend(results)

        else:
            # E1: unknown evaluator type — warn and score 0.0
            logger.warning("Unknown evaluator type: %s — scoring 0.0", evaluator_type)
            breakdown[evaluator_type] = 0.0
            rewards.append(0.0)
            outcome_results.append({
                "type": evaluator_type, "passed": False, "detail": "unknown evaluator",
            })

    # Split outcome_results into tier1 (hard pass/fail) and tier2 (semantic)
    tier1 = [r for r in outcome_results if r["type"] not in _TIER2_TYPES]
    tier2 = [r for r in outcome_results if r["type"] in _TIER2_TYPES]

    all_passed = all(r["passed"] for r in tier1) if tier1 else True
    semantic_score = (
        sum(r["passed"] for r in tier2) / len(tier2) if tier2 else 1.0
    )
    dimensions = classify_dimensions(outcome_results)

    return {
        "reward": 1.0 if all_passed else 0.0,
        "reward_basis": reward_basis,
        "reward_breakdown": breakdown,
        "all_passed": all_passed,
        "semantic_score": semantic_score,
        "outcome_results": outcome_results,
        "dimensions": dimensions,
        **decision_info,
    }


__all__ = [
    "evaluate",
    "evaluate_actions",
    "evaluate_communicate",
    "evaluate_db",
    "evaluate_env_assertions",
    "evaluate_nl_assertions",
    "evaluate_policy",
]


def _resolve_decision(simulation: dict) -> CanonicalDecision | InvalidRun | None:
    """Resolve the canonical decision when a trace is available."""
    trace = simulation.get("trace")
    if trace is None:
        return None
    return resolve(trace)


def _decision_info(
    decision_result: CanonicalDecision | InvalidRun | None,
) -> dict:
    """Convert a decision result into stable reward-info fields."""
    if decision_result is None:
        return {
            "canonical_decision": None,
            "decision_channel": None,
            "decision_valid": False,
            "decision_error": "NO_TRACE",
        }
    if isinstance(decision_result, CanonicalDecision):
        return {
            "canonical_decision": decision_result.decision,
            "decision_channel": decision_result.channel,
            "decision_valid": True,
            "decision_error": None,
        }
    return {
        "canonical_decision": None,
        "decision_channel": None,
        "decision_valid": False,
        "decision_error": decision_result.reason,
    }
