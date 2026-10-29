# Pipeline audit and repairs — 27 October 2026

## Evidence inspected

Read 88 existing audit events in a read-only database transaction for the four reported correlations. No tenant records were changed. The local API uses this workspace with automatic reload.

| Correlation | What the audit actually showed |
| --- | --- |
| `corr-f2583aabbbcf` | Three claims: one supported, one contradicted, one unresolved. Missing evidence alone does not justify changing the unresolved verdict to false. |
| `corr-d1cec0ecbb76` | Research ran, but release verification rejected unsupported statements and an explicit evidence-gap sentence. The primary search provider also reported exhausted quota. |
| `corr-a70f68de63e1` | Three searches returned 36 source entries before the request-size failure. The error summary incorrectly reported zero steps and tools. This was accumulated context, not a long user question. |
| `corr-5ef4721a89d9` | Retrieval, generation and release checks ran; generation hit its output limit. Standard retrieval silently capped coverage at two standards and did not map plain impairment to IAS 36. |

## Repairs

- Render research passages once, with stable reference identifiers. Compact only explicitly marked evidence sections before later model requests, preserving user inputs, calculations and tool-call protocol. Reserve useful output space within the configured request allowance.
- Reuse a validated semantic research plan for bounded retrieval and composition instead of repeatedly researching source-only requests. A failed planner retains the existing fallback.
- Fetch up to eight relevant standards concurrently, including all three topics in the reported IFRS comparison. Failed downloads expire after 30 seconds rather than persisting for a day. Preserve the correct accounting framework.
- Focus each standard's excerpts on its own topic; include its actual Objective paragraph when purpose is requested. Comparison cross-references previously displaced core evidence.
- Apply one elapsed-time budget across provider searches and retries. A slow retry must not discard an earlier usable result.
- Accept explicit non-numeric evidence-gap wording such as “the evidence does not detail …” without requiring a citation. Numeric assertions remain subject to verification.
- Retain actual agent step/tool counts on provider failure. Clear stale truncation flags only after an accepted, fully verified coverage repair; describe remaining incomplete output accurately.

These changes do not raise provider spending limits or exempt factual legal/accounting requirements from verification.

## Live verification and remaining gaps

Replayed the reported ordinary research questions through real planning, retrieval, model generation and release checks. Persistence and the governed source library were isolated with existing test seams; no tenant writes occurred. These are pipeline replays, not authenticated browser acceptance tests.

- Audit plan: returned a substantive plan covering coordination, correspondence, documents and exposure in 24 seconds, without a request-size error. Optional guidance is separated from unresolved legal/accounting requirements; status remains partial.
- IFRS comparison: official IFRS 16, IAS 36 and IAS 37 purpose evidence now survives in the answer. The final replay remained partial because documentation/comparison detail did not all pass verification. It did not report the original request/output-size failure. This is improvement, not full acceptance of the question.
- Tax comparison: still not answered in the final replay. The configured primary search key returned HTTP 432 for exhausted quota and backup evidence did not establish a releasable answer. Restoring provider access remains an external dependency.

The claim review's unresolved royalty assertion remains unresolved; the system must not infer falsity merely from absent evidence.

Runtime `/health/ready` returned HTTP 200, and `/health/version` reported the same application-source hash as the workspace. Regression tests cover 36 long sources across three searches, preserved references and arithmetic, output space, planner-context isolation, publisher recovery, three-standard coverage, purpose evidence and slow fallback retries.

Final backend suite: **4,885 passed, 75 skipped, 22 expected failures**. `git diff --check` passed.
