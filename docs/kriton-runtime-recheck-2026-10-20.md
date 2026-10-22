# Kriton runtime and regression recheck — 20 October 2026

This recheck made no implementation changes, provider calls, shared-database writes or deployment changes. Existing working changes remain intact.

## Running-instance check

Local listeners included frontend port 3000 and a Python process on port 8010. A read-only GET of http://127.0.0.1:8010/health/version timed out after five seconds without returning data. The running backend version and its readiness therefore remain unconfirmed. No restart was performed. The existing endpoint returns revision and config_hash; its hash reads current files, so even a successful response alone would not prove all modules in a long-running interpreter were reloaded.

## Fresh local regression evidence

- Backend: **44 passed in 10.07 seconds** across automatic visual integrity, root-cause HTTP, stage-investigation HTTP and restored-branch regressions. [Log](investigations/kriton-runtime-recheck-2026-10-20/backend-tests.log).
- Frontend: **2 passed**, rendering real Recharts SVG line/bar output and exercising rendering-failure table fallback. Geometry is mocked; this is not a screenshot of the running frontend. [Log](investigations/kriton-runtime-recheck-2026-10-20/svg-tests.log).
- [Fresh request/response traces](investigations/kriton-runtime-recheck-2026-10-20/http-traces.json) are offline in-process HTTP evidence, not requests to port 8010.

## Acceptance status

| Requested check | Verified status |
| --- | --- |
| Running build includes fixes | Unconfirmed: version endpoint timed out. |
| Exact £4,800 accrual journal without sales-return contamination | Exact prompt not available in this request; not verified. Other independent-task and follow-up isolation regressions passed. |
| Depreciation with supplied inputs | Existing regression passed for a $20,000 asset, five-year life and $2,000 salvage value: $3,600 annual depreciation. This does not reconstruct the missing transcript. |
| Exact ₹84,600 GST payable / zero ledger difference | Exact source figures and assumptions not supplied; not verified. Existing supplied GST case passed at ₹226,800 with both ledger differences zero. |
| Actual visible chart | Real SVG component tests passed and HTTP chart payload/follow-up tests passed. Visibility in the running application remains unverified. |
| Six-section report despite provider failure | Not established. Current failure handling preserves verified calculations and honestly marks unfinished sections partial; this does not satisfy the stronger requirement to produce all six substantive sections. |

No claim is made that every failure in the uploaded historical log is fixed or that production has been updated. No live Groq tokens were used. The previous unchanged offline benchmark still scored 48 passed / 32 failed and is not a live quality acceptance result.
