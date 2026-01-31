"""
AgentExecutor implementation for PI-Bench Green Agent.

Handles A2A protocol execution using TaskUpdater artifacts.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    DataPart,
    InvalidRequestError,
    Part,
    Task,
    TaskState,
    TextPart,
)
from a2a.utils import new_agent_text_message, new_task
from a2a.utils.errors import ServerError
from pydantic import BaseModel

from pi_bench.a2a.engine import run_multi_turn_assessment

logger = logging.getLogger(__name__)


TERMINAL_STATES = {
    TaskState.completed,
    TaskState.canceled,
    TaskState.failed,
    TaskState.rejected,
}


class AssessmentRequest(BaseModel):
    """Assessment request parsed from A2A message."""

    purple_agent_url: str
    purple_agent_id: str = "agent"
    agentbeats_id: str | None = None
    agent_name: str | None = None


def parse_assessment_request(message_text: str) -> AssessmentRequest | None:
    """
    Parse an A2A message into an assessment request.

    Supports two formats:
    1. Direct: {"purple_agent_url": "http://...", "purple_agent_id": "agent"}
    2. AgentBeats: {"participants": {"agent": "http://..."}, "agentbeats_ids": {...}, "agent_names": {...}, "config": {...}}
    """
    try:
        data = json.loads(message_text)

        agentbeats_id = None
        agent_name = None

        participants = data.get("participants")
        if participants:
            # AgentBeats format - participants is a dict like {"agent": "http://..."}
            if isinstance(participants, dict):
                # Get first role and endpoint
                for role, endpoint in participants.items():
                    purple_agent_id = role
                    purple_agent_url = str(endpoint)

                    # Extract agentbeats_id and agent_name if provided
                    agentbeats_ids = data.get("agentbeats_ids", {})
                    agent_names = data.get("agent_names", {})

                    if isinstance(agentbeats_ids, dict):
                        agentbeats_id = agentbeats_ids.get(role)
                    if isinstance(agent_names, dict):
                        agent_name = agent_names.get(role)

                    break
                else:
                    return None
            else:
                return None
        else:
            # Direct format
            purple_agent_url = data.get("purple_agent_url")
            purple_agent_id = data.get("purple_agent_id", "agent")
            agentbeats_id = data.get("agentbeats_id")
            agent_name = data.get("agent_name")

            if not purple_agent_url:
                return None

        # Strip trailing slash to avoid double slashes in URLs
        purple_agent_url = purple_agent_url.rstrip("/")

        return AssessmentRequest(
            purple_agent_url=purple_agent_url,
            purple_agent_id=purple_agent_id,
            agentbeats_id=agentbeats_id,
            agent_name=agent_name,
        )

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.debug(f"Failed to parse assessment request: {e}")
        return None


class Executor(AgentExecutor):
    """
    PI-Bench Green Agent Executor.

    Orchestrates GDPR policy compliance assessments for purple agents.
    """

    def __init__(self, output_file: str | None = None):
        """
        Initialize executor.

        Args:
            output_file: Optional file path to write results JSON (e.g., /app/output/results.json)
        """
        self.output_file = output_file

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Execute assessment request."""
        msg = context.message
        if not msg:
            raise ServerError(error=InvalidRequestError(message="Missing message in request"))

        task = context.current_task
        if task and task.status.state in TERMINAL_STATES:
            raise ServerError(
                error=InvalidRequestError(
                    message=f"Task {task.id} already processed (state: {task.status.state})"
                )
            )

        if not task:
            task = new_task(msg)
            await event_queue.enqueue_event(task)

        context_id = task.context_id
        updater = TaskUpdater(event_queue, task.id, context_id)
        await updater.start_work()

        try:
            # Extract text from message
            message_text = ""
            for part in msg.parts:
                if hasattr(part.root, "text") and part.root.text:
                    message_text += part.root.text

            # Parse assessment request
            assessment_request = parse_assessment_request(message_text)
            if assessment_request is None:
                await updater.reject(
                    new_agent_text_message(
                        "Invalid assessment request. Expected JSON with "
                        "purple_agent_url and purple_agent_id, or AgentBeats "
                        "format with participants.",
                        context_id=context_id,
                        task_id=task.id,
                    )
                )
                return

            await updater.update_status(
                TaskState.working,
                new_agent_text_message(
                    f"Starting GDPR assessment for {assessment_request.purple_agent_id} "
                    f"at {assessment_request.purple_agent_url}",
                    context_id=context_id,
                    task_id=task.id,
                ),
            )

            logger.info(
                f"Running multi-turn GDPR assessment for {assessment_request.purple_agent_id} "
                f"at {assessment_request.purple_agent_url}"
            )

            # Run assessment (all 94 scenarios)
            import time as _time

            t0 = _time.monotonic()

            try:
                report = await run_multi_turn_assessment(
                    purple_url=assessment_request.purple_agent_url,
                )
                elapsed = _time.monotonic() - t0

                # Convert report to AgentBeats format
                from pi_bench.a2a.results import report_to_agentbeats

                results_json = report_to_agentbeats(
                    report,
                    purple_agent_id=assessment_request.purple_agent_id,
                    agentbeats_id=assessment_request.agentbeats_id,
                    agent_name=assessment_request.agent_name,
                    time_used=elapsed,
                )

                # Return results as artifact - ONLY DataPart so agentbeats-client can extract it
                await updater.add_artifact(
                    parts=[
                        Part(root=DataPart(data=results_json)),
                    ],
                    name="PI-Bench Assessment Results",
                )

                logger.info(f"Assessment completed in {elapsed:.2f}s")

                # Mark task as completed so agentbeats-client can extract results
                await updater.complete()

            except Exception as assessment_error:
                elapsed = _time.monotonic() - t0
                logger.exception(f"Assessment failed after {elapsed:.2f}s")

                # Still try to save partial results if available
                error_message = f"Assessment failed: {str(assessment_error)}"

                # Create minimal error report
                from pi_bench.a2a.results import report_to_agentbeats
                from pi_bench.a2a.assessment import AssessmentReport

                error_report = AssessmentReport(scenario_results=[], metadata={})
                results_json = report_to_agentbeats(
                    error_report,
                    purple_agent_id=assessment_request.purple_agent_id,
                    agentbeats_id=assessment_request.agentbeats_id,
                    agent_name=assessment_request.agent_name,
                    time_used=elapsed,
                )

                # Add error details
                results_json["error"] = error_message

                await updater.add_artifact(
                    parts=[
                        Part(root=TextPart(text=error_message)),
                        Part(root=DataPart(data=results_json)),
                    ],
                    name="PI-Bench Assessment Results (Failed)",
                )

                # Mark as failed but with artifact
                await updater.failed(
                    new_agent_text_message(
                        error_message, context_id=context_id, task_id=task.id
                    )
                )
                return

        except Exception as e:
            logger.exception("Fatal assessment error")
            await updater.failed(
                new_agent_text_message(
                    f"Fatal error: {str(e)}", context_id=context_id, task_id=task.id
                )
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Cancel is not supported."""
        raise ServerError(error=InvalidRequestError(message="Cancel not supported"))
