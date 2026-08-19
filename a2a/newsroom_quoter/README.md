# newsroom-quoter — Quote Desk

Part of [the newsroom example](../newsroom_editor/README.md); the editor's
README is the guide to the whole system.

Picks the single most quotable sentence from an article, verifies the pick is
a literal substring of the article (falling back to the first sentence when the
model paraphrases), and files it in the story archive. The quoter is the
newsroom's checkable transformation: anyone reading the lineage can confirm by
eye that this payload descends from the article.

In: `{"story_id", "angle", "article"}` · Out: `{"story_id", "quote", "verbatim"}`
