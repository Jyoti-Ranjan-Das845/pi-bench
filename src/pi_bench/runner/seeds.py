"""Seed derivation — deterministic SHA-256 trial seeds."""

import hashlib


_MAX_SEED = 2**63 - 1  # OpenAI max seed value


def derive_seed(base_seed: int, item_id: str, trial: int = 0) -> int:
    """Derive a deterministic seed from a stable item id and trial index."""
    h = hashlib.sha256(f"{base_seed}:{item_id}:{trial}".encode()).hexdigest()[:16]
    return int(h, 16) % _MAX_SEED


def derive_trial_seeds(
    base_seed: int, tasks: list[dict], num_trials: int
) -> list[tuple[dict, int, int]]:
    """Generate (task, trial, seed) tuples with SHA-256 derived seeds.

    seed = int(sha256(f"{base_seed}:{task_id}:{trial}").hexdigest()[:16], 16)
    Order-independent: changing task count doesn't shift other seeds.
    """
    result = []
    for task in tasks:
        for trial in range(num_trials):
            trial_seed = derive_seed(base_seed, task["id"], trial)
            result.append((task, trial, trial_seed))
    return result


def build_work_queue(
    tasks: list[dict],
    num_trials: int,
    base_seed: int,
    completed: set[tuple],
    include_seed_in_key: bool = False,
) -> list[tuple[dict, int, int]]:
    """Generate (task, trial, seed) tuples, excluding completed."""
    all_work = derive_trial_seeds(base_seed, tasks, num_trials)
    return [
        (task, trial, seed)
        for task, trial, seed in all_work
        if _work_key(task, trial, seed, include_seed_in_key) not in completed
    ]


def _work_key(
    task: dict,
    trial: int,
    seed: int,
    include_seed: bool,
) -> tuple:
    """Return the resume key for a planned work item."""
    if include_seed:
        return (task["id"], trial, seed)
    return (task["id"], trial)
