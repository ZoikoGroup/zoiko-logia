# Standard response output-limit repair

The standard Groq adapter previously read response content without checking
`finish_reason`. A provider response ending with `length` could therefore be
treated as a finished answer, an optional rewrite, or a chart tool request.
The agent loop already checked for this condition.

The standard adapter now checks every completion, including tool recovery
and final chart narration, before handing content or tool calls to its caller.
A truncated response raises a safe typed `ProviderResponseIncomplete` error.
The existing orchestration failure path retains independently verified work
and distinguishes service failure from policy refusal. Optional rewrites return
no replacement so that the existing answer can continue through verification.
This does not automatically increase output allowances or spend tokens retrying.

Scripted regressions cover both request-budget and standalone adapter use,
optional rewrite preservation, and the user-facing unavailable outcome.
The complete offline backend suite passed: **3,194 passed**, 21 skipped,
2 expected failures and 130 warnings. Whitespace checks also passed.
No live Groq calls were made. Shared database migrations and deployment were
not performed. Durable memory still requires the database preparation described
in [the memory review](kriton-memory-and-provenance-2026-10-19.md).

This closes one verified completion-handling gap. It does not establish live
answer quality or guarantee uninterrupted answers when provider capacity is
exhausted. Cross-worker provider-capacity scheduling remains outstanding.
