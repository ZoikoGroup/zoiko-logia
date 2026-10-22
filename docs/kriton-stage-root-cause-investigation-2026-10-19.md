# Kriton — first-failing-stage investigation

19 October 2026. Local code and isolated test infrastructure only.

**The attachment provides expected results, but omits the original messages and complete inputs for the new income statement, bank reconciliation, £4,560 inventory case and six-section management report. Those exact acceptance cases remain unverified.** Their original questions, failed responses and request/correlation IDs were requested. Missing inputs were not reverse-engineered from expected outputs.

The investigation reproduced specific mechanisms using previously supplied messages and existing explicit test fixtures. Confirmed defects were fixed in their existing components. These mechanism regressions are not substitutes for the missing original cases or evidence that production is fixed.

No Groq or other live provider calls, production configuration changes, deployments, shared-database writes, commits or pushes were made. Existing Git changes were preserved.

## Scenario findings

| Requested case | Earliest proven divergence | Result and limit |
| --- | --- | --- |
| A: new income statement | Not established for the missing original payload. Separately, `splitQuestions` discarded shared non-question prose before submission. | Client regression proves that a paragraph containing figures can be dropped when numbered deliverables are split. Fixed before the reasoning/retrieval stage. It does not prove this happened in the missing £1.2m case. |
| B: inventory replacement | For a known complete statement, a from/to request loaded the stored history, then `_standalone_with_figures` discarded it because the two monetary amounts looked independent. The inventory handler also recognised only over/understatement deltas, not explicit replacements. | Fixed contextual recognition and replacement parsing. Known £95,000 → £85,000 case returns COGS £570,000, OP £144,000, PBT £135,000. The new £160,000 → £130,000 case requires its original statement. |
| B: correction after rejected version | A version-mismatched revision was correctly rejected, but its raw user text was replayed later as though applied. | Rejected revisions remain in the scoped ledger but are excluded from calculation history, including duplicate client replay. A subsequent valid revision now succeeds. |
| C: supplied GST | No retrieval block reproduced for the exact earlier GST request. It already uses the deterministic route with no model or retrieval calls. | Correct ₹2,280,000 net sales, ₹410,400 output GST, ₹1,020,000 net purchases, ₹183,600 input tax amount and ₹226,800 payable. New explicit ledger differences are ₹0 each. |
| C: arithmetic versus legal claims | The calculator appended an unsourced VAT-specific recoverability assertion, including to Indian GST arithmetic. | Replaced with a scoped statement that arithmetic does not establish legal eligibility/recoverability. An added legal-eligibility request still enters retrieval and remains partial when evidence is unavailable. No evidence policy bypass. |
| D: new bank reconciliation | No exact original payload or failed response supplied. | Current implementation adjusts the bank side by **adding deposits in transit and subtracting unpresented cheques**. £88,350 + £5,800 − £7,000 = £87,150 is consistent with that direction. This identity is not an end-to-end validation of the omitted cash-book adjustments. No speculative bank fix was made. |
| E: inventory completion | In the existing complete fixture, deterministic output construction omitted closing units and explicit cost-reconciliation results. No model call occurred. | Added both methods' closing units, total available cost, formulas and reconciliation differences. Existing fixture reconciles to £3,600. The missing £4,560 layer/sale payload was not invented. |
| F: management report | Actual six-section question and production exception absent. Controlled HTTP replay proved that timeout normalisation lost its specific identity after standard fallback. | Added a safe `provider_timeout` classification while preserving the existing `TimeoutError` recovery contract. Existing bounded final-answer recovery remains; no fresh standard-composition fallback follows an exhausted typed timeout. Actual six-section completion remains unverified. |

### Client-to-server boundary

The page calls `splitQuestions(trimmed)` before creating `submittedQuery` and passing it to `askKritonStream`. The old helper only protected outside paragraphs containing a question mark. A data paragraph without `?` was discarded, leaving independent requests such as “Calculate net sales” without its figures.

The fix preserves the whole message whenever it contains shared prose, data, tables, code or instructions outside the numbered questions. Only purely structural labels, such as “Questions” or the existing follow-up heading, may be discarded when splitting independent lists. It does not silently truncate a longer combined message or enlarge service limits.

Three new client checks failed before the fix; all four pass afterward. The streaming API test intercepts `fetch` and checks the exact serialized `query`. It does not use a live browser/server session. Existing independent-list behaviour also passes the legacy split-question checks.

### Inventory context and version handling

The from/to mechanism was isolated further by restoring only the original contextual classifier in a temporary pytest plugin. With the current replacement calculator still present, the request failed again: stored history was loaded, then excluded from processing. That counterfactual replay identifies the classifier as an earlier failure than calculation. Its trace is labelled separately; source files were never reverted.

The existing parser now recognises explicit `closing inventory to …` and `closing inventory from … to …` alongside over/understatement adjustments. A supplied starting value must match the active version. Only closing inventory changes; other expenses, purchases and finance costs retain their values and source locations.

A rejected version is not applied later. The regression follows the known £95,000 baseline to £85,000, rejects a stale £95,000 starting version, and then accepts £85,000 → £80,000. It returns COGS £575,000 and PBT £130,000. The rejected user message remains available in the audit/history ledger; no ledger record is deleted to achieve this.

### GST evidence boundary

The pure arithmetic test configures governed retrieval to fail if called, then verifies that retrieval was never invoked. It calculates from the exact earlier supplied figures and assumptions and makes no model request.

The legal variant asks whether the purchases qualify for input tax credit under Indian law with an official source. That variant does invoke governed retrieval. When retrieval/model service are unavailable in the isolated harness, verified arithmetic is retained, but the response remains partial. Calculated input tax is not presented as independently proven statutory eligibility.

### Inventory completeness

The supported periodic workflow now emits:

- Total available inventory cost, with the supplied layer formula.
- FIFO COGS, closing units, closing inventory and cost-reconciliation difference.
- Weighted-average unit cost, COGS, closing units, closing inventory and cost-reconciliation difference.

Weighted-average closing cost is calculated as available cost less COGS so finite Decimal division does not introduce a spurious reconciliation residual. Counts and values retain distinct units. The existing supported-shape restrictions are unchanged; an omitted £4,560 source dataset cannot be reconstructed uniquely from its total.

### Provider failure classification

Before the timeout fix, a synthetic timeout produced `TimeoutError` at the provider boundary, followed by standard composition and final `model_provider_unavailable`. Four synthetic failed generations were captured. After the fix, the audit retains `provider_timeout`; the existing initial and reserved final-answer attempts are bounded to two, and `agent_completed.fell_back` is false.

`ProviderTimedOut` remains a `TimeoutError`, preserving cancellation, verified-work recovery and time-budget semantics. SDK timeouts, httpx timeouts and native timeouts receive the same safe provider code. No raw provider error body or credential is added to the user-facing message.

Controlled traces distinguish:

| Mechanism | Evidence |
| --- | --- |
| Request too large | Typed `provider_request_too_large` |
| Output truncation | Scripted actual SDK choice `finish_reason=length`, then `provider_response_incomplete` |
| Provider timeout | Synthetic timeout at provider boundary; final audit `provider_timeout` |
| Generic service failure | Synthetic `RuntimeError`, final `model_provider_unavailable`; not reported as output truncation |
| Retrieval failure | Explicit unavailable governed retrieval in the legal-eligibility case; partial response |

These are controlled failure tests, not a diagnosis of the missing live management-report failure. Request character/UTF-8 byte sizes and configured completion allowances are exported with each synthetic model request; they are not measured paid-provider token usage. Injected timeouts do not measure a real provider deadline.

## Changed files and minimal patch

[Scoped patch](investigations/kriton-stage-investigation-2026-10-19/verified-changes.patch) compares against the beginning of this phase and excludes unrelated existing changes.

| File/function | Change |
| --- | --- |
| `frontend/lib/kriton-conversation.ts::splitQuestions` | Preserve shared context before serialization |
| `backend/app/orchestration/service.py::_looks_like_contextual_follow_up` | Recognise explicit inventory revisions before clearing history |
| `backend/app/orchestration/conversation_memory.py::_new_financial_context`, `merge_history` | Preserve revision context; exclude validation-rejected revisions from applied calculation history |
| `backend/app/orchestration/calculations/inventory_statement.py::_inventory_revision`, `inventory_followup` | Parse replacements and validate active version |
| `backend/app/orchestration/calculations/engine.py::vat_amounts` | Conditional eligibility caveat and explicit ledger differences |
| `backend/app/orchestration/calculations/engine.py::periodic_inventory` | Closing units and complete cost reconciliations |
| `backend/app/domains/model_gateway/errors.py` | Specific timeout classification with compatible timeout inheritance |
| `backend/tests/test_vat_clarification.py` | Existing caveat assertion now checks the conditional eligibility boundary rather than requiring an unsupported legal statement |
| `backend/tests/test_stage_investigation_http.py` | Seven HTTP regressions using existing known inputs |
| `backend/tests/test_stage_timeout_classification.py` | Three timeout-type classification checks |
| `frontend/tests/input-propagation-boundary.test.ts` | Four submission-boundary checks |

No new generic prompts, routers, calculation engines, evidence pipelines or memory stores were added. No shadow planner feature was activated. The installed Next.js client-component guide was consulted; no framework API change was needed.

## Trace coverage and validation

Final validation: **3,287 backend tests passed, 22 skipped, two existing expected failures, zero failures** (57.80 seconds; 140 warnings). Targeted checks: **177 passed** (8.71 seconds). Frontend: **220 passed** across 47 files (13.17 seconds). TypeScript: exit 0. Legacy split-question checks, whitespace validation and reverse applicability of the scoped patch passed.

The skips comprise 18 PostgreSQL integration checks, two live-model checks, one missing OCR dependency and the opt-in original-benchmark replay. Expected failures remain the existing native-language Austria aliases.

[Before traces](investigations/kriton-stage-investigation-2026-10-19/http-traces-before.json), [after traces](investigations/kriton-stage-investigation-2026-10-19/http-traces-after.json), [classifier counterfactual](investigations/kriton-stage-investigation-2026-10-19/http-traces-classifier-counterfactual.json) and [validation summary](investigations/kriton-stage-investigation-2026-10-19/validation-summary.json) preserve the evidence.

The harness runs the actual authenticated application route with synthetic token verification and a real RBAC user lookup, isolated SQLite sessions, actual task/context selection, calculations, retrieval/evidence checks, response assembly and durable audit/receipt logic. It verifies tenant identities and persisted audit payload/chain hashes. External DNS/HTTP/provider transports are blocked. Production lifespan and actual PostgreSQL are not executed.

Each raw trace includes the exact submitted message and conversation, loaded history and snapshots, task context, model/tool boundary, available calculations, validation status, final response and persisted audit. An arithmetic route deliberately has no retrieval query or evidence search. Historical correlations belong to temporary isolated ledgers, not the production audit-replay UI.

Validation encountered and resolved seven compatibility failures in the first broad backend run: six timeout-contract/recovery checks and the former VAT-caveat assertion. They were not treated as model-quality failures. The final counts and raw command logs are preserved in the linked summary.

### Commands

From `backend`:

```sh
RUN_LIVE_LLM_TESTS=0 KRITON_TRACE_DIR=/private/tmp/kriton-stage-after .venv/bin/pytest -q tests/test_stage_investigation_http.py tests/test_stage_timeout_classification.py tests/test_root_cause_http.py tests/test_domain_intelligence_http.py tests/test_domain_intelligence_calculations.py tests/test_agent_efficiency.py tests/test_agent_loop.py tests/test_operating_forecast_answerability.py tests/test_verified_work_fallback.py tests/test_vat_clarification.py tests/test_conversation_memory.py
RUN_LIVE_LLM_TESTS=0 .venv/bin/pytest -q -rxXs
```

From `frontend`:

```sh
npm test -- --run
./node_modules/.bin/tsc --noEmit --incremental false
node lib/__tests__/split-questions.mjs
```

All 102 original evaluation/report JSON hashes are checked unchanged in [the manifest](investigations/kriton-stage-investigation-2026-10-19/baseline-sha256.json). The original answer-quality benchmark was not rerun during this phase, and no new live-quality score is claimed.

## Remaining blockers

The original input messages, complete payloads, failed responses and identifiers are required before claiming acceptance for the new £1.2m income statement, its £160,000 → £130,000 follow-up, the £87,150 bank reconciliation, the £4,560 inventory case and the actual six-section report. Expected totals alone are insufficient evidence of what the frontend sent or which adjustments were supplied.

No bank implementation change or speculative purchase-return parser change was made without the corresponding source payload. If the new income statement reaches the backend intact, its input extraction and accounting dependencies still need to be traced before attributing that failure to retrieval or the model.

PostgreSQL RLS, database-computed passage digests, live source retrieval, live provider behaviour and production integration remain unverified. Existing tenant/source/licensing/security code paths were not bypassed; scoped local tests do not replace runtime PostgreSQL checks. No production readiness or permanent universal reliability claim is made.

## Final isolated request correlations

These are local synthetic timings: median 67.53 ms; maximum 179.16 ms. They do not measure live provider or production performance.

| Case | Correlation ID | Outcome | Milliseconds |
| --- | --- | --- | --- |
| A-F-unrelated | corr-7fd1486c4d84 | answered | 67.36 |
| A-fresh | corr-c865bfbfef0f | answered | 65.02 |
| A-multiturn | corr-a32bc6749da5 | answered | 21.77 |
| A-replay-first | corr-f6499b870d63 | answered | 65.71 |
| A-replay-second | corr-f6499b870d63 | answered | 3.8 |
| B-after-rejected-version | corr-5087629fbfe5 | answered | 18.62 |
| B-direct-change | corr-1a573a1be29c | answered | 20.53 |
| B-existing-baseline | corr-9072738c2159 | answered | 91.4 |
| B-from-to-baseline | corr-e69b613be03a | answered | 69.55 |
| B-from-to | corr-383628371727 | answered | 19.49 |
| B-minimal | corr-e42c5c673c1b | answered | 66.22 |
| B-wrong-version | corr-478e25bf6ce9 | clarification_required | 15.92 |
| C-baseline | corr-60d63c600877 | answered | 67.27 |
| C-corrected | corr-e8c6275fa2aa | answered | 19.21 |
| C-exact-existing-GST | corr-1baffbda198b | answered | 131.53 |
| C-legal-evidence | corr-d1ac4c05d636 | answered | 94.55 |
| D-fresh | corr-5f75969cbef2 | answered | 66.08 |
| D-new-task | corr-44ec60846ce8 | answered | 19.4 |
| D-unrelated-baseline | corr-d5a8df9180e7 | answered | 67.7 |
| E-durable-followup | corr-a86a527a6c7e | answered | 21.48 |
| E-existing-inventory | corr-37129399be00 | answered | 67.82 |
| E-other-tenant | corr-32eef7656443 | clarification_required | 12.15 |
| F-after-fix | corr-e2f6bb791b58 | answered | 68.03 |
| F-multiturn | corr-4eac3590a70d | answered | 19.94 |
| F-service | corr-4653177f7d5f | answered | 161.78 |
| F-timeout | corr-040b3a750ba2 | answered | 98.65 |
| G-followup | corr-62fee545b1ff | answered | 21.51 |
| G-provider-failure | corr-11d21585e407 | answered | 167.98 |
| G-real-length-response | corr-73639728a3ae | answered | 91.67 |
| G-scripted-complete | corr-418c3af71b6f | answered | 152.47 |
| G-size | corr-2262710f64f9 | answered | 96.01 |
| G-timeout | corr-613b0dfe2fba | answered | 96.45 |
| G-truncation | corr-531fccdf350a | answered | 179.16 |
| bank-reconciliation | corr-cc8f5307dda2 | answered | 72.18 |
| chart-audit | corr-c3ee02111733 | answered | 156.24 |
| depreciation-natural | corr-d060c1e2e00f | answered | 67.78 |
| inventory-revision-base | corr-b7c7fb4f2fec | answered | 69.9 |
| inventory-revision-first | corr-1d6ec9f75c99 | answered | 19.92 |
| inventory-revision-second | corr-9a3eaad78934 | answered | 19.5 |
| inventory-two-methods | corr-fc2272d57871 | answered | 159.73 |
