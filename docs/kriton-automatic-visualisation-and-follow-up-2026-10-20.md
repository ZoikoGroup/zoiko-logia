# Kriton: automatic visualisation and follow-up reliability

20 October 2026. Local implementation; no deployment or production configuration change.

The implementation extends the existing response planner, visual router, calculation services, conversation snapshots, renderer adapters and audit receipt. It adds no parallel answer engine, generic prompt layer or model calls. No Groq tokens were used. Existing Git changes were preserved.

## Implemented behaviour

### Current request and task integrity

- The exact received message is retained separately from internal glued-word normalisation. Its SHA-256 identifies the current message in the response/receipt; `query_received` retains the corresponding existing shortened hash. Historical context cannot replace this identity.
- The client sends its turn ID and request ID with the conversation ID. The server checks the request ID against the unscoped idempotency header; legacy clients receive the header ID as their request ID. A mismatch is rejected.
- Response metadata records independent, follow-up, correction or multi-part classification using the existing contextual rules. This descriptive classification does not activate the shadow planner or authorise tools.
- `CalculationTaskState` carries the calculation family, original inputs, active typed inputs, changed input names, assumptions and derived results. Root original inputs survive successive supported corrections. State is retained in the existing tenant/user/conversation-scoped snapshots.
- Prior input metadata is reused only for a compatible calculation family. A fresh independent request uses its current inputs. Existing one-variable inventory corrections and new-task isolation regressions remain protected.

A confirmed idempotency defect was also fixed: the router's receipt update replaced the service's hash-bound response envelope with an unhashed response. The update now preserves the request hash. The hash binds to the original message rather than its normalised spelling. A different message under the same key returns 409. Older responses lacking any request binding cannot safely be matched and also return 409 rather than silently replacing the current answer; submitting again with a new key resolves that legacy case. Existing no-hash internal callers remain compatible.

### Structured visualisation selection

`VisualizationIntent` is part of the existing visual router and is returned with the answer. It records the selected output type, reason, validated dataset/rows, x/y fields where meaningful, title, currency, units, periods, legend, explicit preference, confidence and fallback reason. The original typed `VisualizationSpec` remains the renderer contract; the decision does not create a second renderer or data source.

The rules now cover these existing paths:

| Request/data | Selection |
| --- | --- |
| One calculation | Working and result; no decorative chart |
| Income statement, reconciliation or inventory results | Labelled table and formulas by default |
| Supported profit/scenario/method comparison | Existing grouped bars when a chart adds a useful comparison |
| At least three complete, explicitly supplied monthly revenue/sales/profit/expense/cash-flow observations | Automatic line chart and a first-to-last change summary; no chart instruction required |
| Valid parts of one whole | Existing governed composition renderer |
| Reconciling signed financial movements | Existing waterfall renderer when requested and supported |
| Structured process/relationship evidence | Existing flow/graph builders and renderer adapters |
| Explicit text/table-only preference | Suppress automatic calculation charts |

Monthly summaries use only the supplied observations. Missing periods are not filled and no business cause is invented. Unsupported or misleading structures retain the existing fallback/evidence boundary.

Existing inline chart families remain supported for compatibility. Their validated payload is exposed as `renderer_payload` in the selection metadata, rather than incorrectly describing an inline pie/scatter/etc. chart as text. Common supplied line/bar/area-shaped datasets now also use the shared typed spec where it validates. This does not replace every established inline family with a new schema.

### Follow-up presentation changes

A validated source-free visual can be loaded from the authenticated caller's server-owned conversation snapshot. “Make it a bar chart” changes its presentation through the existing shared spec and validator; it does not ask the model to reconstruct figures from earlier prose. External-source visuals still require the normal evidence path.

The line-to-bar regression preserves all values, unit and period labels. The same conversation name under another tenant has no access to that dataset. An independent financial calculation stops an unrelated old chart from becoming the active visual.

Explicit visual preferences take precedence over saved browser defaults. An old “prefer table” or “use bars” preference cannot suppress a newly explicit line-chart request. Valid user-initiated view switching remains available afterward.

### Actual rendering and graceful failure

The React tests invoke the real Recharts renderer, obtain an SVG, switch a real line series to three bars and inspect the readable table for the exact 100/120/90 values and period labels. These tests mock container geometry/ResizeObserver, not the chart library.

A forced renderer exception exercises the actual error boundary and readable-table fallback. An unsupported engine also produces an explicit fallback message instead of a blank chart container. Fallback tables display units/currency. Blocked or unavailable localStorage no longer crashes the chart; in-memory preferences continue working.

The backend describes a validated renderable payload, not a claim that pixels were displayed. Actual client failures remain client-side render-failure telemetry and visible fallback messages; server completion cannot prove that a user's browser rendered successfully.

### Requested deliverables and completion

The existing coverage checker now emits structured deliverable statuses for explicitly named report sections, requested visual payloads and conclusively unfinished response/table structures. Numeric/citation/accounting validators remain separate and authoritative.

A report request with explicit sections reaches composition rather than being stopped after one arithmetic result. Missing requested sections add an explicit incomplete limitation and keep the response partial. A previously explicit partial/none state is not upgraded to complete just because a limitation string was absent. Verified work remains available when later composition fails.

This is bounded structural checking, not a claim of universal semantic report understanding. Supported section headings are matched by their requested names, with Markdown/numbering normalisation. Existing numerical claim verification, accounting calculations, source eligibility and jurisdiction checks still decide what may be released.

## Confirmed first-failing stages

| Regression | First incorrect stage | Fix |
| --- | --- | --- |
| Comparison returns a chart despite text/table-only instructions | Calculation visual selection ignored the preference | Apply the existing automatic-chart guard before choosing a chart |
| Supplied monthly line has only an inline block and no typed payload | Early supplied-chart response assembly | Translate the validated dataset into the shared spec where supported |
| Presentation-only follow-up needs a model/client answer reconstruction | Context selection lacks a persisted typed visual | Reuse the caller's validated server snapshot and validate the view change |
| Request/turn identifiers absent | Request schema and client submission | Add bounded correlation fields and consistent receipt metadata |
| Same key can replay a different original message | Receipt update removes the hash envelope | Preserve binding; reject mismatched/unbound replay |
| Successive corrections relabel the previous version as the original | Calculation-state assembly | Persist and reuse root original inputs separately from active inputs |
| A report can appear complete with an omitted section | Final completeness depends mainly on limitation strings | Check requested structured deliverables at final release |
| Chart crashes with inaccessible storage | Preference read before rendering | Guard storage access; retain session state |
| Render failure loses explicit currency in its fallback | Table rendering | Display the payload's unit/currency with the unchanged values |

## Validation beyond in-process tests

### Separate HTTP process, real JWT verification, PostgreSQL and RLS

Two opt-in integration tests run the actual app under a separate Uvicorn process over loopback TCP. They use locally signed RSA JWTs and a local JWKS server through the normal verifier, real RBAC lookup, normal request-time PostgreSQL sessions and a non-superuser/non-bypass application role. Authentication and database dependencies are not overridden.

The tests provision only a disposable database in a newly created temporary PostgreSQL cluster, using the existing production RLS setup functions. They verify:

- Invalid authentication returns 401.
- The actual HTTP response contains a typed monthly line chart.
- A follow-up becomes bars with the identical dataset.
- Another tenant cannot obtain that dataset through the same conversation ID.
- An independent £100/£60 task returns £40 gross profit, without the preceding £900,000 task's inputs.
- Direct application-role reads of conversation memory are restricted by PostgreSQL RLS.
- The role is neither superuser nor BYPASSRLS.
- Persisted audit payload and chain hashes recompute correctly, and receipt request metadata equals the delivered response metadata.

Five successful HTTP requests are captured, plus an invalid-token check. The cross-tenant data-less chart response remains explicitly partial; an `answered` envelope is not counted as a complete visual answer.

**Limits:** this is genuine out-of-process HTTP and database-policy testing, not a production deployment. Uvicorn runs with production lifespan/startup disabled after explicit test-only provisioning. JWTs/JWKS are local test identities, not a live Supabase project. External providers are blocked. Operational startup/migrations, production integrations and live answer quality remain unverified.

### Multi-process PostgreSQL source governance

The existing isolated PostgreSQL suite passed seven tests using separate worker processes and the non-bypass role. Coverage includes tenant separation with a warm cache, changed passage text/digests, withdrawn/replaced versions, revoked rights and public/private source changes. No source-governance, licensing, RLS policy or database passage-digest implementation was weakened.

The sandbox initially prevented PostgreSQL shared-memory/socket operations. The tests then ran with reviewed access solely to the temporary cluster. The local HTTP/JWKS workers and temporary PostgreSQL server were stopped after testing. No shared/production database was used.

### Suites and unchanged benchmark

Final commands, counts, timings and logs are in [validation summary](investigations/kriton-automatic-visualisation-2026-10-20/validation-summary.json).

The unchanged 80-case original offline benchmark reports **48 scorer passes and 32 failures**. Actual outcomes are **7 answered, 63 unavailable, 3 clarification-required, 5 refused and 2 rejected**. Thirty-three of the scorer's passes are unavailable responses, so that score is not evidence of strong live answer quality. The original scorer/cases were not altered to improve the number.

All 102 original evaluation/report JSON hashes remain unchanged: [manifest](investigations/kriton-automatic-visualisation-2026-10-20/baseline-sha256.json). [Per-case benchmark results](investigations/kriton-automatic-visualisation-2026-10-20/original-benchmark-offline.json) preserve the failures.

Ordinary backend command:

```sh
RUN_LIVE_LLM_TESTS=0 .venv/bin/pytest -q -rxXs
```

Targeted backend command:

```sh
RUN_LIVE_LLM_TESTS=0 KRITON_TRACE_DIR=/private/tmp/kriton-visual-traces .venv/bin/pytest -q tests/test_automatic_visual_integrity.py tests/test_root_cause_http.py tests/test_stage_investigation_http.py tests/test_audit_batch_and_idempotency.py
```

Original offline benchmark command:

```sh
RUN_LIVE_LLM_TESTS=0 RUN_OFFLINE_ORIGINAL_BENCHMARK=1 KRITON_TRACE_DIR=/private/tmp/kriton-visual-benchmark-final .venv/bin/pytest -q tests/test_original_benchmark_offline.py
```

Frontend commands:

```sh
npm test -- --run
./node_modules/.bin/tsc --noEmit --incremental false
```

The opt-in socket suite uses `RUN_SOCKET_HTTP_TESTS=1`, `SOCKET_TEST_ADMIN_URL`, `SOCKET_TEST_APP_URL` and `SOCKET_TEST_TRACE_DIR`; it asserts that its administrator URL points to the dedicated temporary `kriton_http` database before rebuilding a schema. The source-governance suite uses `PASSAGE_CACHE_PG_ADMIN_URL` and `PASSAGE_CACHE_PG_APP_URL`. These destructive test fixtures must only be pointed at disposable isolated databases. They were not run against application data.

## Files and review artifacts

[Scoped patch](investigations/kriton-automatic-visualisation-2026-10-20/verified-changes.patch) compares against the start of this phase and excludes unrelated pre-existing work.

Changed existing components:

- `backend/app/orchestration/schemas.py`: exact-message retention and additive response/request contracts.
- `backend/app/orchestration/service.py`: current-request metadata, calculation state, visual selection/reuse and final deliverable checks.
- `backend/app/orchestration/identifiers.py`, `router.py`: hash-preserving idempotency and matching durable receipts.
- `backend/app/orchestration/conversation_memory.py`: scoped typed visual/root calculation-state retention.
- `backend/app/orchestration/answer_coverage.py`: structured completion checks.
- `backend/app/orchestration/visualization/router.py`, `spec.py`: selection decision, validated presentation changes and explicit preference metadata.
- `backend/app/orchestration/calculations/schemas.py`, `visuals.py`: typed calculation state and preference-aware visual defaults.
- `backend/app/orchestration/chart_intent.py`, `supplied_charts.py`: guarded automatic monthly selection and existing-payload translation.
- `frontend/lib/api.ts`, `frontend/app/ask-kriton/page.tsx`: turn/request identifiers and explicit visual preference field.
- `frontend/components/visualization/charts/ChartRenderer.tsx`, `useChartPreferences.ts`, `DataTableView.tsx`: preference precedence, render/storage fallbacks and visible units.

New regressions/integration infrastructure:

- `backend/tests/test_automatic_visual_integrity.py`
- `backend/tests/test_visual_socket_http.py`
- `backend/tests/socket_http_worker.py`
- `frontend/tests/real-chart-rendering.test.tsx`

[In-process traces](investigations/kriton-automatic-visualisation-2026-10-20/http-after.json), [real socket traces](investigations/kriton-automatic-visualisation-2026-10-20/http-socket-traces.json), PostgreSQL and frontend logs are preserved beside the patch. Correlations in these artifacts belong to isolated test ledgers, not the production audit-replay UI. Timings are local/synthetic and are not production inference benchmarks.

## Remaining review limits

The previously omitted original £1.2m income statement, £4,560 inventory data and actual six-section management-report payloads still cannot be reconstructed from expected totals alone. No acceptance claim is made for those exact unavailable messages. Existing supplied arithmetic, correction, GST, source/jurisdiction and long-response failure regressions run unchanged.

Real SVG rendering was verified for line/bar views and forced chart failure. This does not establish pixel/layout correctness for every ECharts, graph, Mermaid or flow engine on every browser. Existing adapters remain in use. Structural report checks do not prove substantive reasoning or comprehensive domain coverage, and no generic unsupported claim is made grounded to improve answer rates.

No deployment, production configuration change or production migration was performed. The implementation and evidence are available for review; live-provider and production operational verification require separate authorisation and budgets.

## Final validation totals

The full backend suite passed **3,300 tests**, with 24 skips and two existing expected failures. The final targeted regressions passed **39 tests**. Frontend validation passed **222 tests across 48 files**, including two actual SVG rendering tests, and TypeScript completed successfully. Separate authenticated socket HTTP tests passed **2 tests** and isolated PostgreSQL/RLS tests passed **7 tests**. The temporary PostgreSQL server was stopped.

The unchanged offline benchmark scored **48 passed / 32 failed**; only seven cases produced an answered outcome under the synthetic unavailable-service setup. These results do not establish live answer quality or production readiness. See the [machine-readable validation summary](investigations/kriton-automatic-visualisation-2026-10-20/validation-summary.json) and [full backend log](investigations/kriton-automatic-visualisation-2026-10-20/backend-tests.log).
