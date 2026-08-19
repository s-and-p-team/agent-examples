# newsroom-titler — Headline Desk

Part of [the newsroom example](../newsroom_editor/README.md); the editor's
README is the guide to the whole system.

Writes a headline of at most ten words from a story summary and files it in
the story archive. The titler is the deepest link in the chain: it is called by
the summarizer, never by the editor, and it never sees the article — its
output is a derivation of a derivation.

In: `{"story_id", "summary"}` · Out: `{"story_id", "title"}`
