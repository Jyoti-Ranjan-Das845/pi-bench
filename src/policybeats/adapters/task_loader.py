"""
JSON Task Loader - loads task specifications from JSON files.

Implements TaskLoaderPort for file-based task loading.
Compatible with τ²-bench task format.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from policybeats.sim.types import (
    EnvAssertion,
    EvaluationCriteria,
    ExpectedAction,
    InitialState,
    TaskConfig,
    TaskDescription,
    TaskSpec,
    UserInstruction,
    UserScenario,
    UserScenarioInstructions,
)


class JSONTaskLoader:
    """
    Load tasks from JSON files.

    Expected directory structure:
        data_dir/
            {domain}/
                tasks.json    - Task specifications
                db.json       - Database records
                policy.md     - Optional policy document

    Compatible with τ²-bench data format.
    """

    def __init__(self, data_dir: Path | str):
        self.data_dir = Path(data_dir)
        self._task_cache: dict[str, TaskSpec] = {}
        self._db_cache: dict[str, dict[str, Any]] = {}

    def load(self, task_id: str) -> TaskSpec:
        """
        Load a task specification by ID.

        Searches all domains for the task.
        """
        if task_id in self._task_cache:
            return self._task_cache[task_id]

        # Search domains
        for domain_dir in self._iter_domain_dirs():
            tasks_file = domain_dir / "tasks.json"
            if tasks_file.exists():
                tasks = self._load_tasks_from_file(tasks_file, domain_dir.name)
                for task in tasks:
                    self._task_cache[task.id] = task

        if task_id not in self._task_cache:
            raise KeyError(f"Task not found: {task_id}")

        return self._task_cache[task_id]

    def load_by_domain(self, domain: str, task_id: str) -> TaskSpec:
        """Load a specific task from a specific domain."""
        domain_dir = self.data_dir / domain
        tasks_file = domain_dir / "tasks.json"

        if not tasks_file.exists():
            raise FileNotFoundError(f"No tasks.json in domain: {domain}")

        tasks = self._load_tasks_from_file(tasks_file, domain)
        for task in tasks:
            if task.id == task_id:
                return task

        raise KeyError(f"Task {task_id} not found in domain {domain}")

    def list_tasks(self, domain: str | None = None) -> tuple[str, ...]:
        """List all task IDs, optionally filtered by domain."""
        task_ids = []

        dirs = [self.data_dir / domain] if domain else self._iter_domain_dirs()

        for domain_dir in dirs:
            if isinstance(domain_dir, Path):
                tasks_file = domain_dir / "tasks.json"
                if tasks_file.exists():
                    tasks = self._load_tasks_from_file(
                        tasks_file, domain_dir.name
                    )
                    task_ids.extend(t.id for t in tasks)

        return tuple(sorted(set(task_ids)))

    def list_domains(self) -> tuple[str, ...]:
        """List all available domains."""
        domains = []
        for domain_dir in self._iter_domain_dirs():
            tasks_file = domain_dir / "tasks.json"
            if tasks_file.exists():
                domains.append(domain_dir.name)
        return tuple(sorted(domains))

    def load_db(self, domain: str) -> dict[str, Any]:
        """Load database for a domain."""
        if domain in self._db_cache:
            return self._db_cache[domain]

        db_file = self.data_dir / domain / "db.json"
        if not db_file.exists():
            return {}

        with open(db_file) as f:
            data = json.load(f)

        self._db_cache[domain] = data
        return data

    def load_policy(self, domain: str) -> str | None:
        """Load policy document for a domain."""
        policy_file = self.data_dir / domain / "policy.md"
        if policy_file.exists():
            return policy_file.read_text()
        return None

    def _iter_domain_dirs(self):
        """Iterate over domain directories."""
        if not self.data_dir.exists():
            return
        for item in self.data_dir.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                yield item

    def _load_tasks_from_file(
        self, path: Path, domain: str
    ) -> list[TaskSpec]:
        """Load tasks from a JSON file."""
        with open(path) as f:
            data = json.load(f)

        # Handle both list and dict with "tasks" key
        if isinstance(data, dict):
            tasks_data = data.get("tasks", [])
        else:
            tasks_data = data

        return [self._parse_task(t, domain) for t in tasks_data]

    def _parse_task(self, data: dict, domain: str) -> TaskSpec:
        """Parse a single task from JSON data."""
        # Parse description
        description = None
        if "description" in data and isinstance(data["description"], dict):
            desc_data = data["description"]
            description = TaskDescription(
                purpose=desc_data.get("purpose", ""),
                notes=desc_data.get("notes"),
                relevant_policies=tuple(desc_data.get("relevant_policies") or [])
                if desc_data.get("relevant_policies")
                else None,
            )

        # Parse user scenario
        user_scenario = None
        if "user_scenario" in data:
            user_scenario = self._parse_user_scenario(data["user_scenario"])

        # Parse initial state
        initial_state = None
        if "initial_state" in data and data["initial_state"]:
            initial_state = self._parse_initial_state(data["initial_state"])

        # Parse evaluation criteria
        evaluation_criteria = None
        if "evaluation_criteria" in data:
            evaluation_criteria = self._parse_evaluation_criteria(
                data["evaluation_criteria"]
            )

        return TaskSpec(
            id=data.get("id", data.get("task_id", "unknown")),
            description=description,
            user_scenario=user_scenario,
            ticket=data.get("ticket"),
            initial_state=initial_state,
            evaluation_criteria=evaluation_criteria,
            domain=domain,
            annotations=data.get("annotations"),
        )

    def _parse_user_scenario(self, data: dict) -> UserScenario:
        """Parse user scenario from JSON."""
        persona = data.get("persona")

        # Instructions can be string or dict
        instructions = None
        instr_data = data.get("instructions")

        if isinstance(instr_data, str):
            instructions = instr_data
        elif isinstance(instr_data, dict):
            instructions = UserScenarioInstructions(
                task_instructions=instr_data.get("task_instructions"),
                domain=instr_data.get("domain"),
                reason_for_call=instr_data.get("reason_for_call"),
                known_info=instr_data.get("known_info"),
                unknown_info=instr_data.get("unknown_info"),
            )

        return UserScenario(
            persona=persona,
            instructions=instructions,
        )

    def _parse_initial_state(self, data: dict) -> InitialState:
        """Parse initial state from JSON."""
        message_history = tuple(data.get("message_history") or [])
        initialization_data = data.get("initialization_data") or {}

        # Handle agent_data nested structure
        if "agent_data" in initialization_data:
            initialization_data = initialization_data["agent_data"]

        initialization_actions = tuple(data.get("initialization_actions") or [])

        return InitialState(
            message_history=message_history,
            initialization_data=initialization_data,
            initialization_actions=initialization_actions,
        )

    def _parse_evaluation_criteria(self, data: dict) -> EvaluationCriteria:
        """Parse evaluation criteria from JSON."""
        # Parse expected actions
        actions = []
        for action_data in data.get("actions") or []:
            actions.append(ExpectedAction(
                action_id=action_data.get("action_id", ""),
                name=action_data["name"],
                arguments=action_data.get("arguments", {}),
                compare_args=tuple(action_data["compare_args"])
                if action_data.get("compare_args")
                else None,
                info=action_data.get("info"),
            ))

        # Parse env assertions
        env_assertions = []
        for env_data in data.get("env_assertions") or []:
            env_assertions.append(EnvAssertion(
                env_type=env_data["env_type"],
                func_name=env_data["func_name"],
                arguments=env_data.get("arguments", {}),
            ))

        # Parse other fields
        nl_assertions = tuple(data.get("nl_assertions") or [])
        communicate_info = tuple(data.get("communicate_info") or [])
        reward_basis = tuple(data.get("reward_basis") or ["ACTION", "NL_ASSERTION"])

        return EvaluationCriteria(
            actions=tuple(actions),
            nl_assertions=nl_assertions,
            env_assertions=tuple(env_assertions),
            communicate_info=communicate_info,
            reward_basis=reward_basis,
        )


def create_task_loader(data_dir: Path | str) -> JSONTaskLoader:
    """Create a JSONTaskLoader for the given data directory."""
    return JSONTaskLoader(data_dir)


# === TaskConfig conversion ===


def taskspec_to_config(
    spec: TaskSpec,
    loader: JSONTaskLoader,
    system_prompt: str | None = None,
    available_tools: tuple[str, ...] = (),
    max_steps: int = 50,
    max_errors: int = 3,
) -> TaskConfig:
    """
    Convert TaskSpec to TaskConfig for simulation.

    Args:
        spec: Task specification
        loader: Task loader to get DB
        system_prompt: System prompt for agent
        available_tools: Tools available to agent
        max_steps: Max simulation steps
        max_errors: Max errors before termination

    Returns:
        TaskConfig ready for simulation
    """
    # Load domain database
    db = loader.load_db(spec.domain)

    # Apply initial state data
    if spec.initial_state and spec.initial_state.initialization_data:
        db = {**db, **spec.initial_state.initialization_data}

    # Build user instruction
    goal = ""
    context = None

    if spec.ticket:
        goal = spec.ticket
    elif spec.user_scenario and spec.user_scenario.instructions:
        instr = spec.user_scenario.instructions
        if isinstance(instr, str):
            goal = instr
        else:
            parts = []
            if instr.reason_for_call:
                parts.append(instr.reason_for_call)
            goal = "\n\n".join(parts) if parts else "Complete the task."
            context = instr.known_info

    # Default system prompt
    if system_prompt is None:
        policy = loader.load_policy(spec.domain)
        if policy:
            system_prompt = f"You are a helpful assistant.\n\n{policy}"
        else:
            system_prompt = "You are a helpful assistant."

    return TaskConfig(
        task_id=spec.id,
        domain=spec.domain,
        system_prompt=system_prompt,
        user_instruction=UserInstruction(
            goal=goal,
            context=context,
            constraints=(),
        ),
        initial_db=db,
        available_tools=available_tools,
        max_steps=max_steps,
        max_errors=max_errors,
        extra={"task_spec": spec},
    )
