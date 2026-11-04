Phase 1 targeted remediation — 25 October 2026

Targeted fixes are implemented for review in the isolated reliability worktree. Production remains NO-GO: the unchanged offline release gate still reports 91 blocking entries. No actual database data was inspected, no existing document or audit history was changed, and no production writes, real-content ingestion, application/environment migrations, deployment, commit, push or copying to the main folder occurred. Regression fixtures use disposable test storage; their schema setup/migration unit tests are not application-environment migrations.

| Request | Delivered result |
|---|---|
| Individually classify all 91 gate entries | [Updated JSON](/private/tmp/zoiko-phase1-remediation/blockers-91-updated.json), [CSV](/private/tmp/zoiko-phase1-remediation/blockers-91-updated.csv), [readable ledger](/private/tmp/zoiko-phase1-remediation/blocker-dispositions.md). Original B001–B091 IDs and before/after evidence are retained. Every row has severity, criterion, disposition and evidence. No criterion is waived. |
| Fix overbroad clarification | General tax concepts/checklists, supplied-rate accounting arithmetic and pure macroeconomic comparisons no longer require irrelevant statutory-source clarification. Rates, turnover limits, scheme eligibility, deadlines, legal questions, framework rules, historical applicability and contradictory request filters keep their checks. No denied or pending passage is made eligible. |
| Fix incomplete credit-sale answers marked complete | Composition now attempts the requested journal instead of returning VAT-only arithmetic as the full answer. Final coverage validates journal accounts, debit/credit sides, amounts, currency and balance against passed canonical arithmetic. Missing, unsupported, contradictory or invalid entries are incomplete, with partial verification and journal_review_required. |
| Prepare read-only verification | [Plan](/private/tmp/zoiko-phase1-remediation/read-only-verification-plan.md), [prepared SQL](/private/tmp/zoiko-phase1-remediation/inventory-22-readonly.sql). Not authorized or executed. Exactly bound authoritative IDs and target tenant are prerequisites; no arbitrary LIMIT 22 or all-document discovery. |
| Do not inspect/change production | No production connection, data inspection, status correction or audit-history change performed. Main-folder credentials were not loaded. |
| Queue only verified records | [Queue](/private/tmp/zoiko-phase1-remediation/verified-review-queue.json): verified_records=[]; actual count unknown; expected legacy set of 22 unresolved. No invented IDs, usage counts, ranking, reviewer or schedule. |
| Rerun tests and unchanged gate | Actual results below. Gate/baseline/evaluation fixture hashes are unchanged. |
| Explicit governance/live dependencies | Live candidate/credentials, evaluation tenant, accountant-approved ground truth, verified inventory and named independent-review scheduling remain unavailable/unvalidated. No live accuracy claim. |

Implementation and test evidence

| Area | Implementation | Evidence |
|---|---|---|
| Scope the applicability guard to the request | [applicability.py](/Users/kailanaresh/zoiko-logia-reliability/backend/app/orchestration/applicability.py:38), [retrieve.py](/Users/kailanaresh/zoiko-logia-reliability/backend/app/orchestration/retrieve.py:526) | Positive and negative classification, retrieval and HTTP tests in [test_phase1_targeted_remediation.py](/Users/kailanaresh/zoiko-logia-reliability/backend/tests/test_phase1_targeted_remediation.py:1). Pure macro comparison still searches each named country and retains labels; actual data availability/period checks stay with the connector. |
| Do not stop at the VAT arithmetic shortcut | [service.py](/Users/kailanaresh/zoiko-logia-reliability/backend/app/orchestration/service.py:2208) | HTTP provider-failure case retains arithmetic but reports partial; a positive synthetic journal response can complete. No journal is invented when the provider fails. |
| Validate the requested journal at final assembly | [answer_coverage.py](/Users/kailanaresh/zoiko-logia-reliability/backend/app/orchestration/answer_coverage.py:78), [finish path](/Users/kailanaresh/zoiko-logia-reliability/backend/app/orchestration/service.py:1649) | Tests reject absent entries, account-name-only prose, wrong amounts, balanced wrong amounts, wrong accounts, input instead of output VAT, reversed sides, mismatched currency, contradictory entries and unverified canonical arithmetic. Valid explicit tables/Dr-Cr lines match the supplied net-sale inputs. |

The journal check is intentionally bounded: it validates the supported positive net-sale/supplied-VAT-rate exercise with passed engine arithmetic and recognizable account/amount formats. Gross/zero-tax/multi-transaction or unsupported journal formats without equivalent validation remain incomplete. It does not certify legal tax eligibility, perform a posting, or supply accountant-approved ground truth. Production code contains no case-specific £5,000/£1,000/£6,000 answer; those values occur only in synthetic tests and saved evaluation data.

Verification

| Command/check | Actual result | Evidence |
|---|---|---|
| New targeted regression module, UTC | 44 passed, exit 0 | [Named tests](/private/tmp/zoiko-phase1-remediation/focused-final.log) |
| Full backend, TZ=UTC, isolated SQLite | 4,887 passed; 82 skipped; 22 xfailed; 133 warnings; exit 0 | [Log](/private/tmp/zoiko-phase1-remediation/backend-final-0.log), [JUnit](/private/tmp/zoiko-phase1-remediation/backend-final-0.xml) |
| Full backend, TZ=Asia/Kolkata, isolated SQLite | 4,887 passed; 82 skipped; 22 xfailed; 133 warnings; exit 0 | [Log](/private/tmp/zoiko-phase1-remediation/backend-final-1.log), [JUnit](/private/tmp/zoiko-phase1-remediation/backend-final-1.xml) |
| Frontend tests | 51 files / 239 tests passed, exit 0 | [Log](/private/tmp/zoiko-phase1-remediation/frontend-tests.log) |
| TypeScript | tsc --noEmit --incremental false, exit 0 | [Log](/private/tmp/zoiko-phase1-remediation/typescript.log) |
| Frontend lint | npm run lint, exit 0 | [Log](/private/tmp/zoiko-phase1-remediation/frontend-lint.log) |
| Existing routing benchmark | 309 signatures, 0 changed/added/removed | [Comparison](/private/tmp/zoiko-phase1-remediation/routing-comparison.json) |
| Unchanged offline release gate | FAIL, exit 1; 91 conditions | [Log](/private/tmp/zoiko-phase1-remediation/offline-release-gate-final.log), [raw report](/private/tmp/zoiko-phase1-remediation/offline-release-gate.json) |
| Reconstruct gate metrics from saved traces | All 167 non-gold cases reproduce the saved aggregates exactly | [Reconstruction log](/private/tmp/zoiko-phase1-remediation/metric-reconstruction.log), [per-case metrics](/private/tmp/zoiko-phase1-remediation/reconstructed-case-metrics.json) |
| Gate integrity | Criteria, accepted baseline and offline-gate test fixture unchanged byte-for-byte | [Hash proof](/private/tmp/zoiko-phase1-remediation/unchanged-gate-proof.json) |

The full regression suites exercise isolated schema fixtures. No PostgreSQL migration/concurrency environment was started or application migration applied in this remediation turn. Previously supplied isolated PostgreSQL results remain historical evidence, not a newly verified production migration/restore or actual tenant audit check.

Why 91 failures remain

The count is still 75 baseline-case regressions + 6 overlapping zero-tolerance safety failures + 5 metric failures + 4 dataset minimum-rate failures + 1 unevaluated gold dataset. These are 91 gate conditions, not 91 independent live defects. All original IDs retain their failed release status and severity (8 Critical, 83 High); safety conditions are not downgraded because a fixture is synthetic.

| Current primary classification | Entries | Disposition |
|---|---:|---|
| R1 deliberately incomplete synthetic provider | 63 | Recorded ProviderResponseIncomplete in the unchanged negative fixture. Keep failed evidence; independently reviewed positive fixtures/live evaluation are still required. It does not prove production failure or exclude another parser/routing defect. |
| R2 missing independently validated request jurisdiction | 16 | Keep required jurisdiction checks. Agree dataset/request metadata before supplying scope; do not silently assume UK/India from dataset labels or lift filters. |
| R4 VAT assumptions / mixed arithmetic/legal task expectations | 2 | Preserve missing-input safeguards. Tax-inclusive/exclusive assumptions and the expected partial/mixed answer need independent/accountant disposition. |
| R6 aggregate metric/minimum-rate conditions | 9 | Keep failed; each aggregate lists its contributing failed cases and underlying roots. Do not lower thresholds or rewrite the baseline. |
| R7 unavailable tenant-scoped reviewed gold | 1 | Missing EVAL_TENANT_ID and approved tenant-specific ground truth remain blocked. No empty or other-tenant substitute. |

The original overbroad-checklist and macro-comparison guard defects are fixed in the tested scope. Their three original condition entries still fail under the deliberate provider exception; their before/after traces now show composition_failed instead of the unrelated jurisdiction/source clarification. The unchanged harness seeds tenants/users, no governed sources, no successful composition responses, and scripted LOW risk-classifier replies. It is not a qualified positive live-accuracy environment.

The accounting credit-sale case remains a content-score failure because that fixture produces no journal. Its response is now answered/PARTIAL, arithmetic verified but overall PARTIALLY_VERIFIED, journal deliverable incomplete, next action journal_review_required. The positive HTTP test returns a complete journal only when its provided synthetic entry passes the independent final check. Accounting still scores 6/20 with an existing minimum of 0 pending accountant sign-off; 14 accounting failures and the other failed cases are preserved, not declared accepted.

There are 113 scorer-failed cases plus 22 scorer-passing cases with failed citation metrics. Their current traces and per-case metrics are included. Coarse scorer success and aggregate evidence/treatment labels are not proof of completeness, accountant approval or live correctness.

Skips, expected failures and remaining assurance gaps

The 82 skipped and 22 expected-failure test IDs/reasons are identical to the prior review and to each other in both timezones: [exact records](/private/tmp/zoiko-phase1-remediation/skips-xfails-current.json). No new skip/xfail mark or expectation was introduced.

- 49 reporting acceptance cases remain explicitly unimplemented, including SOURCE, PERIOD, FRAMEWORK and SECURITY cases overlapping Phase 1 assurance.
- 11 PostgreSQL auth/tenant/scope/licensing integration checks and seven multi-process PostgreSQL/RLS cache checks remain unexecuted. Ordinary SQLite tests and prior privileged row-lock tests do not establish non-superuser RLS or new review-table privileges.
- Four socket/PostgreSQL tests, four local provider-configuration audits, two live-model tests, one OCR test and one original 80-case benchmark replay remain skipped. The 309 routing signatures are a different check.
- Two Phase 1 PostgreSQL tests remain opt-in/skipped in the ordinary suites; they were passed in the earlier dedicated acceptance run, not rerun here. The offline-gate test is skipped by default but was explicitly run here and failed.
- 20 strict expected failures concern unsupported numeric evidence matches (14 percentage, six amount/count); two concern native-language Austria aliases. They remain known defects/coverage limits, not passes. Country/language coverage is not universal.

Read-only verification and independent review

The plan binds an authoritative 22-version list and target tenant to a SELECT-only, repeatable-read snapshot. It captures source/version identity, submitter/approver/service-account metadata, source audit events, stored and independently recomputable original hashes, distinct publication/effective/reporting/supersession dates, all operation-specific rights, current status and deduplicated recorded answer/bundle/source usage. Missing/extra/invisible records and telemetry limits remain discrepancies, not forced counts or fabricated IDs.

Complete tenant-chain metadata requires explicit separate scope if not already authorized; a filtered source-event subset cannot establish full continuity. No write probes, privilege changes, schema installation, business endpoints that record usage, new content fetches/ingestion or status transitions are part of verification. The SQL has not been executed or target-schema certified.

No actual production inspection is authorized or performed. The queue contains zero verified records and one unresolved dependency for the expected legacy set of 22. Actual count, IDs, independent identities, rights, audit history, hashes, dates, statuses and usage remain unknown. Ranking six highest-use documents and assigning a reviewer/schedule requires verified records and reconciled usage; no placeholder document identities or dates are used.

Live accuracy evaluation, an authorized candidate endpoint/scoped credentials, EVAL_TENANT_ID, accountant-approved tenant-specific ground truth, verified inventory and independent-review arrangements remain explicit dependencies. Credential presence in this review process is not credential validation or a statement about every account; main-folder .env was not loaded. Production remains NO-GO until those dependencies and release failures are resolved through separate authorized review/evaluation.

Diff basis: remediation.diff is incremental to the captured worktree state at the start of this follow-up; only four implementation files, one new regression module and this report changed. The consolidated C1–C7 diff is relative to the earlier captured dirty worktree baseline and preserves unrelated pre-existing work. Neither patch authorizes copying into main, committing or deployment.
