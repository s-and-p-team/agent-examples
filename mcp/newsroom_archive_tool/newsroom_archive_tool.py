"""Story Archive MCP tool — the shared write target of the newsroom example.

Every agent in the newsroom files what it produced here: the summarizer its
summary, the titler its headline, the quoter its pull-quote, and the editor the
keywords and the finished brief. One story therefore accumulates artifacts from
four different callers, which is exactly the fan-in shape the lineage pipeline
has to attribute correctly.

The store is in-memory on purpose: the example needs no database, restarts
clean, and keeps the whole tool one file. Artifacts survive for the life of the
process, which is enough to read a story back after a demo turn.
"""

import itertools
import json
import logging
import os
import sys
from collections import defaultdict

from fastmcp import FastMCP

mcp = FastMCP("StoryArchive")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    stream=sys.stdout,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

_stories: dict[str, list[dict]] = defaultdict(list)
_ids = itertools.count(1)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False})
def save_artifact(story_id: str, kind: str, text: str, author: str) -> str:
    """File one artifact of a story.

    `kind` names what the text is (summary, title, quote, keywords, brief),
    `author` names the agent that produced it. Returns the artifact id.
    """
    artifact_id = f"ART-{next(_ids):04d}"
    _stories[story_id].append({"artifact_id": artifact_id, "kind": kind, "text": text, "author": author})
    logger.info("save_artifact story=%s kind=%s author=%s -> %s", story_id, kind, author, artifact_id)
    return json.dumps({"artifact_id": artifact_id, "story_id": story_id, "kind": kind})


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True})
def get_story(story_id: str) -> str:
    """Read every artifact filed for a story, in filing order."""
    artifacts = _stories.get(story_id, [])
    logger.info("get_story story=%s -> %d artifacts", story_id, len(artifacts))
    return json.dumps({"story_id": story_id, "found": bool(artifacts), "artifacts": artifacts})


def run() -> None:
    transport = os.getenv("MCP_TRANSPORT", "streamable-http")
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    logger.info("StoryArchive MCP server on %s:%d", host, port)
    mcp.run(transport=transport, host=host, port=port)


if __name__ == "__main__":
    run()
