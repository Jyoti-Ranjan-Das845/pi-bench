"""ENV_ASSERTION evaluator — run callable assertions against the environment.

Matches tau2-bench behavior: multiplicative scoring. One failed
assertion zeroes out the entire evaluator (1.0 * 0.0 = 0.0).
"""

import logging

logger = logging.getLogger(__name__)


def evaluate_env_assertions(assertions: list[dict], domain: dict) -> float:
    """Run assertion functions against the environment.

    Each assertion has a 'function' key with a callable.
    Returns 1.0 if all callable assertions pass, 0.0 if any fail.
    Only assertions with a callable function are evaluated.
    """
    results = evaluate_env_assertions_rich(assertions, domain)
    return 1.0 if all(r["passed"] for r in results) else 0.0


def evaluate_env_assertions_rich(assertions: list[dict], domain: dict) -> list[dict]:
    """Return one explainable result per callable environment assertion."""
    if not assertions:
        return []

    callable_assertions = [a for a in assertions if a.get("function") and callable(a["function"])]
    if not callable_assertions:
        return []

    results = []
    for idx, assertion in enumerate(callable_assertions):
        fn = assertion["function"]
        fn_name = fn.__name__ if hasattr(fn, "__name__") else str(fn)
        try:
            result = fn(domain)
            passed = bool(result)
            detail = f"assertion {fn_name} returned {result!r}"
            if not passed:
                logger.info("ENV_ASSERTION: assertion failed: %s", fn_name)
        except Exception as exc:
            logger.warning("ENV_ASSERTION: assertion raised exception: %s", exc)
            passed = False
            detail = f"assertion {fn_name} raised {type(exc).__name__}: {exc}"
        results.append({
            "outcome_id": assertion.get("outcome_id", f"ENV_ASSERTION_{idx}"),
            "type": "env_assertion",
            "passed": passed,
            "detail": detail,
        })

    return results
