# Kriton offline efficiency review — 19 October 2026

This review and its tests use simulated model responses. No live model
evaluation was run and no Groq or other provider tokens were requested.

## Changes

- Reduced the default cumulative agent allowance from 150,000 to 64,000
  tokens (`AGENT_MAX_TOKENS`). Explicit environment overrides still apply.
- Added a 4,096-token output limit per model request, configurable through
  `AGENT_MAX_COMPLETION_TOKENS`. This includes model reasoning tokens.
- Normal agent steps, forced final answers, and no-tools recovery now share
  one usage budget. Recovery previously bypassed token accounting.
- Check the prompt and remaining allowance before requesting a generation;
  clamp output to the remaining allowance. When no answer generation fits,
  return already verified calculations and an explicit incomplete status.
- Reserve allowance before sending a request. Missing usage reports,
  cancellation, and failed generations cannot allow unaccounted retries.
  Provider-reported token usage replaces reservations when available.
- Disable SDK automatic retries for the agent client. The agent's bounded
  recovery logic controls subsequent requests.
- A duplicate tool call points to the earlier result instead of repeating
  the full payload in the conversation. The original result remains present
  for evidence and calculations.
- Mark output truncated by the model's token limit as incomplete.
- Audit records and agent evaluation reports distinguish total accounted
  tokens, estimated reservations, and generation-call count.
- Default tests remove real model credentials. A transport guard fails any
  accidental Groq SDK request before it reaches the network. Tests that
  exercise provider behavior supply mocks. Live tests remain opt-in.

## Limits of these controls

Prompt preflight uses a conservative UTF-8 byte allowance with protocol
headroom, not an exact model tokenizer. It can stop early, especially for
large documents or non-English input. Actual provider usage is authoritative
when returned; prompt estimation cannot guarantee the provider's final bill.
Input evidence is not silently truncated to fit the allowance.

The cumulative allowance applies to the agent loop and its own final and
recovery calls. Separate risk-classification, planning, verification, and
non-agent completion paths are outside that allowance. The optional monetary
cap still requires configured pricing; no provider prices or billing limits
were guessed or changed.

Offline tests verify calculations, budget enforcement, duplicate handling,
timeouts, evidence preservation, source checks, follow-ups, and incomplete
answer reporting. They cannot establish the intelligence or writing quality
of live model answers. Output limits and conservative input estimates may
require tuning for complex tasks when explicitly authorized live evaluation
becomes available. No deployment was performed.

## Verification

Run the deterministic suite without live model access:

```sh
cd backend
RUN_LIVE_LLM_TESTS=0 python3 -m pytest -q
```

`tests/test_agent_efficiency.py` specifically checks prompt preflight,
remaining output allowance, absent usage, failure reservations, monetary
preflight, final/recovery accounting, preservation of verified work,
duplicate context, disabled SDK retries, blocked offline transport, and
honest output-truncation status.

Final result: **3,112 passed, 21 skipped, 2 expected failures** in 50.13
seconds, including 12 efficiency checks. The suite emitted 124 test warnings,
primarily from existing asynchronous database mocks. Python compilation and
`git diff --check` also passed.

## Follow-up: provider request-size limit

The manually reported request `corr-eb0edccbf225` reached Groq, which returned
HTTP 413: 12,437 requested tokens against an 8,000 TPM allowance. This is
distinct from the earlier account-spending block. No live model call was
made during diagnosis or regression verification.

The agent now uses a compact system prompt and grounded prompt instead of
repeating the standard composer's domain examples and visual-format schemas.
Supplied-figure calculations expose calculation tools without unrelated
lookup definitions. The full user question and applicable evidence are
preserved. Hyphenated current-year labels in supplied period comparisons and
explicit currency declarations no longer incorrectly request live lookups.

`AGENT_MAX_REQUEST_TOKENS` defaults to 8,000. Generated output is bounded by
that allowance minus an input estimate and protocol margin. This per-request
estimate is separate from the cumulative 64,000-token agent allowance and
does not enforce an account-wide rolling TPM limit across concurrent users.
Actual provider tokenization and other traffic can still affect acceptance.
An HTTP 413 now produces a specific size-limit message without repeating the
same request through standard composition.

Updated verification: **3,144 backend tests and 212 frontend tests passed**;
TypeScript, relevant frontend lint, and `git diff --check` passed. The backend
suite also reported 21 skips, 2 expected failures, and 130 test warnings.
The reported manufacturing question has an offline production-assembly test
covering its retained input, calculator-only tools, and estimated request
allowance. Live answer quality remains for the user's manual verification.
