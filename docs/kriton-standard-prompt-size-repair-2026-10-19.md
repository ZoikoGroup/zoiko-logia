# Standard composition request-size repair

Reported audit: `corr-4839e2ecfc4a`, for the UK VAT threshold question.
A read-only inspection found successful safety screening, three eligible
registered sources and sufficient retrieval confidence. Composition failed
with `provider_request_too_large` after approximately 380 ms. The final
execution record had one completed supporting call (913 tokens) and no
unreconciled token reservation. Under the current budget implementation,
that is consistent with the answer failing the local input-size preflight
before an answer-generation transport call. The request was not a domain
or safety refusal. It used the standard composition path, not the agent loop.

The standard Groq adapter carried 10,997 characters of system instructions.
The standard grounded prompt repeated extensive domain/formatting guidance.
Sources, history, registered passages and request-specific instructions were
added on top. The configured request allowance was 8,000 estimated tokens.
Thus a short user question could exceed the allowance internally.

The standard adapter now uses compact composition instructions derived from
the compact domain and evidence policy, adapted to its actual tools. It does
not tell the standard model to use an unavailable calculator or search tool.
The production grounded prompt also uses the compact evidence format for
standard composition. Reference identifiers and source text remain supplied;
the instructions preserve domain boundaries, untrusted-data handling,
verification limits, partial answers and honest missing-information guidance.
Legacy prompt builders remain available to their other callers.

An illustrative offline comparison with the same three source excerpts
changed the local input estimate from 10,932 to 4,688 tokens before history
and request-specific additions. These are estimates for a constructed
fixture, not measurements of the reported provider payload or billing.
The regression also exercises three excerpts with conversation history and
checks the remaining completion allowance and reference identifiers.

Focused request-size, execution and context checks: 38 passed. Full offline
backend suite: 3,203 passed, 21 skipped, 2 expected failures and 132 warnings.
No Groq calls,
provider changes, credential changes or database writes were made. Live
answer correctness and real provider token counts remain unverified.
Exceptionally large evidence sets can still exceed a finite allowance;
this repair removes duplicated instructions rather than increasing limits.
