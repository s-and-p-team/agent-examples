# newsroom-archive-tool — Story Archive

Part of [the newsroom example](../../a2a/newsroom_editor/README.md); the
editor's README is the guide to the whole system.

An in-memory MCP artifact store. Every agent in the newsroom files what it
produced here — summary, title, quote, keywords, brief — so one story
accumulates artifacts from four different callers. That fan-in is the shape the
example exists to exercise.

Tools: `save_artifact(story_id, kind, text, author)` · `get_story(story_id)`

There is no database; artifacts live for the life of the process, which is
enough to read a story back after a demo turn.
