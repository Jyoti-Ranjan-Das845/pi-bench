"""
Tests for JSON task loader.
"""

import json
import pytest
from pathlib import Path
import tempfile

from policybeats.adapters.task_loader import (
    JSONTaskLoader,
    create_task_loader,
    taskspec_to_config,
)
from policybeats.sim.types import (
    EvaluationCriteria,
    ExpectedAction,
    TaskSpec,
    UserScenario,
    UserScenarioInstructions,
)


@pytest.fixture
def temp_data_dir():
    """Create a temporary data directory with mock tasks."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)

        # Create mock domain
        mock_dir = data_dir / "mock"
        mock_dir.mkdir()

        # Create tasks.json
        tasks = [
            {
                "id": "test_task_1",
                "description": {
                    "purpose": "Test task 1",
                    "notes": "Simple test"
                },
                "user_scenario": {
                    "persona": "Professional",
                    "instructions": {
                        "task_instructions": "If agent asks, say yes.",
                        "reason_for_call": "Need help",
                        "known_info": "User ID is test_user",
                        "domain": "mock"
                    }
                },
                "evaluation_criteria": {
                    "actions": [
                        {
                            "action_id": "1",
                            "name": "get_user",
                            "arguments": {"user_id": "test_user"}
                        }
                    ],
                    "nl_assertions": ["Agent should be helpful"],
                    "reward_basis": ["ACTION"]
                }
            },
            {
                "id": "test_task_2",
                "ticket": "Simple ticket task",
                "evaluation_criteria": {
                    "nl_assertions": ["Task should complete"]
                }
            }
        ]
        (mock_dir / "tasks.json").write_text(json.dumps(tasks))

        # Create db.json
        db = {
            "users": {
                "test_user": {"user_id": "test_user", "name": "Test User"}
            }
        }
        (mock_dir / "db.json").write_text(json.dumps(db))

        # Create policy.md
        (mock_dir / "policy.md").write_text("# Test Policy\n\nBe helpful.")

        yield data_dir


class TestJSONTaskLoader:
    def test_load_task(self, temp_data_dir):
        loader = JSONTaskLoader(temp_data_dir)
        task = loader.load("test_task_1")

        assert task.id == "test_task_1"
        assert task.domain == "mock"
        assert task.description is not None
        assert task.description.purpose == "Test task 1"

    def test_load_task_with_scenario(self, temp_data_dir):
        loader = JSONTaskLoader(temp_data_dir)
        task = loader.load("test_task_1")

        assert task.user_scenario is not None
        assert task.user_scenario.persona == "Professional"
        assert isinstance(task.user_scenario.instructions, UserScenarioInstructions)
        assert task.user_scenario.instructions.task_instructions == "If agent asks, say yes."

    def test_load_task_with_ticket(self, temp_data_dir):
        loader = JSONTaskLoader(temp_data_dir)
        task = loader.load("test_task_2")

        assert task.ticket == "Simple ticket task"

    def test_load_evaluation_criteria(self, temp_data_dir):
        loader = JSONTaskLoader(temp_data_dir)
        task = loader.load("test_task_1")

        assert task.evaluation_criteria is not None
        assert len(task.evaluation_criteria.actions) == 1
        assert task.evaluation_criteria.actions[0].name == "get_user"
        assert len(task.evaluation_criteria.nl_assertions) == 1

    def test_list_tasks(self, temp_data_dir):
        loader = JSONTaskLoader(temp_data_dir)
        tasks = loader.list_tasks()

        assert "test_task_1" in tasks
        assert "test_task_2" in tasks

    def test_list_domains(self, temp_data_dir):
        loader = JSONTaskLoader(temp_data_dir)
        domains = loader.list_domains()

        assert "mock" in domains

    def test_load_db(self, temp_data_dir):
        loader = JSONTaskLoader(temp_data_dir)
        db = loader.load_db("mock")

        assert "users" in db
        assert "test_user" in db["users"]

    def test_load_policy(self, temp_data_dir):
        loader = JSONTaskLoader(temp_data_dir)
        policy = loader.load_policy("mock")

        assert policy is not None
        assert "Be helpful" in policy

    def test_task_not_found(self, temp_data_dir):
        loader = JSONTaskLoader(temp_data_dir)

        with pytest.raises(KeyError):
            loader.load("nonexistent_task")

    def test_load_by_domain(self, temp_data_dir):
        loader = JSONTaskLoader(temp_data_dir)
        task = loader.load_by_domain("mock", "test_task_1")

        assert task.id == "test_task_1"
        assert task.domain == "mock"


class TestTaskSpecToConfig:
    def test_convert_simple_task(self, temp_data_dir):
        loader = JSONTaskLoader(temp_data_dir)
        spec = loader.load("test_task_1")

        config = taskspec_to_config(
            spec,
            loader,
            system_prompt="You are a test assistant",
            available_tools=("get_user", "set_data"),
        )

        assert config.task_id == "test_task_1"
        assert config.domain == "mock"
        assert config.system_prompt == "You are a test assistant"
        assert "get_user" in config.available_tools

    def test_convert_with_db(self, temp_data_dir):
        loader = JSONTaskLoader(temp_data_dir)
        spec = loader.load("test_task_1")

        config = taskspec_to_config(spec, loader)

        # Should have loaded DB
        assert "users" in config.initial_db

    def test_convert_with_policy_prompt(self, temp_data_dir):
        loader = JSONTaskLoader(temp_data_dir)
        spec = loader.load("test_task_1")

        config = taskspec_to_config(spec, loader)

        # Should include policy in system prompt
        assert "Be helpful" in config.system_prompt

    def test_taskspec_in_extra(self, temp_data_dir):
        loader = JSONTaskLoader(temp_data_dir)
        spec = loader.load("test_task_1")

        config = taskspec_to_config(spec, loader)

        # TaskSpec should be stored in extra
        assert "task_spec" in config.extra
        assert config.extra["task_spec"].id == "test_task_1"


class TestCreateTaskLoader:
    def test_create_loader(self, temp_data_dir):
        loader = create_task_loader(temp_data_dir)
        assert isinstance(loader, JSONTaskLoader)

    def test_string_path(self, temp_data_dir):
        loader = create_task_loader(str(temp_data_dir))
        assert isinstance(loader, JSONTaskLoader)


class TestRealDataLoading:
    """Test loading actual data files if they exist."""

    def test_load_mock_tasks(self):
        """Test loading from our created data/mock directory."""
        # Path relative to tests
        data_dir = Path(__file__).parent.parent / "data"
        if not data_dir.exists():
            pytest.skip("Data directory not found")

        loader = JSONTaskLoader(data_dir)
        domains = loader.list_domains()

        if "mock" not in domains:
            pytest.skip("Mock domain not configured")

        tasks = loader.list_tasks("mock")
        assert len(tasks) > 0

        # Load a specific task
        if "verify_passenger_count" in tasks:
            task = loader.load("verify_passenger_count")
            assert task.evaluation_criteria is not None
            assert len(task.evaluation_criteria.actions) > 0
