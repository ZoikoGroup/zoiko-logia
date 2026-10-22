# Reporting implementation plan — verified revision, 21 October 2026

Status: **planning only; decisions below remain proposed**. This update verifies the supplied review against the current repository and the local specification package. It does not authorise implementation, approve an accounting treatment, or certify a release. Reporting code, fixtures and tests remain unchanged.

The original complete phase plan was not included in the supplied review or found as a reporting plan in this repository. The phase sequence below is the revised planning baseline, incorporating the review's dependencies without claiming to reproduce every original phase verbatim.

## Verified inputs and existing work

Seven CSV/JSON assets are available in `/Users/kailanaresh/Downloads`: `report_catalog.csv`, `reconciliation_rules.csv`, `acceptance_test_cases.csv`, the three request/fact/manifest schemas, and `synthetic_display_example.json`. The catalog has 90 rows, RPT-001 through RPT-090; the rule CSV has ten rules; the acceptance CSV has 58 cases across 11 suites. ZL-RPT-002 through ZL-RPT-007 Word documents are available. **ZL-RPT-001 remains missing.**

The review's count of “five” assets is incorrect. The existing specification README already anticipates a separate `schemas/` directory; preserve that organisation rather than introduce a second contract location. Copy no assets in this planning-only change. Future ingestion must preserve received bytes, record hashes, document version and approval status, and keep approved revisions immutable.

The Word documents' contract, framework, QA, presentation and implementation sections were inspected where relevant to these decisions. They are proposed baselines, not evidence that legal applicability, licensing, professional review or production readiness has been approved. External standards links were not independently researched as part of this local code/plan review.

Existing code in `backend/app/domains/reporting/` already provides a pure-library path:

- Strict decimal-string journal inputs; source-ID/version deduplication and conflict handling; cutoff and orphan-reversal checks; deterministic SHA-256 snapshot sealing.
- Versioned account mapping; unmapped accounts become blocking exceptions rather than “Other”.
- Decimal facts and BS/P&L/CF/equity compilation from one snapshot; TB-001, BS-001, PL-001, CF-001 and EQ-001 reconcilers with explicit deltas.
- A synthetic `golden_route_001` and mutation tests; at most `DRAFT_RECONCILED`, with no reviewed/issued output.

The existing suite passed **20 tests in 0.85 seconds**, with live model transport disabled. This is not execution of the 58 CSV acceptance cases. Existing reversal checks establish that the referenced journal exists, not full certification of reversal amount, timing or linkage semantics. A frozen dataclass/hash also does not establish database append-only enforcement.

## Corrections and qualifications to the supplied review

| Topic | Verified result | Planning consequence |
| --- | --- | --- |
| Billing idempotency | No billing replay mechanism was found. `IdempotencyRecord` has a unique tenant/key constraint. | Reuse the persistent reservation/replay concept, not an assumed billing implementation. |
| Command-center header | `command_center/router.py` accepts and audits `Idempotency-Key`, but does not enforce same-key replay or changed-body rejection. | A header is not sufficient; implement and test reservation, request binding and replay explicitly. |
| Existing idempotency helpers | `claim_idempotency` and `store_idempotency` commit internally; helpers are designed for Ask Kriton. | Assess transaction ownership, key namespace, actor/operation scope, expiry and in-flight recovery before reuse in reporting. |
| Outbox and audit | No outbox implementation was found. `record_event_async` normally commits internally; in batch mode it buffers, and `commit_audit_batch` commits/retries. | Reuse the hash-chain envelope, but do not assert atomicity merely because the same session is passed. Establish one explicit unit of work and test rollback/retry of both state and audit. |
| FRQA-0054 | The CSV literally names an unavailable outbox, while this repository has an audit ledger. | Record an architecture interpretation of the failure boundary, retain the original row, and prove no report-state/issue success without the required durable audit write. |
| Database arithmetic | SQLite is the configured default; no SQLAlchemy `Numeric` amount column was found in application models. Runtime configuration can override that default. | Decide exact persistence separately from the existing Decimal computation. Use canonical decimal strings for portable exact storage, or explicitly require and test PostgreSQL exact numeric storage. No float/SQLite numeric-affinity conversion. |
| Rule IDs | CSV: TB-001, BS-001, CF-001, EQ-001, CI-001, INT-001, FMT-001, AUTH-001, DISC-001, TXT-001. PL-001 and CF-002 are absent. | Preserve the CSV. Keep implemented PL-001 identified as a playbook/local extension pending reconciliation. Do not implement CF-002 without an agreed invariant and ID. |
| Feature rollout | Existing configuration switches are available; no general feature-flag registry/evaluator was found. | Prefer proposed default-off reporting settings and a certified combination allowlist initially; add a flag service only if requirements justify it. |
| API prefix | Platform routers mount under `/api/v1`; the specs illustrate `/v1/reports`. | Resolve by ADR before public contracts; proposed local path is `/api/v1/reports`. |
| Request scope | The received JSON Schema has no `jurisdiction` property and rejects additional properties. ZL-RPT-003 describes jurisdiction in the conceptual request. | Resolve a schema revision or a pinned server-side jurisdiction-resolution contract; never silently drop jurisdiction or accept an undeclared field. |
| Template identity | Catalog IDs are RPT-001…RPT-090, but the request schema permits arbitrary strings and ZL-RPT-003 illustrates a semantic ID. | Approve catalog/alias/version mapping and allowlist semantics before route support is claimed. |
| Gate names | ZL-RPT-005 and ZL-RPT-007 assign different meanings to G1/G2 and other gate numbers. | Use document-qualified gate IDs and approve a crosswalk; local “G1/G2” completion is not completion of the QA document's gates. |

Audit atomicity is a substantive correction to the review: rollback/retry paths can discard pending business state while re-staging audit rows, and earlier internal commits cannot be undone by a later failure. A future reporting transaction must own commit boundaries, avoid unsafe helper commits, preserve tenant RLS context, and serialize conflicting chain/state updates. This is a design requirement, not an assertion that reporting persistence already fails a runtime test; persistence does not exist yet.

## Phase sequence and exit evidence

| Phase | Work to plan | Exit evidence / dependency |
| --- | --- | --- |
| 0 — Decisions and controlled inputs | Resolve the decision register below; obtain ZL-RPT-001; inventory/hash the available assets and approvals; define supported report combinations and gate crosswalk. | Named owners and recorded decisions. Unaffected local contract analysis may proceed; missing architecture is not permission to infer approval/issue rules. |
| 1 — Contract alignment and acceptance inventory | Preserve the received schemas; align the existing facts; add the second synthetic fixture and truthful 58-case coverage inventory. | Contract round trips, exact values, validation negatives, fixture lineage and explicit unsupported statuses. No API/database changes in this phase. |
| 2 — Request/authentication/idempotency boundary | Proposed `/api/v1/reports`; reuse `get_current_user`/`require_permission`; server-resolve tenant and role, authorise entities and sources, reject changed-body key reuse. | Concurrent same-key requests yield one report/job; foreign tenant/actor and changed payload tests; deterministic replay/in-flight recovery. Header-only acceptance is insufficient. |
| 3 — Durable source truth | Persist existing snapshot/import receipts; tenant/entity scoping; read-only imports; version/cutoff/reversal controls; append-only triggers and revision lineage. | Trigger-backed mutation rejection, same-source stable seals, new revisions for changed inputs, real application-role RLS and isolation tests. |
| 4 — Durable compiler and lifecycle | Persist existing facts and rule outcomes, finish missing rule applicability, add explicit allowed transitions and compare-and-swap revision/state checks; couple state/idempotency/audit writes deliberately. | Competing transitions have one winner; every failed audit transaction leaves no committed state/issue change; retry tests prove business state and audit remain paired. Existing arithmetic stays in use. |
| 5 — Framework and disclosures | Versioned, effective-date-aware rule packs, notes/applicability, source rights and certified support matrix. | No arithmetic-only financial statement is promoted as a complete framework report. Missing notes/applicability remain blocking. |
| 6 — Constrained narrative | Fact-linked numerical claims, typed omissions and eligible citations; provider-failure handling. | Unsupported claims are rejected; unavailable narrative cannot masquerade as a complete report; FRQA-0055 numeric-only recovery does not erase disclosure requirements. |
| 7 — Render/export parity | One frozen semantic model to HTML/PDF/DOCX/XLSX and other explicitly supported formats; display-scale/rounding policies. | FMT-001 and export mutations; disclosed rounding residuals; physical-page and actual renderer inspection; no independent recalculation in renderers. |
| 8 — Job/issue operations | Cancellation, safe checkpoints, revocation, retries, audit failure and issue deduplication. | FRQA-0054…0058 plus real HTTP/PostgreSQL isolation tests; an unavailable dependency never produces a false success. |
| 9 — Scoped release | Proposed default-off settings and certified template/framework/jurisdiction/entity/period/output combinations; operational budgets and rollback evidence. | Independent review, applicable gates, explicit release approval. No deployment/configuration change is authorised by this plan. |

Phases 3 and 4 extend the current library; they do not recreate ingestion, mapping, calculations or reconciliation in a parallel reporting engine. Approval/issue, external source eligibility, access control and certified scope remain separate from arithmetic success.

## Adjusted Phase 1 deliverables

1. **Register all seven assets.** Future locations: the three CSVs and display example under `backend/app/domains/reporting/spec/`, the three JSON Schemas under `spec/schemas/`, with provenance/version/checksum records. Resolve contradictory requirements through approved revisions or ADRs; do not edit controlled files to make tests pass.
2. **Align existing facts rather than replace the compiler.** Derive strict Pydantic request/fact/manifest boundary models from the received contracts and review generated behaviour. Map `concept` to `concept_id`, entity identity to `entity_id`, snapshot hash/ID to `source_snapshot_id`, mapping version to `account_map_version`, and instant/duration dates to the schema's `period` union. Add explicit basis and value status. Preserve label/source-journal/lineage metadata in an internal provenance structure where the wire schema does not permit those fields. Decide identity/version migration before changing fact IDs.
3. **Add semantic contract checks.** Dates/ordering, instant versus duration, exact decimal strings, currency and basis consistency, valid nonempty identifiers, and value-status/value consistency need tests beyond generated types. A missing value must remain missing, not zero; zero needs explicit provenance. Do not use the presentation scale to multiply stored facts. Jurisdiction and template-ID conflicts remain decisions, not hidden schema extensions.
4. **Retain `golden_route_001` unchanged and plan `golden_route_002`.** The latter is a newly constructed, explicitly synthetic ledger designed to reproduce the separate display example, not a recovered original ledger. Pin its own period and opening-balance assumptions, journals, map and independently reviewed expected values. Targets include assets 780,000, equity 360,000, retained earnings/net income 120,000, and cash 150,000 + 140,000 − 50,000 − 40,000 + 0 = 200,000 USD. The first fixture's equity is 575,000 and remains valid for its own inputs. Numeric reconciliation and report completeness must be separate assertions: the display example stays `DRAFT_INCOMPLETE` without required notes. Decide where that completeness gate belongs; it does not exist in the current pipeline merely because the example JSON labels it so.
5. **Map every original acceptance row to evidence.** Preserve all 58 IDs, descriptions, mutations and expectations. Record owner, implementation phase, exact fixture, executable test, current result and blocker. Bridge existing tests only where the mutation and expected behaviour genuinely match. New tests must assert behaviour, not just CSV loading or a constant false condition.
6. **Treat unimplemented cases honestly.** Prefer a visible backlog for cases without an executable path. If an executable regression is intentionally `xfail`, require a specific reason/issue and strict unexpected-pass handling. Required acceptance failures and unsupported cases remain release blockers, regardless of pytest exit status. Twenty library passes plus expected failures are not 58 completed acceptance tests.

Acceptance suite counts: NUMERIC 7; CASHFLOW 5; PERIOD 5; FX 5; CONSOLIDATION 5; FRAMEWORK 6; SOURCE 5; LLM 5; SECURITY 5; EXPORT 5; OPERATIONS 5.

## Decision register — proposed, not approved

| Decision | Alternatives / recommended direction for review | Owner |
| --- | --- | --- |
| Duplicate posting versus request replay | Distinguish duplicate ledger rows from an idempotent API retry. FRQA-0004 requires BLOCK; playbook §15.2 allows no double count or block. Proposed: block duplicate postings within an import, replay the same request without reimporting. Current identical-row ignore behaviour remains unchanged pending the decision. | Accounting Domain + Architect |
| Jurisdiction contract | Approved schema revision with explicit field, or documented server resolution pinned in the manifest; neither silent defaulting nor permissive extras. | Architect + Rules |
| Template/API vocabulary | Catalog IDs, semantic aliases, versioned support matrix, `/api/v1` prefix and error/status contracts. | Architect + Product |
| Exact persistence | Portable canonical decimal strings with application arithmetic, or explicit PostgreSQL exact numeric requirement with precision/scale and database tests. | Data + Reporting |
| Transaction and event boundary | Existing hash-chain ledger with one reporting-owned unit of work; decide flush/enqueue/commit integration and retry semantics before implementation. If external reliable delivery is later required, define it separately; the ledger is not an outbox. | Platform + Security |
| Reconciliation identifiers | Retain the ten CSV IDs; reconcile local PL-001 and any proposed CF-002 with the playbook and assign authoritative definitions. | Accounting Domain + QA |
| Fact extensions and display completeness | Identity/basis/status mapping, opening-date semantics, retained internal lineage, and a completeness gate that can keep a reconciled numeric draft incomplete. | Reporting + Accounting Domain |
| Scale/contra controls | Define FRQA-0003 storage-versus-presentation scale checks, explicit contra polarity and FRQA-0006 display residual handling. Do not assume they are already covered. | Reporting + Design/QA |
| Gate crosswalk and certification | Resolve conflicting gate numbers between ZL-RPT-005 and 007; retain independent finance sign-off and approved scope. | QA + Architect + Accounting Domain |
| Rollout mechanism | Initial configuration switches plus certified allowlist versus a later flag service. No route becomes “supported” from a switch alone. | Platform + Operations |

## Verification record and limits

Source code reviewed includes reporting modules/tests, `orchestration_state/models.py`, `orchestration/identifiers.py`, `command_center/router.py`, `audit_ledger/event_envelope.py`, `identity/rbac.py`, `core/config.py` and `requirements.txt`. The listed PDF/DOCX/XLSX libraries already exist; that does not establish implemented or verified report exports.

See [source checksums and review metadata](review-evidence-2026-10-21/review-evidence.json) and the [unchanged reporting test run](review-evidence-2026-10-21/golden-route-tests.log). The review inspected local Word paragraph/table text and the available CSV/JSON assets, not rendered page layout or current external accounting authority. No Groq/model calls, database writes, asset copying, implementation/test changes or deployment were performed.
