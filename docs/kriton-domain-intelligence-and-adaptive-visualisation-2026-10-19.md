# Kriton — domain intelligence, reliability and adaptive visualisation

19 October 2026. Local implementation and isolated validation only.

The confirmed gaps were in intent/input recognition, missing deterministic workflows, revision handling and chart semantics. A paid model key does not repair these stages. This change extends the existing calculation, conversation-state, visualisation and audit paths; it does not add another prompt/router/model pipeline or enable a shadow planner.

No live Groq or other provider requests were made. No deployment, production configuration change, shared-database write, commit or push was performed. Existing working-tree changes and original benchmark files/reports were preserved.

## Confirmed findings and changes

### Depreciation

The supplied informal machine question fell through the calculation-intent guard because it did not contain one of the recognised calculation verbs. The depreciation parser also lacked “lasts 6 years” and explicit “no resale value”, and the output only supported annual depreciation.

The existing engine now recognises that straight-line request, retains explicitly supplied zero residual value, reads the useful life, and produces both requested periods. For £24,000, six years and zero residual value:

- Annual: (£24,000 − £0) ÷ 6 = £4,000.
- Monthly: £4,000 ÷ 12 = £333.333…; display £333.33.

An absent residual value remains missing. Invalid cost/residual combinations and conflicting currencies do not produce a successful calculation. A zero useful life produces an undefined result rather than an invented amount.

### Bank reconciliation

No deterministic bank-reconciliation workflow existed in the inspected engine; the synthetic numerical case depended on model composition and failed when that provider was unavailable. This does not prove the exact cause of an earlier live bank response: no exact historical bank example was available in the supplied transcript inspected during this phase.

The existing engine now supports explicitly labelled, positive bank/cash-book balances and the listed timing/ledger adjustments when the user explicitly states that there are no other reconciling items:

| Side | Calculation | Adjusted balance |
| --- | --- | --- |
| Bank statement | £12,000 + £1,500 deposits in transit − £700 outstanding cheques | £12,800 |
| Cash book | £12,600 − £100 bank charges + £300 interest received | £12,800 |
| Difference | £12,800 − £12,800 | £0 |

The adjustments are not applied to both sides. Changing the cash-book balance to £12,500 leaves a £100 unreconciled difference; no balancing plug is introduced. Repeated balance versions require selection. Conflicting currencies, additional unknown monetary adjustments, overdrafts, bank errors and other unsupported shapes do not receive a verified answer from this narrow workflow. Zero difference establishes arithmetic agreement, not the accuracy of bank records or authorisation to post a journal.

### FIFO and periodic weighted average

These workflows also lacked a deterministic route in the inspected code. The new regression is a synthetic numerical case, not a recovered historical FIFO response.

The existing engine now accepts explicitly ordered cost layers with periodic valuation and the stated condition that all purchases precede the only sale. For 100 opening units at £10, 200 purchased units at £13 and 180 sold:

| Method | COGS | Closing inventory |
| --- | --- | --- |
| FIFO | 100 × £10 + 80 × £13 = £2,040 | 120 × £13 = £1,560 |
| Periodic weighted average | 180 × (£3,600 ÷ 300) = £2,160 | 120 × £12 = £1,440 |

Both conserve £3,600 total cost. Tests also cover zero sales, sales within the first layer and complete depletion. Mixed currencies, overselling, returns/freight adjustments, duplicate opening layers and interleaved sales are not silently treated as this supported shape. Perpetual/moving-average transaction ledgers remain outside this new deterministic workflow.

### Changed-inventory follow-ups

The existing handler found the original statement and applied a single correction; a second correction could discard the first revision. It now replays the recorded user corrections in order, modifies closing inventory only and retains the source location of each input. An unrelated later financial task still stops backward baseline selection.

For the supplied wholesale statement, £95,000 closing inventory overstated by £10,000 becomes £85,000. A subsequent £2,000 understatement correction makes the active figure £87,000, not £97,000. COGS is then £568,000, operating profit £146,000 and finance costs remain £9,000. The existing first-correction case remains COGS £570,000, OP £144,000 and PBT £135,000.

### Structured task state and provenance

The existing tenant/user/conversation-scoped JSON snapshot now retains the current intent, calculation family, figure version/query ID, referenced-input flag, typed inputs and their locations, formula dependencies, derived outputs, assumptions/limits, clarification reason and requested section names. Final response completeness, outcome, remaining limitations and chart ID are saved after response validation. Existing numerical facts retain their period/scenario identity where supported.

This state describes the existing execution; it does not grant evidence authority to conversation text or change the shadow planner into an execution authority. It is not a universal semantic parser for arbitrary financial reports. Exact source-turn IDs for every historic input and independent per-section semantic completion are not established by these descriptive fields.

Calculation audit events now distinguish current-query inputs from mixed/history inputs. The durable answer receipt includes the selected chart type, a hash of its dataset, source IDs, formula IDs and the associated calculation hash. The HTTP regression recomputes the dataset hash, checks persisted final task status, and verifies the existing audit-chain hashes.

### Adaptive visualisation

The calculation visualiser previously required an explicit chart request and plotted compatible-looking amounts without distinguishing comparison purpose. The frontend offered a line view for any bar dataset, even unordered accounting categories.

Changes use the existing renderer contract:

- Validated current/previous or original/revised profit comparisons can select grouped bars without a separate chart instruction. FIFO/weighted-average comparisons use the same grouped renderer.
- Requested income-statement waterfalls use net sales and signed cost/expense movements only when those components reconcile exactly to the verified subtotal. The existing waterfall renderer required no new rendering engine. The uncorrected wholesale bridge ends at £145,000 PBT.
- Pie/donut composition requires non-negative parts that reconcile to the total. Monetary unit costs are excluded from comparisons of total amounts. Annual/monthly depreciation is presented as a table rather than comparing different time bases in a chart.
- A line view is offered only for an ordered, unique temporal axis with at least three points. Waterfall movements cannot be switched into an ordinary line. Switching valid views reuses the original dataset without mutation or refetch.

Existing line, scatter, stacked/grouped, composition and other governed visual builders remain available on their established data paths. This phase did not add arbitrary scatter observations, fabricate missing time-series data, enable stacking of overlapping profit subtotals or implement new chart families. Unsupported requested chart structures disclose the limitation and retain the calculation table.

### Provider failures and long reports

Existing request-budget, output-truncation and typed provider-failure paths were exercised again through the authenticated HTTP route. The long-report tests cover a scripted complete response, follow-up recalculation, request-size failure, timeout exception, provider failure and a genuine scripted SDK `finish_reason=length` response. Verified calculations survive incomplete composition; the result is not labelled complete.

No new provider-recovery fix was justified by these offline tests. A scripted successful response is not evidence that the paid live model will generate it. Request-size, provider, retrieval and tool failures still require operational diagnosis when encountered live. The existing governed source eligibility and citation checks remain the authority for rules, standards, tax and current-data requests.

## Exact change scope

[Scoped review patch](investigations/kriton-domain-intelligence-2026-10-19/verified-changes.patch) compares against the start of this phase, excluding unrelated pre-existing edits.

| File | Change |
| --- | --- |
| `backend/app/orchestration/calculations/engine.py` | Depreciation recognition/periods; bank reconciliation; periodic inventory; currency consistency checks |
| `backend/app/orchestration/calculations/inventory_statement.py` | Ordered inventory revisions and correct input locations |
| `backend/app/orchestration/calculations/visuals.py` | Verified-data gate, comparisons, waterfall bridge and compatible units |
| `backend/app/orchestration/conversation_memory.py` | Descriptive task state in existing scoped snapshots |
| `backend/app/orchestration/service.py` | Persist final task completion and forward calculation input provenance |
| `backend/app/orchestration/audit_events.py` | Per-input source metadata |
| `backend/app/orchestration/router.py` | Chart/calculation provenance in the existing durable receipt |
| `frontend/components/visualization/charts/engineRouting.ts` | Semantically valid view alternatives |
| `frontend/components/visualization/charts/ChartRenderer.tsx` | Use those alternatives |
| `backend/tests/test_live_router_defects.py` | Mark the existing successful chart fixture as verified, matching the strengthened production contract |
| `backend/tests/test_domain_intelligence_http.py` | Five real-route tests, seven requests |
| `backend/tests/test_domain_intelligence_calculations.py` | Independent arithmetic, invalid/ambiguous input and chart-provenance regressions |
| `frontend/tests/chart-view-semantics.test.ts` | Valid alternatives and dataset preservation |

The installed Next.js `use client` guide was read before frontend edits. No app routing or framework convention was changed.

## Validation and evidence

**Final results:** 3,277 backend tests passed, 22 skipped, two existing expected failures, zero failures (56.58 seconds; 140 warnings). The final targeted suite passed 45 tests (6.51 seconds). Frontend: 216 tests passed across 46 files; final focused chart checks: 26 passed. TypeScript: exit 0. Whitespace and reverse applicability of the scoped review patch both passed. The 22 skips comprise 18 PostgreSQL integrations, two live-model tests, one missing OCR dependency and the opt-in benchmark test, which was run separately.

Final counts, timings and benchmark details are in [validation summary](investigations/kriton-domain-intelligence-2026-10-19/validation-summary.json). The final targeted run includes the new domain regressions and the existing A–G HTTP suite.

The HTTP harness uses the real application route, RBAC user lookup, task/context resolution, calculation path, audit persistence and receipt logic against isolated SQLite sessions. External HTTP/DNS are blocked. Token verification and provider responses are synthetic; production startup is not executed. All correlations refer to temporary isolated ledgers, not the production audit-replay UI.

[Before traces](investigations/kriton-domain-intelligence-2026-10-19/http-traces-before.json) preserve the three initially failing requests. [After traces](investigations/kriton-domain-intelligence-2026-10-19/http-traces-after.json) include the repaired cases and A–G failure/completion checks. Each includes the request/conversation, task context, selected history, model boundary, calculation, response and persisted audit events. The exported model request sizes are characters and UTF-8 bytes, not measured provider tokens. All reported latency is synthetic local latency.

### Unchanged original benchmark

All 80 original cases were replayed with the unchanged scorer and unavailable synthetic external services. The scorer reports **48 passed / 32 failed**, with actual outcomes **7 answered, 63 unavailable, 3 clarification required, 5 refused and 2 rejected**. Of the 48 scorer passes, 33 were unavailable responses. These weak expectations do not establish answer quality and were deliberately not rewritten.

The benchmark harness passed its execution/integrity check in 83.02 seconds; that is not a quality pass. [Per-case results](investigations/kriton-domain-intelligence-2026-10-19/original-benchmark-offline.json) retain the failures. All 102 original evaluation/report JSON hashes remain unchanged: [manifest](investigations/kriton-domain-intelligence-2026-10-19/baseline-sha256.json).

### Reproduction commands

From `backend`:

```sh
RUN_LIVE_LLM_TESTS=0 .venv/bin/pytest -q -rxXs
RUN_LIVE_LLM_TESTS=0 KRITON_TRACE_DIR=/private/tmp/kriton-domain-after .venv/bin/pytest -q tests/test_domain_intelligence_calculations.py tests/test_domain_intelligence_http.py tests/test_root_cause_http.py
RUN_LIVE_LLM_TESTS=0 RUN_OFFLINE_ORIGINAL_BENCHMARK=1 KRITON_TRACE_DIR=/private/tmp/kriton-domain-benchmark .venv/bin/pytest -q tests/test_original_benchmark_offline.py
```

From `frontend`:

```sh
npm test -- --run
./node_modules/.bin/tsc --noEmit --incremental false
```

## Acceptance limits and remaining blockers

The tested numerical cases, ordered inventory corrections, reconciliation directions, chart selection, dataset-preserving switching and persisted provenance now pass locally. Existing isolation/evidence controls were not removed or bypassed. No licensing, RLS policy, source-eligibility, database digest, migration or production activation change is part of the scoped patch.

PostgreSQL integration checks are skipped without an isolated PostgreSQL instance, so actual PostgreSQL RLS and database-computed passage digests are not runtime-verified here. Live tax/standard/current-data retrieval, paid Groq limits, live reasoning quality and production memory activation remain unverified. The two existing non-English Austria expected failures remain. No claim is made that every cash-flow, balance-sheet, forecasting or arbitrary multi-part report is covered by a deterministic workflow.

Production rollout and live-provider evaluation have not been proposed or executed as part of this change. They require separately authorised infrastructure and usage budgets; the local results do not establish production readiness.

## Final isolated correlations

Median HTTP latency: 69.24 ms; maximum: 188.26 ms. These figures exclude any live inference or network latency.

| Case | Correlation ID | Outcome | Milliseconds |
| --- | --- | --- | --- |
| A-F-unrelated | corr-237b5114364d | answered | 76.41 |
| A-fresh | corr-a8aa2ca5e394 | answered | 68.94 |
| A-multiturn | corr-e8afd28f11bd | answered | 25.59 |
| A-replay-first | corr-bce708318993 | answered | 69.84 |
| A-replay-second | corr-bce708318993 | answered | 4.03 |
| B-minimal | corr-8c514454985e | answered | 69.24 |
| C-baseline | corr-83b4da2617b0 | answered | 135.59 |
| C-corrected | corr-0fc81bfcf51f | answered | 20.21 |
| D-fresh | corr-a2a6cafeba96 | answered | 71.77 |
| D-new-task | corr-9d734dabea08 | answered | 20.66 |
| D-unrelated-baseline | corr-0e36faf3d01a | answered | 73.55 |
| E-durable-followup | corr-5d1a3d204970 | answered | 20.6 |
| E-other-tenant | corr-d3b5c06fc334 | clarification_required | 13.67 |
| F-after-fix | corr-944be4fb60ff | answered | 71.2 |
| F-multiturn | corr-53b0716cb4fa | answered | 21.79 |
| G-followup | corr-858cef0f834a | answered | 24.34 |
| G-provider-failure | corr-5a4eadfc1e9b | answered | 118.58 |
| G-real-length-response | corr-17e701e1993a | answered | 96.34 |
| G-scripted-complete | corr-6de7b64412db | answered | 160.18 |
| G-size | corr-3595e8060725 | answered | 188.26 |
| G-timeout | corr-cfa0262b2688 | answered | 102.94 |
| G-truncation | corr-a96f8ec0c56d | answered | 104.04 |
| bank-reconciliation | corr-008b9bf4061b | answered | 67.85 |
| chart-audit | corr-0817fd639052 | answered | 67.18 |
| depreciation-natural | corr-396fa8dc73e3 | answered | 84.11 |
| inventory-revision-base | corr-80a1b1fe7328 | answered | 68.57 |
| inventory-revision-first | corr-859387c97f04 | answered | 19.65 |
| inventory-revision-second | corr-b9ac013b14a8 | answered | 19.27 |
| inventory-two-methods | corr-eced26ef61bb | answered | 123.94 |
