"""A2A Executor — handles incoming assessment requests from AgentBeats.

Implements the a2a-sdk AgentExecutor interface. Parses the incoming request
to extract the purple agent URL and assessment config, runs the multi-domain
assessment engine, and returns results as a DataPart artifact via TaskUpdater.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from typing_extensions import override

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import DataPart, Part, TextPart
from a2a.utils import new_agent_text_message, new_task

from pi_bench.a2a.assessment import run_assessment
from pi_bench.a2a.results import to_agentbeats_results

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentBeatsEnvelope:
    """Normalized AgentBeats assessment request.

    This wrapper keeps AgentBeats-specific request shapes out of the core
    assessment runner. The runner still receives only a purple URL and config.
    """

    purple_url: str
    agent_id: str
    domain: str
    config: dict[str, Any]


class PIBenchExecutor(AgentExecutor):
    """Executes pi-bench assessments for incoming A2A requests.

    Accepts an assessment request containing a purple agent URL,
    runs all scenarios (finra, retail, helpdesk) against it, and
    returns AgentBeats-formatted results as an artifact.
    """

    def __init__(self, concurrency: int = 1) -> None:
        self.concurrency = max(1, int(concurrency))

    @override
    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Handle an incoming assessment request.

        Expected input (as a data or text part in the message):
            {
                "participants": {
                    "agent": "<purple_agent_url>"
                },
                "config": {
                    "domain": "policy_compliance",
                    "scenario_scope": "all",
                    "max_steps": 40,
                    "user_model": "gpt-5.4",
                    "seed": 42
                }
            }

        For local tests, participants.agent may also be an object:
            {"url": "<purple_agent_url>", "id": "<agent_id>"}
        """
        msg = context.message
        if not msg:
            await event_queue.enqueue_event(
                new_agent_text_message(
                    json.dumps({"error": "No message in request"})
                )
            )
            return

        task = context.current_task
        if not task:
            task = new_task(msg)
            await event_queue.enqueue_event(task)

        context_id = task.context_id
        updater = TaskUpdater(event_queue, task.id, context_id)
        await updater.start_work()

        try:
            request_data = _extract_request_data(context)
            envelope = _parse_agentbeats_envelope(
                request_data,
                server_concurrency=self.concurrency,
            )

            if not envelope.purple_url:
                await updater.failed(
                    new_agent_text_message(
                        "No purple agent URL provided",
                        context_id=context_id,
                        task_id=task.id,
                    )
                )
                return

            logger.info(
                "Starting assessment for agent %s at %s (concurrency=%d)",
                envelope.agent_id,
                envelope.purple_url,
                envelope.config["concurrency"],
            )

            t0 = time.monotonic()

            scenario_results = await asyncio.to_thread(
                run_assessment,
                purple_url=envelope.purple_url,
                config=envelope.config,
            )

            elapsed = time.monotonic() - t0

            agentbeats_results = to_agentbeats_results(
                agent_id=envelope.agent_id,
                domain=envelope.domain,
                scenario_results=scenario_results,
                time_used=elapsed,
            )

            await updater.add_artifact(
                parts=[Part(root=DataPart(data=agentbeats_results))],
                name="PI-Bench Assessment Results",
            )

            logger.info(
                "Assessment completed in %.2fs — %d scenarios",
                elapsed, len(scenario_results),
            )
            await updater.complete()

        except Exception as exc:
            logger.exception("Assessment failed")
            error_msg = f"Assessment failed: {exc}"

            await updater.add_artifact(
                parts=[
                    Part(root=TextPart(text=error_msg)),
                    Part(root=DataPart(data={"error": str(exc)})),
                ],
                name="PI-Bench Assessment Results (Failed)",
            )

            await updater.failed(
                new_agent_text_message(
                    error_msg,
                    context_id=context_id,
                    task_id=task.id,
                )
            )

    @override
    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Notify caller that cancellation is not supported.

        PI-Bench assessments run synchronously in a thread and cannot be
        interrupted mid-scenario. The caller receives an error message.
        """
        await event_queue.enqueue_event(
            new_agent_text_message(
                json.dumps({"error": "Cancellation not supported"})
            )
        )


def _extract_request_data(context: RequestContext) -> dict[str, Any]:
    """Extract assessment request data from the A2A RequestContext."""
    message = context.message
    if message is None:
        return {}

    for part in message.parts or []:
        if hasattr(part, "root"):
            part = part.root
        if hasattr(part, "data") and part.data is not None:
            return dict(part.data) if isinstance(part.data, dict) else {}
        if hasattr(part, "text") and part.text:
            try:
                return json.loads(part.text)
            except json.JSONDecodeError:
                continue

    return {}


def _parse_agentbeats_envelope(
    request_data: dict[str, Any],
    *,
    server_concurrency: int,
) -> AgentBeatsEnvelope:
    """Normalize AgentBeats and local assessment request shapes.

    Supported participant forms:
    - Official/AgentBeats style: {"participants": {"agent": "http://..."}}
    - Local rich style: {"participants": {"agent": {"url": "http://...", "id": "..."}}}
    - Direct style: {"purple_agent_url": "http://...", "purple_agent_id": "..."}
    """
    role, purple_url, agent_id = _extract_agent_participant(request_data)
    config = dict(request_data.get("config", {}))
    domain = str(config.pop("domain", "policy_compliance") or "policy_compliance")

    config.setdefault("scenario_scope", "all")
    config.setdefault("user_model", "gpt-5.4")
    config.setdefault("max_steps", 40)
    config.setdefault("seed", 42)

    requested_concurrency = _positive_int(
        config.get("concurrency", server_concurrency),
        default=server_concurrency,
    )
    config["concurrency"] = min(requested_concurrency, max(1, int(server_concurrency)))

    # This public AgentBeats wrapper supports full-set and domain runs. The
    # lower-level assessment function keeps doing the actual validation.
    scope = str(config.get("scenario_scope", "all")).strip().lower()
    if scope not in {"all", "domain"}:
        raise ValueError("scenario_scope must be 'all' or 'domain'")
    config["scenario_scope"] = scope

    if scope == "domain" and not config.get("scenario_domain"):
        raise ValueError("scenario_domain is required when scenario_scope='domain'")

    return AgentBeatsEnvelope(
        purple_url=purple_url,
        agent_id=agent_id or role,
        domain=domain,
        config=config,
    )


def _extract_agent_participant(request_data: dict[str, Any]) -> tuple[str, str, str]:
    """Extract participant role, endpoint URL, and leaderboard id."""
    participants = request_data.get("participants")
    agentbeats_ids = request_data.get("agentbeats_ids", {})

    if isinstance(participants, dict) and participants:
        if "agent" in participants:
            role = "agent"
            participant = participants["agent"]
        else:
            role, participant = next(iter(participants.items()))

        if isinstance(participant, str):
            purple_url = participant
            agent_id = _agentbeats_id_for(role, agentbeats_ids) or role
            return role, purple_url.rstrip("/"), agent_id

        if isinstance(participant, dict):
            purple_url = str(
                participant.get("url")
                or participant.get("endpoint")
                or participant.get("base_url")
                or ""
            )
            agent_id = str(
                participant.get("id")
                or participant.get("agentbeats_id")
                or _agentbeats_id_for(role, agentbeats_ids)
                or role
            )
            return role, purple_url.rstrip("/"), agent_id

    purple_url = str(request_data.get("purple_agent_url") or "")
    agent_id = str(request_data.get("purple_agent_id") or request_data.get("agentbeats_id") or "agent")
    return "agent", purple_url.rstrip("/"), agent_id


def _agentbeats_id_for(role: str, agentbeats_ids: Any) -> str | None:
    if isinstance(agentbeats_ids, dict):
        value = agentbeats_ids.get(role)
        if value:
            return str(value)
    return None


def _positive_int(value: Any, *, default: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)
