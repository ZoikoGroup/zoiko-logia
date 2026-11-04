# Phase 1 follow-up evidence — 25 October 2026

Production remains **NO-GO**. This package is for technical review. No production data was inspected, no existing document status was changed, and no ingestion, deployment, commit, push, environment migration or copy into the main folder was performed.

## Measured result

The unchanged offline release gate still fails with **91 conditions; zero formal closures**. Every condition has an individual classification, severity, affected criterion, observed evidence, proposed disposition and next decision in `blocker-resolution-matrix.json`, `.csv` and `.md`. Classification does not waive a release criterion.

| Classification | Conditions | Disposition |
|---|---:|---|
| Deliberate offline-provider fixture failures | 63 | Recorded provider failures explain these observations; retain failures pending representative evaluation. This includes overlapping critical safety failures, which are not waived. |
| Missing validated request jurisdiction | 16 | Separate diagnostics demonstrate the same questions proceed with an explicit jurisdiction. Preserve original gate failures; resolve the request/dataset contract through review. |
| Unresolved tax-basis/mixed-task assumptions | 2 | Require reviewed include/exclude-tax assumptions and deliverables; no fabricated inputs or changed expectations. |
| Derived aggregate criteria | 9 | Remain failed until constituent results meet unchanged criteria. |
| Unavailable tenant ground truth | 1 | Blocked on authorized tenant access and approved truth; no substitute tenant or bypass. |

All 91 scored verdicts remain unchanged versus the prior gate report. Severity remains eight Critical and 83 High. The provider fixture intentionally supplies incomplete responses and no source corpus; it cannot establish live accuracy. The 16 explicit-jurisdiction diagnostics are separate evidence, not gate passes. The two assumption diagnostics remain unresolved.

## Narrow consistency correction

`backend/app/orchestration/router.py` now records `AnswerReceipt.review_required=true` when the API explicitly requests journal review. Before the fix, the missing and invalid journal cases failed this assertion (two failures, one valid-case pass). No new document review queue is created by this receipt field.

Nineteen new tests in `backend/tests/test_phase1_release_evidence.py` cover three credit-sale outcomes and 16 jurisdiction diagnostics. Missing/invalid journal responses retain verified arithmetic but have partial completeness, partially verified metadata, an incomplete requested journal deliverable, an explicit journal-review action, matching final audit completeness and a true receipt review flag. The API `outcome=answered` reflects retained arithmetic; the partial completeness and displayed Partial badge prevent it implying a completed journal. The valid journal control is complete. Tests bind answer text hashes, calculation fingerprints, verification payloads, persisted audit payload hashes and the synthetic tenant audit chain. A composed response may omit the optional top-level calculation object; its verification/audit calculation identifier is checked against the canonical calculation.

The read-only display-expression check evaluates existing frontend logic against saved synthetic responses: missing/invalid cases display “Partially answered — some parts incomplete” and Partial. It is not a browser test or live evaluation.

## Actual command results

| Run | Result |
|---|---|
| Focused consistency, jurisdiction, targeted-remediation and answer-status checks | 94 passed; 8 warnings |
| New evidence module | 19 passed |
| Final credit-sale audit/canonical-calculation checks | 3 passed; 16 deselected |
| Full backend, TZ=UTC | 4,906 passed; 82 skipped; 22 xfailed; 133 warnings; exit 0 |
| Full backend, TZ=Asia/Kolkata | 4,906 passed; 82 skipped; 22 xfailed; 133 warnings; exit 0 |
| Unchanged offline release gate | 1 failed; 91 blocking conditions; exit 1 |

Raw logs and JUnit XML are included. Backend runs used disposable SQLite databases; they do not demonstrate PostgreSQL concurrency, production migration or production restore behavior. Historic isolated migration/restore and frontend/routing results remain prior evidence and were not rerun here. No new frontend changes were made in this follow-up.

The 82 skips remain: 49 unimplemented reporting catalog; 11 auth/tenant/licensing PostgreSQL integration; seven multi-process RLS cache; four PostgreSQL sockets; four environment audits; two live models; one OCR; one original 80-case replay; two opt-in Phase 1 PostgreSQL tests; one default-skipped offline gate (run separately and failed). The 22 expected failures remain 14 small-percent numeric-evidence, six amount/count and two Austria native-language alias cases. These are unresolved assurance limits, particularly PostgreSQL/auth/RLS coverage and live-model behavior. They were not converted to passes. See extracted JUnit records.

## Verification and independent evaluation dependencies

The actual 22-document inventory and audit history are **unverified**. The read-only plan and SQL remain **UNEXECUTED**. No IDs, identities, hashes, dates, rights, statuses or usage counts have been invented. No document queue is prepared: verified records are empty, a named independent reviewer is absent, and no schedule or review window is agreed. Re-reviewing the highest-use six requires verified usage counts first.

Prepared blind worksheets freeze all 167 locally available non-gold cases, including 20 engineering accounting proposals. **Zero cases are accountant-approved.** Engineering proposed expectations are separate from the blind worksheet. A qualified independent accountant must supply expected results, resolve assumptions and sign the exact dataset/case hashes. Preparing worksheets does not complete that human task.

Live evaluation was **not run**. Approved secret-manager integration/references, scoped nonproduction target/tenant/account, exact candidate artifact/configuration and evaluation budget remain missing. No credentials were read from the main application environment, and no secret values were requested in chat. No live accuracy claim is made. The handoff records required human approval bindings and secret-management controls. The existing promotion workflow includes deployments and must not be triggered under this authorization. An unrelated deployed revision cannot validate this uncommitted worktree.

## Recommended next approval gate

Obtain named qualified independent reviewer/accountant identities, an agreed review schedule and signed ground-truth scope. Separately authorize the narrowly scoped read-only inventory plan with the authoritative 22 version IDs, tenant, snapshot/access controls and explicitly permitted audit metadata. Verify those records before preparing the independent review queue. Then authorize a bounded nonproduction live evaluation using approved secret references and an exact candidate binding. Keep all release criteria intact and resolve or explicitly review every remaining failure. No production release, status switch or migration is recommended.

## Evidence navigation

The archive includes the individual blocker matrix, raw gate report/traces, counterfactual diagnostics, before/after audit tests, full backend logs/XML, audit consistency summaries, display evaluation, frozen worksheets, readiness/dependency manifests, unexecuted read-only plan, source hashes and incremental implementation diff. The incremental diff covers this follow-up only; earlier C1–C7 and targeted changes remain in the worktree and are separately exported as the consolidated worktree diff.
