"""Eligibility Review — an A2A agent in the prior-authorization example.

Receives an eligibility question from the intake agent, reads the member's
policy from the Patient Records MCP server, and returns a coverage verdict.
"""

import logging
import os
from textwrap import dedent

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from a2a.helpers import (
    new_task_from_user_message,
    new_text_message,
    new_text_part,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    TaskState,
)
from priorauth_eligibility.workflow import review

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


def get_agent_card(host: str, port: int) -> AgentCard:
    skill = AgentSkill(
        id="eligibility_review",
        name="Eligibility Review",
        description="Decides whether a member's health plan covers a requested procedure.",
        tags=["healthcare", "insurance", "eligibility", "prior-authorization"],
        examples=[
            '{"policy_number": "HP-88213445", "procedure_code": "73721", "requested_procedure": "MRI knee"}',
        ],
    )
    return AgentCard(
        name="Eligibility Review",
        description=dedent(
            """\
            Reviews a prior-authorization request against the member's health
            plan.

            ## How it works
            - Reads the member's policy from the patient records service
            - Weighs the requested procedure against the plan's exclusions and
              prior-authorization rules
            - Replies COVERED, NOT COVERED or NEEDS REVIEW with a short reason
            """
        ),
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=False),
        skills=[skill],
        supported_interfaces=[
            AgentInterface(
                url=os.getenv("AGENT_ENDPOINT", f"http://{host}:{port}").rstrip("/") + "/",
                protocol_binding="JSONRPC",
            )
        ],
    )


class EligibilityExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if not task:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        task_updater = TaskUpdater(event_queue, task.id, task.context_id)

        user_input = context.get_user_input()
        await task_updater.update_status(
            TaskState.TASK_STATE_WORKING,
            new_text_message(
                "Checking the member's coverage...",
                context_id=task_updater.context_id,
                task_id=task_updater.task_id,
            ),
        )
        try:
            verdict = await review(user_input)
            await task_updater.add_artifact([new_text_part(verdict)])
            await task_updater.complete()
        except Exception as exc:  # noqa: BLE001 — report, never crash the task
            logger.exception("eligibility review failed")
            await task_updater.add_artifact([new_text_part(f"NEEDS REVIEW — eligibility review failed: {exc}")])
            await task_updater.failed()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise Exception("cancel not supported")


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def run() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    agent_card = get_agent_card(host, port)

    request_handler = DefaultRequestHandler(
        agent_executor=EligibilityExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=agent_card,
    )

    routes = [Route("/health", health, methods=["GET"])]
    routes.extend(create_agent_card_routes(agent_card))
    routes.extend(create_jsonrpc_routes(request_handler, "/", enable_v0_3_compat=True))

    logger.info("Eligibility Review agent on %s:%d", host, port)
    uvicorn.run(Starlette(routes=routes), host=host, port=port)


if __name__ == "__main__":
    run()
