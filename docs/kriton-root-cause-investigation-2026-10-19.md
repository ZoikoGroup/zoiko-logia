# Kriton root-cause investigation — 19 October 2026

Five existing components were corrected and offline regressions pass. No Groq tokens were used. This verifies specific local defects, not production reliability or live model intelligence. Existing working-tree changes were preserved; no commit, deployment, production configuration change or shared-database write was made.

## Findings and fixes

| Case | First incorrect stage observed before fix | Correct behaviour and final result |
| --- | --- | --- |
| A: inclusive VAT | No new defect reproduced in current route | £150,000 inclusive at 20% gives £125,000 net and £25,000 VAT; fresh and multi-turn pass. |
| B: minimal inventory statement | Inventory parser required operating expenses even when operating profit was not requested | Net sales £936,000, COGS £560,000, gross profit £376,000. No invented operating expenses. |
| C: stock correction | Requested separate finance-cost output was absent; underlying arithmetic already worked | Corrected COGS £570,000, GP £366,000, operating expenses £222,000, OP £144,000, finance costs £9,000, PBT £135,000. |
| D: independent reconciliation | No new defect reproduced | £180,000 result, £30,000 discrepancy; supplied/computed margins 36% and 42%. Independent task does not inherit unrelated figures. |
| E: durable follow-up | Explicit reference to unavailable prior figures could reach the model instead of asking for missing context | Accessible durable D context answers directly. Other tenant gets clarification with zero model requests and no leaked figures. |
| F: supplied GST rate and returns | Missing-input gate failed to recognise explicitly shared 18% rate; underlying calculator also ignored returns | Net sales £2,280,000 × 18% = £410,400; net purchases £1,020,000 × 18% = £183,600; net payable £226,800. Both supplied ledgers match. |
| G: long response and provider errors | No new model-generation defect proven offline | Scripted complete response and follow-up pass; size, timeout and truncation failures preserve verified calculations and remain partial. |

Additional verified defect: replaying the same idempotency key minted a second receipt. The router now returns the existing validated, scoped cached receipt. Authentication and request-scope validation still run.

Before-fix observations included B `corr-e6bfef90a7ad`, C correction `corr-ae2ecccad2a5`, and F `corr-a9c5dff2a0ab`. Temporary raw before traces are no longer available; these are recorded investigation observations, not independently replayable production evidence. Current raw after traces are preserved below.

## Exact change scope

See [scoped review patch](investigations/kriton-root-cause-2026-10-19/verified-fixes.patch), which separates this investigation from extensive pre-existing working-tree edits.

- `backend/app/orchestration/input_requirements.py`: recognise the explicitly supplied shared GST/VAT rate.
- `backend/app/orchestration/calculations/engine.py`: subtract sales/purchase returns before tax, retain explicit calculation inputs and rates, compare supplied ledgers, reject invalid returns/currency combinations. Existing canonical VAT output names remain compatible.
- `backend/app/orchestration/calculations/inventory_statement.py`: allow requested gross-profit calculations without inventing missing operating expenses; bind ambiguous returns to appropriate sales context; expose explicit finance costs.
- `backend/app/orchestration/router.py`: preserve the original durable receipt on validated idempotent replay.
- `backend/app/orchestration/service.py`: clarify explicit references to missing prior figures using the existing context path.

No replacement router, prompt pipeline, calculator, memory or evidence system was introduced. Source eligibility, tenant scope and audit controls were retained. Real PostgreSQL RLS and database-computed passage digest behaviour were not verified by SQLite tests.

## Validation

The full offline backend suite completed with **3,246 passed, 22 skipped, 2 expected failures, 0 failures**, in 56.15 seconds (140 warnings). Skips: 18 PostgreSQL integration checks, two live-model tests, one missing OCR dependency and the opt-in benchmark replay (run separately). Expected failures remain the existing native-language Austria aliases.

The final dedicated regression run completed with **18 passed in 5.19 seconds**, including 14 HTTP tests, 22 recorded HTTP requests and four independent GST arithmetic/validation tests. Focused existing VAT, memory, typed-figure, source eligibility and tenant/audit suites also completed with 70 passed and five skipped. Whitespace and scoped reverse-patch applicability were checked.

The HTTP fixture runs the real application route, RBAC lookup, task/context selection, calculations, orchestration, eligibility, idempotency and persisted audit/receipt logic against isolated SQLite sessions. It checks tenant identity, receipt durability and actual audit payload/chain hashes. Authentication tokens and provider transports are synthetic; DNS/external HTTP are blocked. Production startup/lifespan is not executed. G's successful long response is scripted, so it does not prove that a live model will compose it correctly. Timeout exceptions are injected rather than waiting through a production deadline. Synthetic usage fields are not billing evidence.

### Unchanged original benchmark

All 80 original cases reached HTTP 200 through the isolated route. The unchanged original scorer reported **48 passed and 32 failed**. Actual outcomes were **7 answered, 63 unavailable, 3 clarification required, 5 refused and 2 rejected**. Of the scorer's 48 passes, 33 were unavailable responses: some original expectations are too weak to establish answer quality. The scorer and cases were deliberately left unchanged.

This is not an answer-quality pass. Model/search-dependent cases cannot establish live performance with scripted unavailable transports. One existing expectation still requires a generic footer removed earlier at the user's request. Detailed case outcomes are in [original benchmark results](investigations/kriton-root-cause-2026-10-19/original-benchmark-offline.json). All 102 original evaluation/report JSON hashes were checked unchanged; see [hash manifest](investigations/kriton-root-cause-2026-10-19/benchmark-sha256.json).

### Reproduction

Run from `backend`, with no live-provider opt-in:

```sh
RUN_LIVE_LLM_TESTS=0 .venv/bin/pytest -q -rxXs
RUN_LIVE_LLM_TESTS=0 KRITON_TRACE_DIR=/private/tmp/kriton-root-cause-final .venv/bin/pytest -q tests/test_root_cause_http.py tests/test_gst_returns_regression.py
RUN_LIVE_LLM_TESTS=0 RUN_OFFLINE_ORIGINAL_BENCHMARK=1 KRITON_TRACE_DIR=/private/tmp/kriton-root-cause-benchmark-final .venv/bin/pytest -q tests/test_original_benchmark_offline.py
```

## Current isolated request evidence

These correlations belong to temporary isolated ledgers, not the production audit replay UI. Full request, model boundary, calculation, history selection, response and persisted audit data are in [after traces](investigations/kriton-root-cause-2026-10-19/http-traces-after.json). Latencies are local synthetic timings, not production or live-provider performance.

| Case | Correlation ID | Outcome | Milliseconds |
| --- | --- | --- | --- |
| A-F-unrelated | corr-066b278180d8 | answered | 64.58 |
| A-fresh | corr-15e4d0c61d3e | answered | 90.85 |
| A-multiturn | corr-be1a261c0cf2 | answered | 19.61 |
| A-replay-first | corr-3b32f1ad8686 | answered | 62.55 |
| A-replay-second | corr-3b32f1ad8686 | answered | 3.92 |
| B-minimal | corr-296c58a5bd73 | answered | 67.56 |
| C-baseline | corr-2a4df868dbb2 | answered | 123.82 |
| C-corrected | corr-d9d25634eda6 | answered | 18.72 |
| D-fresh | corr-3abda14a6921 | answered | 63.91 |
| D-new-task | corr-b38e8826f64d | answered | 27.4 |
| D-unrelated-baseline | corr-fed8b9efcc04 | answered | 68.79 |
| E-durable-followup | corr-318408964112 | answered | 20.79 |
| E-other-tenant | corr-19685fc46f98 | clarification_required | 11.83 |
| F-after-fix | corr-01603d9dc88b | answered | 68.53 |
| F-multiturn | corr-13f00c936456 | answered | 18.19 |
| G-followup | corr-769ec95d9375 | answered | 22.78 |
| G-provider-failure | corr-a75be6604427 | answered | 107.6 |
| G-real-length-response | corr-1c144a3787f5 | answered | 87.95 |
| G-scripted-complete | corr-923bbf1ac842 | answered | 173.18 |
| G-size | corr-141dd5364d50 | answered | 160.51 |
| G-timeout | corr-ecac05d36ff9 | answered | 91.63 |
| G-truncation | corr-a0c10e573aa3 | answered | 91.8 |

## Remaining limits

Live answer quality, paid Groq limits, current-source retrieval and production integrations remain unverified. Previously reported production memory-migration activation and separate search allowance issues were not rechecked or changed here. PostgreSQL integration coverage remains skipped. A paid key alone cannot correct routing, calculation or missing-context defects. Specific regressions now protect the repaired cases; no implementation can promise successful answers to every arbitrary question or remove genuine service failures.

Further production verification should use separately authorised access and budgets. This investigation does not activate a migration, change providers, hide incomplete answers or claim deployment success.
