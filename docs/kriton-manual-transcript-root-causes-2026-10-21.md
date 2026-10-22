# Kriton manual transcript: reproduced failures and fixes

21 October 2026. This investigation used the newly supplied transcript, current code and blocked/scripted model boundaries. No Groq or other live model tokens were used. Existing changes, including the separate reporting module, were preserved.

## What the transcript establishes

The transcript contains genuine input-routing, calculation coverage and chart-selection defects, alongside provider failures and honest incomplete-source responses. A paid API key cannot change these application code paths. Prior regressions covered narrower input shapes, so their passing results did not establish that these newly supplied forms worked.

The missing original £4,800 accrual and ₹84,600 GST scenarios are now available. Fifteen original questions were extracted verbatim into `backend/tests/fixtures/manual_transcript_20261021.json`, with a checksum of the uploaded transcript. They were not reconstructed backwards from expected outputs.

Nine initial regressions failed before the implementation changes. All fifteen final new regressions now pass; the additional cases cover state retention, independent-task isolation, safe request-size diagnostics, unsupported extra expenses and an unsourced accounting claim.

## Response review

| Supplied response | Finding | Verified result / current limit |
| --- | --- | --- |
| GST initial question | Incorrect clarification: the shared 18% rate and exclusive treatment were explicitly supplied. | Net sales ₹870,000; net purchases ₹400,000; output GST ₹156,600; input GST ₹72,000; payable **₹84,600**; both ledger differences zero. Fixed and verified fresh and after unrelated history. |
| Purchase returns correction | ₹86,400 payable and a ₹1,800 input-ledger discrepancy were arithmetically correct, but completion unnecessarily depended on the provider and omitted the output-ledger reconciliation. | Corrected input GST ₹70,200; payable **₹86,400**; output-ledger difference zero. The calculator explicitly defines differences as calculated minus recorded, so its input difference is **−₹1,800**, equivalent to a recorded excess of ₹1,800. Fixed without model calls. |
| Current UK VAT threshold | Partial retrieval response; not a false arithmetic refusal. It did not verify all requested current-rule details. | Official verification sources are available, but the running application's live retrieval/answer generation was not retested with provider calls. No current-rule data was hardcoded into the fixes. |
| Corporation tax on £180,000 accounting profit | An insufficient-evidence notice misses the user's request to identify the missing inputs. | Now asks for jurisdiction, period, taxable-profit adjustments and relevant relief/company information. Explicit supplied-rate arithmetic remains supported. |
| £4,800 electricity accrual | “Ignore VAT” triggered the VAT guard and requested an irrelevant rate. | Proposed debit electricity expense / credit accrued expenses **£4,800**; profit −£4,800; liability +£4,800; cash unchanged. Fixed, no posting or model call. |
| January invoice £5,100 | Difference of £300 and settlement arithmetic are useful, but the response assumes the earlier entry was actually posted and presents period treatment without sufficient care. | This exact invoice follow-up was restored but not newly implemented or live-verified in this phase. The new initial entry explicitly says proposed, not posted. The full follow-up still needs review before acceptance. |
| £75,000 revenue cut-off | Unsafe answer: invented 2023/2024 dates, unsupported framework claims and an automatic bill-and-hold liability conclusion. | Do not accept the transcript as verified audit advice. A scripted regression confirms the specific unsupported framework/liability statement is not released through the current offline pipeline. This is not validation of arbitrary live audit prose. |
| £62,000/£47,000 receivables investigation | Service request-size failure, not missing user inputs or evidence of misconduct. | No account-specific limit or historical request payload was available to distinguish the original local preflight rejection from a provider rejection. New diagnostics distinguish those origins safely. Full live answer remains unverified. |
| Profit versus cash example | Supplied calculations are correct: profit **£40,000**, operating cash movement **−£25,000**. | The figures do not establish detailed working-capital causes. No arithmetic change was needed. |
| £800,000 income statement | Incorrect and incomplete: sales returns were ignored; only gross profit/margin were returned despite six requested metrics. | Net sales **£780,000**, gross profit **£290,000**, gross margin **37.18%**, operating expenses **£180,000**, operating profit **£110,000**, operating margin **14.10%**, PBT **£101,000**. Fixed. |
| Depreciation correction | The transcript's corrected table is arithmetically right and contradicts its first answer. | Revised operating expenses **£184,000**, operating profit **£106,000**, operating margin **13.59%**, PBT **£97,000**; gross figures unchanged. Now deterministic, with original/current columns and successive corrections retained. |
| January–June line chart | Numbers are correct, but the selected chart was not rendered. | Six supplied observations now produce a real typed LINE payload, supporting table, **£576,000** total and **40%** first-to-last change. |
| Bar-chart follow-up | The transcript appears to render bars successfully. | Exact follow-up is now handled as a presentation change over the stored validated dataset, retaining all values and currency. |
| Six-section management report | Explicit failure is honest, but the contradictory “Answered — no cited sources” footer is wrong. The response also lost usable deterministic results. | Both periods now calculate: current GP £380,000 / OP £130,000 / PBT **£112,000**; previous GP £360,000 / OP £125,000 / PBT **£110,000**. On simulated provider failure, calculations are retained and report acceptance explicitly fails. The footer agrees. A complete six-section fallback was not added. |
| Mixed calculation/FX/fictional ticker | A partial response is appropriate if external parts cannot be completed, but displaying only 35% is insufficient. | Current blocked-provider regression retains **£280,000 gross profit and 35% margin**. Live retrieval and arbitrary successful provider-output preservation remain unverified; no price/rate was invented. |

The official UK sources currently state the £90,000 threshold and its 1 April 2024 effective date; use the [current registration page](https://www.gov.uk/register-for-vat) and [official change notice](https://www.gov.uk/government/publications/vat-increasing-the-registration-and-deregistration-thresholds/increasing-the-vat-registration-threshold). This external review is separate from verification of Kriton's own retrieval path. For the cut-off issue, [IFRS Foundation's published IFRS 15 text, B79–B82](https://www.ifrs.org/content/dam/ifrs/publications/pdf-standards/english/2021/issued/part-a/ifrs-15-revenue-from-contracts-with-customers.pdf) describes control and bill-and-hold conditions; retaining physical possession alone does not establish the transcript's automatic liability conclusion. No legal/framework applicability is inferred for the unspecified business.

## Earliest failing stages and changes

1. **VAT input guard — `input_requirements.py`.** The supported shared-rate wording did not cover “every transaction attracts 18%”. A literal mention of VAT in “ignore VAT” also activated a VAT calculation guard. The guard now recognises the supplied wording and distinguishes an ignored tax from a requested tax calculation. The corporation-tax guard now handles the specific missing-information request without intercepting explicit-rate calculations or unrelated operating forecasts.
2. **Tax ledger parsing — `calculations/engine.py`.** The original aliases recognised some “ledger says” and input-VAT/ITC forms, but missed “input GST ledger shows”. Added explicit aliases and bounded one-variable return corrections. The correction recomputes with the original rates/assumptions and recorded balances; it does not reuse assistant prose as source data.
3. **Lossy calculation selection — `calculations/statements.py`, `engine.py`, `service.py`.** The existing operating-statement matcher expected a particular two-period colon-labelled shape. An unmatched full statement fell through to the generic gross-margin calculator, which ignored sales returns and stopped. Added a bounded full-statement recogniser for supplied revenue, returns, COGS, operating components/aggregate and interest, plus one-variable component corrections. Added a guard so unsupported full statements with returns cannot masquerade as a complete gross-margin shortcut. Unknown extra monetary lines, mixed currencies and ambiguous aggregate/component combinations stay outside the new shortcut.
4. **Incomplete local explanation routing — `service.py`.** A negative instruction not to claim verified law was misread as a request for legal verification. Operational journal/working explanations already available from the calculator also unnecessarily entered provider composition. Corrected the negative-clause handling and bounded supported explanations; report sections and genuine external legal/current-rule requests still require their normal paths.
5. **Chart selection — `chart_intent.py`, `supplied_charts.py`, `visualization/router.py`.** The generic conditional guard rejected any question containing “if”, including the harmless rendering-failure instruction. The dataset parser also expected explicit month/value pairs rather than a month range with a “respectively” list. Added the bounded rendering-fallback exception, exact list-count validation, and month-range translation to the existing validated chart renderer. Real conditional data/evidence requests remain guarded. Extended view-change recognition for the supplied plural-bars instruction without re-extracting the figures.
6. **Context/capacity interaction — `service.py`.** Ordinary independent narrative questions could still append earlier chat content unless the narrower standalone-numeric heuristic matched. Composition now includes history when a recognised follow-up needs it; added explicit component, return, invoice and chart follow-up forms. This reduces unrelated context and prompt size, but cannot guarantee every provider request fits or every paraphrase is recognised.
7. **Request-size diagnosis — gateway `agent_budget.py` and `errors.py`.** Local size preflight and provider size failures used the same exception without origin metadata. Local failures now carry `origin=local_preflight`, the safe input estimate and configured limit; composition logs distinguish that origin. No prompts, keys or raw provider error bodies are added to these logs.
8. **Status presentation — `frontend/app/ask-kriton/page.tsx`.** The footer fell through to a route-based “Answered” label despite an unavailable report outcome. Report-incomplete/unavailable labels now take precedence, preserving specific provider-failure labels.

These fixes extend the existing orchestration, calculator, chart, history and audit contracts. They do not replace them with a second answer engine or weaken source rights, tenant isolation or evidence validation.

## Capacity and recurring failures

Current code defaults include `AGENT_MAX_REQUEST_TOKENS=8000` and `AGENT_MAX_COMPLETION_TOKENS=4096`. Historical composition logs also show the 8,000 request allowance. Input, tool schemas, returned tool results, reasoning and generated output compete within configured/provider constraints. A short visible question can therefore still become a large internal request.

A paid key does not automatically update application settings or establish which organisation/model limits apply. [Groq's official rate-limit documentation](https://console.groq.com/docs/rate-limits) describes organisation-level limits, and its [API reference](https://console.groq.com/docs/api-reference) describes completion-token controls. The actual account limits were not queried, and no paid-account entitlement or 413 cause is claimed verified. The implementation did not blindly increase budgets or retry rejected requests repeatedly.

The shared development database still reports that the `conversation_turns` migration is missing. The server currently falls back to supplied history. The new tests exercise durable memory only in isolated databases; they do not prove the shared database now retains task state. That migration remains an actual operational dependency and was not applied to shared data.

## Verification and build identity

- Before fixes: **nine failed** exact-scenario regressions.
- New final regressions: **15 passed**.
- Full backend: **3,344 passed**, 25 skipped, two existing expected failures, 140 warnings; 64.30 seconds.
- Full frontend: **222 passed in 48 files**; 11.90 seconds, including actual SVG chart/fallback tests with mocked geometry.
- TypeScript: successful, exit 0.
- Separate real HTTP / locally signed JWT / PostgreSQL application-role RLS: **three passed**, 12 successful question requests; 7.24 seconds. This includes the original GST and correction, accrual, income/depreciation and line/bar scenarios. External model transports were blocked. The worker's production lifespan is disabled and its JWT/JWKS/schema are isolated, so this does not certify production dependencies.
- All 102 original benchmark-manifest files remain unchanged. The optional 80-case offline benchmark scorer was not replayed in this turn; no improved score is claimed.

The running local `/health/version` returned HTTP 200 in **32.4 ms**. Its source hash matches both the current working tree and the separate socket worker:

`dde2b95acd39320a5d5660018eab67a25dc75d39214e7f9af286083084f74b1f`

Repository commit remains `1984fa9f78651f0830e3514c5f14b9695a884e30`; the dirty source fingerprint, rather than the commit alone, identifies these uncommitted changes. No authenticated model-backed question was sent to the user's running instance. Its health/version identity is verified; live provider answer quality is not.

Commands from `backend`:

```sh
RUN_LIVE_LLM_TESTS=0 KRITON_TRACE_DIR=/private/tmp/kriton-oct21-final-traces .venv/bin/pytest -q tests/test_manual_transcript_oct21.py
RUN_LIVE_LLM_TESTS=0 KRITON_TRACE_DIR=/private/tmp/kriton-oct21-final-traces .venv/bin/pytest -q -rxXs
RUN_SOCKET_HTTP_TESTS=1 RUN_LIVE_LLM_TESTS=0 .venv/bin/pytest -q tests/test_visual_socket_http.py
```

The last command additionally received URLs pointing only to the newly created disposable Unix-socket PostgreSQL cluster. That cluster was stopped after testing. Frontend commands were `npm test -- --run` and `./node_modules/.bin/tsc --noEmit --incremental false` from `frontend`.

## Evidence and remaining work

[Original transcript](investigations/kriton-manual-transcript-2026-10-21/original-transcript.txt), [before/after traces](investigations/kriton-manual-transcript-2026-10-21/http-after.json), [authenticated socket traces](investigations/kriton-manual-transcript-2026-10-21/http-socket-traces.json), [scoped patch](investigations/kriton-manual-transcript-2026-10-21/verified-changes.patch), [runtime identity](investigations/kriton-manual-transcript-2026-10-21/runtime-version.json) and [validation summary](investigations/kriton-manual-transcript-2026-10-21/validation-summary.json) are preserved alongside the test logs. The patch excludes unrelated pre-existing changes and passed reverse-application checking; it was not applied in reverse.

Remaining work includes the shared-memory migration, live retrieval/provider verification, complete six-section report generation under failure, and broader audit/invoice narrative validation. The exact invoice follow-up has not been certified. The specific source-free arithmetic and chart regressions passing does not establish that Kriton understands every possible paraphrase or that all generated accounting advice is correct. No production deployment, key change, paid model call, shared database mutation, commit or push was performed.
