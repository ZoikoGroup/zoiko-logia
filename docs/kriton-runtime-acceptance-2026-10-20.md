# Kriton runtime identity and report acceptance — 20 October 2026

The local serving backend now responds on port 8010 and its immutable source fingerprint matches the fresh application HTTP tests and the separate authenticated socket worker. Nine final health requests returned HTTP 200. This establishes the local build under test; it does not establish production readiness or reproduce the missing original fixtures.

## 1. Running build and timeout investigation

The original process was Uvicorn reload supervisor **2723**, started at 12:42:57 local time from this repository's backend directory. Its serving child **31836**, and subsequently **41158**, exited during startup. The read-only `_verify_security_policies()` database catalog query raised `TimeoutError`. Uvicorn's reload supervisor retained the listening socket with no live serving child. TCP listening therefore did not establish HTTP readiness; both version and liveness requests timed out. This was a worker/startup failure rather than a missing health route.

An automatic source reload temporarily recovered the worker, but another startup encountered the same database timeout. After recording that recurrence, the failed local reload supervisor was terminated once. Its existing `dev.mjs` supervisor restarted it with the same environment. Reloader **42924** and serving worker **42944** then completed startup. No startup security checks were bypassed, database schemas migrated or shared records written. No production process or configuration was changed.

The final serving identity is:

- Repository commit: `1984fa9f78651f0830e3514c5f14b9695a884e30`.
- Release label: `development`.
- Application source SHA-256: `49cdee0f61f348407961638b04e1f8efb40100999c2cd808c79953809815e447`.
- Build ID: `development:49cdee0f61f348407961638b04e1f8efb40100999c2cd808c79953809815e447`.
- Worker identity captured at `2026-10-20T08:52:29.720559+00:00`.

The working tree is dirty, so the commit alone does not identify these changes. New `app/core/build_identity.py` captures the commit, source hash, existing configuration hash and capture time once per process. `/health/version` returns that immutable snapshot rather than hashing whichever files happen to be on disk later. Responses carry the same `X-Kriton-Build` header, including the actual `/ask` responses in the isolated traces. The source hash is for backend application Python files, not frontend assets or every repository file. It is diagnostic identity, not signed supply-chain attestation.

The underlying database latency has **not** been permanently resolved. A separate read-only `SELECT 1` probe took 3,765 ms, and the final readiness probes took approximately one second. The startup timeout can recur. The shared database also lacks the `conversation_turns` migration, as recorded in the logs. Its supplied-history fallback is not equivalent to verified durable memory. No shared-database migration or policy change was performed.

Evidence: [startup events](investigations/kriton-runtime-acceptance-2026-10-20/startup-events.log), [failed runtime probes](investigations/kriton-runtime-acceptance-2026-10-20/runtime-before-restart.json), [final runtime identity and latencies](investigations/kriton-runtime-acceptance-2026-10-20/runtime-check.json).

## 2. Original fixture recovery

All 94 available text attachments, current tests and investigation documentation were searched, including Unicode/space-normalized monetary amounts. No original £4,800 accrual transaction or ₹84,600 GST calculation prompt was found. Only their expected outputs are supplied in the current request. The original full six-section management-report payload is also unavailable.

Those original fixtures remain **blocked pending their exact original prompts**. A request for the missing prompts was sent while the independent work continued. No input dataset was constructed backwards from an expected answer, and no different scenario is labelled a restored original.

Existing exact fixtures did run unchanged: the supplied ₹226,800 GST case (including zero ledger differences, fresh and after unrelated history), natural-language machine depreciation (£24,000 over six years, zero resale value: £4,000 yearly and £333.33 monthly), income-statement corrections, task isolation, bank reconciliation and inventory checks. These passing regressions do not prove the missing £4,800/₹84,600 originals pass.

See [fixture provenance and missing-input status](investigations/kriton-runtime-acceptance-2026-10-20/fixture-provenance.json).

## 3. Report completion and provider failure

The existing calculation, orchestration, coverage and audit paths remain in use. No parallel report engine or unverified canned report was added.

A six-section report with no supplied section titles uses this explicit contract:

1. Executive summary.
2. Financial results and workings.
3. Key changes and interpretation.
4. Risks and limitations.
5. Management questions.
6. Recommended next steps.

Explicit user-supplied section names take precedence. Missing sections and empty/placeholder-only headings fail coverage checks. These checks establish structural coverage; existing numerical and evidence validators remain necessary. They cannot prove the substantive adequacy of arbitrary report prose.

The new regression exposed an earlier calculation failure: the operating-statement parser counted `sections:\n1. Executive summary` as an additional labelled monetary input. This made an otherwise supported statement unrecognised, so there were no verified calculations to retain after provider failure. The amount guard now excludes numbered section-list starts while still rejecting unknown actual monetary lines. A regression asserts that an unclassified expense is still rejected.

When a requested report of six or more sections cannot be completed, the final response now returns:

- `outcome: unavailable`.
- `next_action.type: report_incomplete`.
- An explicit statement that the report cannot be completed and has not passed report-completion validation.
- Each missing section marked incomplete in `requested_deliverables`.
- Already verified calculations retained, when available, with `answer.completeness: partial`.

A retained calculation is useful recovery evidence, **not an accepted complete report**. The acceptance tests require that the failed request cannot satisfy the completed-answer conditions. Fresh and multi-turn provider-service-failure and timeout tests preserve the independently verified £177,000 profit before tax while explicitly failing report acceptance. A complete deterministic six-section fallback has not been implemented; the explicit failure branch is the permitted alternative in this request.

Changed implementation files: `app/core/build_identity.py`, `app/main.py`, `app/orchestration/answer_coverage.py`, `app/orchestration/service.py`, and `app/orchestration/calculations/statements.py`. New tests are in `tests/test_report_completion_acceptance.py`. Existing offline and socket HTTP fixtures now record/assert serving build identity.

## 4. Fresh regression results against the identified source build

| Check | Result | Evidence |
| --- | --- | --- |
| Full backend | 3,309 passed; 24 skipped; two existing expected failures; 140 warnings; 74.12 s | [Log](investigations/kriton-runtime-acceptance-2026-10-20/backend-tests.log) |
| Final report/build/depreciation/domain subset | 14 passed; 4.97 s | [Log](investigations/kriton-runtime-acceptance-2026-10-20/final-targeted-tests.log) |
| Full frontend, including actual SVG rendering | 222 passed; 11.43 s | [Log](investigations/kriton-runtime-acceptance-2026-10-20/frontend-tests.log) |
| TypeScript | Successful, exit 0 | [Log](investigations/kriton-runtime-acceptance-2026-10-20/typescript.log) |
| Separate real HTTP / signed JWT / PostgreSQL / audit | Two passed; 6.53 s; five successful question requests plus invalid-token rejection | [Log](investigations/kriton-runtime-acceptance-2026-10-20/socket-tests.log), [traces](investigations/kriton-runtime-acceptance-2026-10-20/http-socket-traces.json) |
| Separate PostgreSQL source/cache/RLS isolation | Seven passed; 1.75 s | [Log](investigations/kriton-runtime-acceptance-2026-10-20/postgres-rls-tests.log) |
| Unchanged original 80-case benchmark | Scorer: 48 passed / 32 failed; only seven answered outcomes | [Results](investigations/kriton-runtime-acceptance-2026-10-20/original-benchmark-summary.json) |

The full suite includes fresh tasks, corrections, follow-ups, missing-input detection, deterministic calculations, source/jurisdiction grounding, provider failures and response completeness. Optional database and live-provider tests remain skipped in that run; the separate socket/RLS suites above were explicitly enabled. This is not a claim that every skipped integration was run.

The socket tests use local cryptographically signed JWT/JWKS, real application-role PostgreSQL RLS and the production request router. The worker has production lifespan disabled and uses a disposable schema. Its source build is identical to the local serving backend, but its test identity provider, schema and configuration differ. No authenticated question was submitted to the user's port-8010 database or live Groq provider. Real frontend Recharts SVG is exercised with mocked layout geometry; no manual screenshot/browser check of the running frontend is claimed.

The benchmark cases and scorer were preserved. SHA-256 verification confirms all 102 baseline manifest files are unchanged. Synthetic unavailable services limit what the score means: 63 outcomes were unavailable, seven answered, three clarification requests, five refusals and two rejections. The 48 scorer passes are not 48 complete live answers. [Manifest](investigations/kriton-runtime-acceptance-2026-10-20/baseline-sha256.json).

Commands used, from `backend` unless noted:

```sh
RUN_LIVE_LLM_TESTS=0 KRITON_TRACE_DIR=/private/tmp/kriton-runtime-final-traces .venv/bin/pytest -q -rxXs
RUN_LIVE_LLM_TESTS=0 KRITON_TRACE_DIR=/private/tmp/kriton-runtime-final-traces .venv/bin/pytest -q tests/test_report_completion_acceptance.py tests/test_domain_intelligence_http.py
RUN_LIVE_LLM_TESTS=0 RUN_OFFLINE_ORIGINAL_BENCHMARK=1 KRITON_TRACE_DIR=/private/tmp/kriton-runtime-benchmark .venv/bin/pytest -q tests/test_original_benchmark_offline.py
RUN_SOCKET_HTTP_TESTS=1 RUN_LIVE_LLM_TESTS=0 .venv/bin/pytest -q tests/test_visual_socket_http.py
RUN_LIVE_LLM_TESTS=0 .venv/bin/pytest -q tests/test_passage_cache_isolated_postgres.py
```

The last two commands additionally received explicitly isolated database URLs through their documented test environment variables. They must not target a shared database; their fixtures rebuild disposable schemas. The temporary task-owned PostgreSQL cluster was stopped after the tests. Frontend commands were `npm test -- --run` and `./node_modules/.bin/tsc --noEmit --incremental false` from `frontend`.

## 5. Final runtime repetition and acceptance limits

Three consecutive requests per endpoint returned:

| Endpoint | Status | Recorded latency range |
| --- | --- | --- |
| `/health/version` | 200, 200, 200 | 1.637–3.740 ms |
| `/health/live` | 200, 200, 200 | 0.986–1.806 ms |
| `/health/ready` | 200, 200, 200 | 974.872–1,236.140 ms |

All carried the same serving build ID. The header in fresh offline HTTP and socket traces matches that source build. The configured production dependencies were not exercised with live model calls, production authentication, production database migrations or all browser renderers.

Remaining blockers are the missing exact original fixtures, recurring database-startup latency and missing shared durable-memory migration, plus the 32 unchanged offline benchmark failures and unverified live-provider quality. The local restart recovers service but does not permanently correct the database or reload-supervisor failure mode. No production-readiness claim is made.

No Groq tokens or other live model tokens were used. Existing Git changes were preserved; nothing was committed, pushed or deployed, and no production configuration or shared database data was changed. [Machine-readable validation summary](investigations/kriton-runtime-acceptance-2026-10-20/validation-summary.json).
