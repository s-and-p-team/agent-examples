# newsroom-summarizer — Summary Desk

Part of [the newsroom example](../newsroom_editor/README.md); the editor's
README is the guide to the whole system.

Condenses an article into a three-sentence summary guided by the editor's
angle, files the summary in the story archive, then delegates the headline to
the Headline Desk — passing only the summary, never the article. That onward
delegation is what makes the newsroom a chain three agents deep.

In: `{"story_id", "angle", "article"}` · Out: `{"story_id", "summary", "title"}`
