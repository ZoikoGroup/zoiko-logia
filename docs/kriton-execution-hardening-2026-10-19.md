# Kriton execution hardening — 19 October 2026

Subsequent work: [durable conversation inputs and numerical identity](kriton-memory-and-provenance-2026-10-19.md) implements the next memory/provenance phase and records its database activation requirement. The remaining-work section below describes the state immediately after execution hardening.

Implemented locally after the architecture review. No live model calls, provider configuration changes, deployment, commit or push were performed.

## Implemented

- One request-scoped Groq generation allowance now covers the agent, standard composition, supporting classification/verification calls and answer repairs. It shares token accounting, conservative reservations, completion limits, a model-call limit and an absolute deadline. A nested orchestration call shares the allowance; concurrent requests have separate allowances. Closing or cancelling a request prevents inherited background work from initiating new generations against its budget.
- `MODEL_REQUEST_MAX_CALLS` defaults to 20 and is documented in `.env.example`. This is a ceiling across these Groq calls, not a promise that every request should use 20 calls. Existing token and completion settings remain in effect. Auxiliary calls can request a smaller completion allowance.
- Groq SDK automatic retries are disabled in both standard and auxiliary paths. The adapter no longer shortens a provider cooldown and retries a rate-limited account. Existing invalid-tool-argument corrections and eligible fallback paths remain bounded by the shared request allowance.
- Spending and provider-authentication failures prevent another transport attempt within the same request. Rate-limit failures prevent another transport attempt against the same model within that request, without incorrectly blocking a separately allowed model. Structured 401/403, 413 and 429 provider failures have safe classifications; raw provider response bodies are not shown to users.
- A failed optional answer repair returns control to the existing verification path, which can retain supported text and identify incomplete parts. It does not erase that text merely because another generation cannot fit the budget or the provider is unavailable.
- Explanation subtasks explicitly marked as not requiring authoritative evidence are now instructed to explain from supplied facts and general reasoning. Tasks requiring current or authoritative facts still require evidence. Suggested business causes must remain questions to investigate rather than factual assertions.
- Primary composition failures without recoverable work now return `outcome="unavailable"`, not `"refused"`. The frontend understands the new outcome and separately identifies provider usage limits and request processing limits. The workflow and request logs recognize these service failures. Actual policy refusals remain distinct.
- The final response audit includes request-wide Groq calls, usage/reservation totals and configured ceilings. Estimates remain distinguishable from provider-reported usage; the configured cost estimate is not a billing statement.
- A narrow recipe-domain regression now exercises an actual domain boundary without invoking a model. Financial costing, budget and margin wording remains eligible for the domain path. The old test had accidentally accepted composition failure as proof of correct domain refusal.

## Verification

- Backend: **3,167 passed**, 21 skipped, 2 expected failures. The run reported 127 warnings, primarily existing test-mock coroutine and dependency warnings.
- Frontend: **212 passed**.
- TypeScript, changed-file ESLint, whitespace and unresolved-merge checks passed.
- New offline cases exercise shared standard/agent/auxiliary budgets, nested and concurrent requests, cancellation, deadlines, terminal failure suppression, model-specific rate limits, optional repair failure, service outcome classification and evidence instructions.
- No live Groq transport was used. Model output in these checks is scripted; live answer quality and actual token savings were not measured.

## Remaining architectural work

The current controls are request-scoped. They do **not** coordinate the organization's rolling token allowance across API workers, other applications or later requests. A shared admission/queue mechanism still needs implementation and configuration against the real account limits. No automatic retry/resume queue was introduced here.

Conversation history is still bounded and selected rather than persisted as a complete structured scenario ledger. Numerical checks still combine calculation receipts with heuristic attribution rather than a complete typed dependency graph. The existing semantic planner remains in shadow mode; it was not enabled as an additional paid call. The new shared Groq allowance does not claim equivalent transport-level accounting for Gemini or OpenAI adapters.

Those changes require their own focused implementation and integration verification. They should preserve tenant authorization, explicit domain boundaries and trustworthy numerical inputs. These fixes do not establish ChatGPT/Claude equivalence or guarantee an answer during provider outages or exhausted allowances.

For manual validation, use a fresh chat for the original manufacturing question, retain that chat for both scenario follow-ups, and inspect the new audit outcome and completeness. Historical response cards retain their original contents.
