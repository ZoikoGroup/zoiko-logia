# Kriton: implemented reliability fixes — 21 October 2026

The supplied VAT, bank reconciliation, audit, CVP and quarterly-budget transcript exposed several application defects. A paid Groq key does not correct these defects. This change fixes reproduced paths and adds regression coverage; it does not establish that every possible prompt will succeed.

## Root causes and implemented fixes

| Root cause | Change | Verified result |
| --- | --- | --- |
| Provider-error recovery equated a successful calculator call with a calculation grounded in the task. Unrelated operands could become a supposedly verified answer. | Recovery checks operands against the supplied evidence and successful non-calculator results, then follows accepted calculation dependencies. Unsupported receipts are removed from the released recovery result. | The unrelated £12,500 + £1,200 − £4,300 example is withheld; valid bank calculations survive the same simulated provider failure. Arithmetic correctness alone no longer establishes recovery eligibility. |
| Recognised revisions did not consistently retain original inputs, and could fall through to model-generated examples. | A shared revision resolver uses typed calculator inputs from user turns, replays recognised updates, and stops at an intervening independent task. It reuses existing formula implementations. | Bank cheque correction produces £28,400 adjusted bank, £28,500 adjusted book and −£100 bank-minus-book difference. VAT refund produces final net receipts £55,000 and VAT £11,000. Repeated refunds remain cumulative. |
| Original/adjusted reconciliation labels were interpreted as unrelated historic scenarios. | Figure attribution distinguishes an independent task from a revision before applying historical scenario checks. | Original bank reconciliation retains supplied figures and produces £28,500 on each side, including after an unrelated earlier turn. |
| Text recognition missed supported input forms and omitted requested feasibility outputs. | Added supplied-input aliases, explicit loan-payment handling, retained target profit/capacity and whole-unit break-even results. | CVP: £30 contribution, 6,000 break-even units, 9,000 target units versus 8,000 capacity, £60,000 maximum profit. Revised £48 variable cost: £27 contribution, 6,667 whole break-even units, 10,000 target units, £36,000 maximum profit. Loan journal: debit loan £15,000, debit interest expense £3,000, credit bank £18,000 under the supplied expense assumption. |
| A quarter label's digit could be parsed as the actual financial measure. The supplied quarterly dataset lacked a deterministic comparison route. | Added a token boundary to target-pair extraction and a validated two-series budget/actual chart and variance table. Table-only follow-up reuses the nearest supported user dataset. | Q1 is a category, not amount 1. Budget £350,000 versus actual £358,000: £8,000, 2.29%. An actual grouped chart renders eight bars; its table retains both series. |
| Supplied audit facts were unnecessarily dependent on external sources/model completion. | Added bounded inventory-count and invoice-threshold analyses using the supplied figures, with evidence requests and conditional conclusions. | Inventory: 30-unit/£720 shortage; management's unverified 20-unit dispatch explanation leaves a conditional 10-unit/£240 difference. Invoices total £29,700; being individually below £10,000 supports investigation, not a finding of fraud or automatic policy breach. |
| A clearly incomplete income-tax question could reach the provider instead of asking for missing facts. | Local missing-input detection requests jurisdiction, currency, tax year and relevant business/tax details without inventing a rate. | The supplied incomplete question produces clarification without provider access. |

These are bounded supported calculation and follow-up families, not a replacement for general language understanding. Ordinary model answers still need their existing grounding and completeness checks. Recovery operand checking establishes numeric provenance, not the semantic correctness of every conceivable formula. Existing correct fictional-tax, cash-conversion-cycle, missing-month and profit-reconciliation cases were retained.

## Verification

No live Groq or other model-provider calls were made. Tests use blocked or scripted transports.

- Before fixes: eight newly restored regression tests failed. The exact 16 source questions are preserved in `backend/tests/fixtures/systemic_scenarios_20261021.json`, with source checksum.
- Backend full suite: **3,363 passed, 25 skipped, 2 expected failures**. Targeted recovery/provenance/agent regression group: **115 passed**. The later additional socket case is covered separately below.
- Frontend full suite: **223 passed across 48 files**. TypeScript check passed. The three real SVG tests passed without mocking the chart library, including eight quarterly bars and table parity.
- Separate real loopback HTTP/JWT/PostgreSQL suite: **4 passed**, recording **23 successful question requests**, including a mixed conversation covering all revised task families. It uses an isolated PostgreSQL app role with RLS, local JWT/JWKS and provider access blocked. Its worker runs without application lifespan, so this is not production startup validation.
- **102 existing benchmark files retain their recorded checksums**. No benchmark cases were rewritten. This is not a new live benchmark quality score.

The new grouped-chart SVG test initially failed because its geometry stub measured the legend as the entire 300-pixel chart height. Correcting that measurement to a realistic legend height resolved it. No frontend production renderer change was needed for this finding.

## Running build and remaining limits

The local port 8010 `/health/version` returned **HTTP 200 in 32 ms**. Its immutable source hash matches the tested worker and current backend source:

`384a56c9402a3a3e12112313b7173adab45759d365ba957ec2ce3288088b7886`

Its commit is `1984fa9f78651f0830e3514c5f14b9695a884e30`; this is a dirty development build, so the source hash is necessary to identify the actual tested code. The runtime configuration hash differs from the isolated test worker, as expected for separate configurations. This single health observation does not establish sustained latency, production deployment, or live answer quality.

The previously identified shared-database `conversation_turns` migration remains an operational issue; no shared migration was applied here. The isolated suite provisions its own database and does not prove shared-runtime conversation persistence. The temporary test cluster was stopped. These fixes do not implement the separate six-section management-report fallback or prove unrelated older invoice follow-up cases fixed. No production deployment was performed, and existing working-tree changes were preserved.

## Reviewable evidence

[Evidence manifest](investigations/kriton-systemic-reliability-2026-10-21/evidence.json), [before-fix failures](investigations/kriton-systemic-reliability-2026-10-21/before.log), [full backend result](investigations/kriton-systemic-reliability-2026-10-21/backend-full.log), [HTTP traces](investigations/kriton-systemic-reliability-2026-10-21/http-socket-traces.json), and [scoped implementation patch](investigations/kriton-systemic-reliability-2026-10-21/scoped-fixes.patch) preserve this change separately from the existing dirty tree.
