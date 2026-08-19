"""Quote Desk — A2A wrapper around the quote-picking workflow."""

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
from newsroom_quoter.workflow import pick_quote

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


def get_agent_card(host: str, port: int) -> AgentCard:
    skill = AgentSkill(
        id="quote_desk",
        name="Quote Desk",
        description="Picks the most quotable verbatim sentence from an article and files it.",
        tags=["newsroom", "quote"],
        examples=[
            '{"story_id": "NEWS-1a2b3c4d", "angle": "Focus on the cost overrun.", "article": "The city opened..."}',
        ],
    )
    return AgentCard(
        name="Quote Desk",
        description=dedent(
            """\
            Pulls one verbatim sentence out of an article.

            ## How it works
            - Asks the model for the most quotable sentence, given the editor's angle
            - Verifies the pick really is a substring of the article; falls back to
              the first sentence when it is not
            - Files the quote in the story archive and returns it with a
              `verbatim` flag
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


class QuoterExecutor(AgentExecutor):
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
                "Picking the quote...",
                context_id=task_updater.context_id,
                task_id=task_updater.task_id,
            ),
        )
        try:
            result = await pick_quote(user_input)
            await task_updater.add_artifact([new_text_part(result)])
            await task_updater.complete()
        except Exception as exc:  # noqa: BLE001 — report, never crash the task
            logger.exception("quote picking failed")
            await task_updater.add_artifact([new_text_part(f"The quote could not be picked: {exc}")])
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
        agent_executor=QuoterExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=agent_card,
    )

    routes = [Route("/health", health, methods=["GET"])]
    routes.extend(create_agent_card_routes(agent_card))
    routes.extend(create_jsonrpc_routes(request_handler, "/", enable_v0_3_compat=True))

    logger.info("Quote Desk agent on %s:%d", host, port)
    uvicorn.run(Starlette(routes=routes), host=host, port=port)


if __name__ == "__main__":
    run()
