# Kriton enterprise implementation plan for developers

**Status:** proposed engineering plan, 18 September 2026.

**Inputs:** *ZoikoLogia AI Engineering Guideline* (15 September 2026, v1.0) and this repository's code.

**Decision:** this repository is a workable foundation. It is not yet an enterprise release. The guideline is a design input, not evidence that any feature or approval is complete.

## 1. Complete rough approach

Read this section before taking a feature ticket. It describes how the whole platform should work and the order in which to build it. Section 2 then describes F0 through F10 one at a time, including existing code and exact work to add.

### 1.1 Choose a bounded first release

The first release is **read-only** and limited to named jurisdictions, accounting frameworks, licensed sources, and professional reviewers. It supports three workflows:

1. **Accounting-policy research:** answer a question for a specified framework and effective period with precise source passages and any contrary or superseded guidance.
2. **Document-to-evidence extraction:** extract facts from an uploaded file and link every reported fact to its page, sheet, row, or region. Customer documents are evidence about the customer; they are not governing authority.
3. **Reconciliation assistance:** validate inputs, perform decimal arithmetic with a versioned tool, show unmatched items, and send consequential work to a reviewer.

Kriton may draft and explain. It may not post journals, file returns, submit payroll, issue assurance opinions, move funds, or send external communications. Add such actions only under a separate design and authorization decision. Do not assume that a global architecture means every jurisdiction and language is supported at launch.

Use exact search, approved templates, structured reports, deterministic tools, or human escalation when generation adds no value. Treat language models, retrieval, fine-tuning, and agent workflows as separate choices; model size and public rankings alone do not justify a deployment.

### 1.2 Establish contracts before changing the pipeline

Agree on the first jurisdiction, framework, period rules, source owners, data classes, reviewer roles, critical errors, and release thresholds with Product, domain assurance, architecture, security, privacy, source-rights, and operations owners. Reconcile the guideline with ZL-T0-08 and ZL-ENG-03/05/06 before declaring a baseline.

Version these contracts together:

- `TaskContext`: trusted actor, tenant, engagement, role, purpose, data class, task type, jurisdiction, framework, entity, period, currency, language, and intended use.
- `EvidenceItem` and `EvidenceBundle`: authorized source or customer-file identity, exact version/hash, passage locator, authority class, rights, applicability, retrieval time, and index version.
- `CalculationResult` and `ChartSpec`: validated inputs, source references, decimal outputs, units, rounding, rule/tool version, and period-aligned chart data.
- `AnswerResponse`: explicit status, draft or conclusion, assumptions, limitations, material claims, evidence and calculation references, review requirement, and audit ID.
- `ReleaseManifest`: exact model deployment, prompt, policy, retriever, source snapshot, tool/rule, and evaluation versions.

Maintain existing `POST /api/v1/orchestration/ask` during transition. Add versioned fields behind a feature flag, migrate stored answers, and remove legacy fields only after a documented compatibility period. Proposed new tables and routes in this plan require architecture review; they are not present just because they are named here.

### 1.3 Implement one governed request path

The production request path should run in this order:

1. Verify the token and resolve actor, tenant, engagement, role, and purpose from server-side state. Reject forged or revoked scope.
2. Resolve workflow, jurisdiction, framework, effective period, currency, and data classification. Ask a specific clarification when a material fact is absent.
3. Apply preliminary safety screening **before** retrieval. The policy service, not the model, decides allowed routes and tools.
4. Build a retrieval plan and filter tenant, engagement, rights, data class, jurisdiction, framework, and effective dates **inside candidate queries**. Repeat rights checks before model transmission and disclosure.
5. Retrieve lexical and semantic candidates for the pilot hybrid baseline. Rerank only eligible results. Prefer applicable governing authority over a merely similar passage. Record exclusions and conflicts. A simpler retrieval mode needs an approved evaluation showing it meets the same gate.
6. Freeze a versioned evidence bundle with exact passage locations and hashes. Keep customer facts, governing sources, external web material, and tool outputs in separate fields.
7. Classify substantive risk using the effective context and retrieved evidence. Select `LLM`, `CLARIFICATION`, `REFUSAL`, `HUMAN_REVIEW`, or `SECURITY_INCIDENT`. Return an explicit no-source status when evidence is insufficient.
8. Select a model deployment eligible for that task, data class, region, source rights, and tool set. A fallback is independently checked; if no deployment qualifies, return unavailable or queue for review.
9. Let the model draft language and propose typed tool inputs. Treat retrieved text and tool results as untrusted data, not executable instructions. Validate inputs and, when required, obtain confirmation before invoking allowlisted deterministic tools through service code. The model cannot authorize its own action or alter a recorded result.
10. Validate schema, claim-to-span support, quoted text, source applicability, calculations, units, chart values, display rights, and professional boundaries. Unresolved material conflicts or unsupported claims go to clarification or human review.
11. Persist the validated answer, evidence/tool/model manifest, and ordered audit event **before** returning a substantive answer. If durable recording fails, return an operational failure. Do not stream unvalidated conclusions.
12. On later evidence access or export, recheck current rights. Record reviewer edits and approvals separately from the model draft and preserve the original release record.

This path is the integration contract for all three pilot workflows. A source connector or chart renderer cannot bypass it merely because it returns useful content.

### 1.4 Build in vertical slices

Build the first policy-research slice end to end for one approved jurisdiction and a small source set. Demonstrate a supported answer, no-source result, conflict, superseded source, revoked licence, and cross-tenant denial. Then add document extraction using the same evidence and response contracts. Add reconciliation with deterministic arithmetic and review. Qualify a second model provider and run the complete evaluation corpus only after the workflows use the same controlled path.

Start evaluation-case authoring and migration work in parallel with contracts. Do not wait until the end to discover that a response cannot be scored or a schema cannot be upgraded. Put new retrieval, response, and gateway behavior behind flags. Compare against a frozen baseline, shadow-test, canary to a bounded cohort, and keep a rollback route.

Bound each workflow with explicit states, maximum retrieval passes and tool calls, token and runtime budgets, retries, cancellation, and durable resume/failure records. Compare direct synthesis with a bounded retrieve–analyze–verify workflow on the same cases. Prefer predefined steps for repeatable work; a dynamic agent loop must earn its added cost and risk in evaluation.

### 1.5 Use measured release gates

Create at least the guideline's proposed **300 expert-authored starting cases** across the three pilot workflows, plus isolation and adversarial suites. This is a starting scope, not proof of production reliability. Freeze a separate release holdout and check contamination by engagement, document family, and time. Score actual candidate executions; never use fixed or simulated metrics as a release result.

Before the pilot, domain owners preapprove critical-error definitions and task-specific thresholds. Report retrieval recall, authority/date selection, citation support, numeric correctness, material omission, correct abstention, useful completion, reviewer minutes, p95 latency, and cost per accepted task by workflow, jurisdiction, language, and risk. **Any observed critical authorization, rights, fabricated-authority, or material calculation failure blocks the candidate release.** Zero observed failures in a finite suite is a release condition, not a zero-risk claim.

Also rehearse provider/search/database outage, ineligible fallback, audit failure, cancellation, source revocation, backup restore, rollback, and incident response. A named release authority records the pilot go/no-go decision.

Compare at least two contractually eligible model deployments with evidence and tools held constant. If authorized product access exists, separately compare Kriton workflows with Harvey, CoCounsel Tax, and LexisNexis Protégé on accepted work product, source entitlements, review effort, and supported tasks. Label unavailable tests as unavailable; do not infer superiority from vendor claims or public rankings.

### 1.6 Follow one engineering pattern for every feature

For each feature: define a typed contract and failure states; add a reviewed migration if storage changes; implement service authorization and rights checks; wire a versioned API and UI state; write durable audit/telemetry; test positive and negative cases; run an integration or expert check where unit tests are insufficient; shadow-test; then enable behind a flag. Additive schema changes should follow **expand → backfill → validate → cut over → retire**. Record the owner and rollback path before enabling a pilot feature.

Use models for interpretation, synthesis, and drafting. Use services for permissions, source authority, arithmetic, approvals, and record integrity. Improve evidence and context before considering fine-tuning. Add vector retrieval, graph reasoning, agents, distillation, or self-hosting only if a measured failure or economic requirement justifies them.

Maintain six coordinated engineering artifacts as the code evolves: (1) architecture decisions and model routing register; (2) task, evidence, and response contracts; (3) source/rights register with quality-gate mappings; (4) versioned evaluation corpus and release scorecard; (5) security, review, and incident control specification; and (6) release manifest and operations runbook. Update existing estate documents where they already own an artifact.

Fine-tuning is post-baseline work only. Require a named residual failure, approved training and teacher-output rights, expert-reviewed examples, a frozen holdout, leakage checks split by engagement/document family/time, and an economic hypothesis. Test memorization, privacy leakage, abstention, and regression. Distillation or self-hosting also needs a measured quality/cost or contractual case, operating plan, and requalification.

## 2. Feature-by-feature developer plan

The sections below are in dependency order. Each feature states **what exists**, **what to implement**, **how to implement it**, and **how to prove it is done**. File paths are code touchpoints, not a claim that every named capability already exists.

### F0 — Pilot scope and task contracts

**What exists:** `backend/app/orchestration/schemas.py` defines ask, route, source-bundle, citation, and response shapes. `orchestration/service.py` runs the ask workflow. The current request does not carry a complete, trusted professional task context; its `conversation_id` is not server-side conversation memory.

**Implement:** a versioned `TaskContext`, three +`TaskSpec` records, and a context-completeness decision. Define required framework, period, entity, currency, source type, tool, and review role for each workflow. Record unsupported jurisdictions, languages, and task variants. Publish JSON examples, an architecture decision register, and a mapping from ZL-ENG-05/06 source-precedence and information-quality rules to machine checks, domain review, owners, and failure routes.

**Approach:**

1. Add Pydantic context/spec contracts alongside `orchestration/schemas.py` or in a dedicated contracts package.
2. Resolve actor and tenant from `get_current_user`; authorize requested engagement and other context on the server. Add a context resolver before retrieval in `service.py`.
3. Store task-spec version and effective context on every task. Add a small context selector to `frontend/app/ask-kriton/page.tsx` that displays the server-resolved values.
4. Add table-driven tests for missing material facts, unsupported context, and forged tenant/engagement values.

**Done when:** owners sign the three task contracts; the API gives a specific clarification for a missing framework or period and rejects forged scope.

### F1 — Identity, engagement, and authorization

**What exists:** Supabase token verification, identity models/RBAC, tenant-aware database sessions, and RLS for selected source/document tables in `backend/app/main.py`. Existing RLS and uploader rules do not prove engagement isolation across every store and export.

**Implement:** engagement membership and grants, operation-level authorization, revocation, and scope enforcement for SQL, object storage, search, caches, jobs, model context, exports, and replay.

**Approach:**

1. Add `engagements`, `engagement_memberships`, and versioned grants through Alembic. Backfill only with an approved mapping; do not invent ownership for legacy records.
2. Implement `authorize(actor, operation, resource, effective_context)` in `identity/rbac.py` with allow/deny and reason code. Call it at each protected route and before model transmission/export.
3. Include tenant, engagement, rights version, and source version in cache and index keys. Migrate RLS policies to reviewed migrations and test least-privilege DB roles.
4. Add cross-tenant, same-tenant different-engagement, revoked-user, cache-hit, worker, export, and audit-replay tests. Inspect mocked outbound model payloads for leakage.

**Done when:** denied content never reaches retrieval results, model context, charts, exports, caches, or replay in the isolation suite; revocation meets the approved service target.

### F2 — Source register, licences, and provenance

**What exists:** `source_library/models.py` stores sources and versions, `massarius/license_gate.py` screens some use rights, and source approval routes exist. Uploaded customer files live separately in `documents/`, which is the right authority distinction.

**Implement:** publisher/owner, authority class, framework/language, effective dates, supersession links, content hash, publication/retrieval times, passage IDs, approval and quality state, and versioned rights for ingestion, indexing, model transmission, display, summary, export, retention, and training. Unknown rights deny that use. Preserve original-language source text and identify translations as derived evidence.

**Approach:**

1. Add source-rights and passage records through Alembic; keep approved `SourceVersion` content immutable.
2. Extend `source_library/service.py` and its router with registration, file/URL validation, deduplication, passage extraction, and maker-checker approval.
3. Provide one `can_use(source_version, context, operation)` decision with reason codes. Enforce it before indexing, retrieval, model context, citation display, and export.
4. Add freshness, expiry, supersession, and revocation jobs; find bundles and released answers affected by a source change without rewriting old records.

**Done when:** a source is traceable from original bytes to approved passage and citation; a full rights matrix, unknown-rights denial, and revocation tests pass.

### F3 — Hybrid retrieval and evidence bundles

**What exists:** `orchestration/retrieve.py` explicitly calls its governed source method `keyword_mvp`; `massarius/bundle_builder.py` creates a frozen bundle shape. Uploaded documents have separate search. Live SearXNG and statistics connectors currently enter answer composition outside the registered source bundle.

**Implement:** context-driven `RetrievalPlan`, filtered passage index, lexical and semantic candidates, reranking, applicability checks, contrary/superseded evidence, and an immutable bundle manifest for every professional answer. External data must have equivalent provenance/rights or remain outside material conclusions.

**Approach:**

1. Create stable `passage_id` records with source version/hash, locator, effective interval, tenant/engagement, and rights metadata. Backfill only approved pilot sources.
2. Add rights-filtered lexical retrieval first, with fixed top-k and timeout. Evaluate it on expert-labelled cases.
3. Add vector candidates behind a rollout flag, then evaluate the complete hybrid path against the lexical baseline. Filter rights and scope in the candidate query; rerank only eligible candidates. A lexical-only production mode requires a documented exception showing the same release gates pass.
4. Apply jurisdiction, framework, entity, period, authority, and supersession rules separately from similarity score. Freeze selected/excluded IDs, reasons, hashes, and index version in the bundle.
5. Integrate web/live connectors through this policy or prohibit them from governing professional claims. Preserve numeric source definition, period, publication state, original language, and any labelled translation. Instrument missing sources, stale versions, OCR loss, table-header loss, chunk-boundary/cross-reference loss, retrieval failure, and context truncation as separate failure reasons.

**Done when:** recall and applicability meet F0 thresholds; excluded text never reaches a model; a released bundle can be replayed after the index changes.

### F4 — Structured answer and release validation

**What exists:** `AskKritonResponse`, a citation list, `composition_validator.py`, and `massarius/answer_validator.py`. Current checks do not establish that every material claim is supported by the *right* passage or recorded calculation. The frontend can show a model-knowledge answer with no sources.

**Implement:** explicit `answered`, `partial`, `no_source`, `clarification`, `review_required`, `refused`, and `operational_failure` status; structured assumptions and effective context; typed material claims; claim-to-passage/tool binding; mechanical and semantic release gates; durable audit-before-release. Show evidence completeness and calibrated route states, not an invented percentage from model self-assessment.

**Approach:**

1. Extend `orchestration/schemas.py` and keep old `outcome`/`route` fields during compatibility migration.
2. Draft claims as `source_fact`, `customer_fact`, `calculation`, or `inference`, each with supporting IDs and exact spans or result IDs.
3. Validate schema, authorization, source rights, span existence, quote text, effective period, units, calculations, and chart points. Send unsupported material conclusions or unresolved conflicts to clarification/review.
4. Persist the validated answer and audit/release manifest before returning it. Use a transaction or durable outbox for consistency; audit failure returns operational failure.
5. Make the frontend render status and support data directly, rather than infer it from prose or citation count.

**Done when:** fabricated citation, irrelevant span, altered number, revoked source, conflict, and audit-outage cases cannot produce a released substantive answer.

### F5 — Deterministic calculations, statistics, and charts

**What exists:** `orchestration/live_data.py` calls exchange-rate, statistics, and market connectors. `AnswerRenderer.tsx` renders chart JSON generated in answer text. There is no general recorded accounting-calculation service; model-authored chart values remain a risk.

**Implement:** a `calculations/` domain using `Decimal`, a typed observation contract, versioned calculation runs, reconciliation outputs, and charts generated from recorded values. First operations: sum, difference, variance, percentage, grouping by period, and matching with explicit unmatched items.

**Approach:**

1. Define typed inputs, currency, unit, scale, rounding, rule version, effective date, source IDs, and explicit error states. Reject incompatible units/currencies, duplicate rows, invalid periods, and division by zero.
2. Let the model propose inputs only. Validate them in service code and, where needed, obtain user/reviewer confirmation before execution. Persist exact inputs and outputs.
3. Convert source observations to typed provider/indicator/period/unit/value records with missing-value state. Align comparisons only on common observed periods.
4. Generate `ChartSpec` and a table from the recorded dataset. Update the frontend to render this typed payload and show value-to-source drilldown. Restrict legacy fenced charts to clearly unverified drafts during migration.

**Done when:** golden boundary cases pass; every chart/table point exactly equals a stored observation or calculation; missing data produces a visible no-data response, never invented figures.

### F6 — Document extraction and evidence review

**What exists:** `documents/extract.py`, `chunker.py`, `service.py`, and storage handle text PDFs, DOCX, spreadsheets, slides, CSV, and text. Scanned PDFs currently report that OCR is needed. Chunks have human-readable locators but not full page/row geometry.

**Implement:** secure asynchronous ingestion, OCR, layout and table structure, precise page/sheet/row/box location, partial-coverage reporting, and reviewer corrections with original/corrected versions.

**Approach:**

1. Add `uploaded → scanning → extracting → needs_review/ready/failed` states, resource limits, parser version, job ID, and retry rules. Never retrieve unscanned or failed files.
2. Add a provider-neutral OCR adapter selected after accuracy, residency, privacy, and cost tests on the pilot documents.
3. Preserve original bytes/hash, table headers, typed numeric values, sheet/row/column or page bounding boxes, and extraction confidence signals. Mark truncation and unreadable regions as partial.
4. Build a reviewer viewer that opens each cited region and records corrections, reviewer, reason, and timestamp. Treat corrected customer facts as evidence, not professional authority or automatic training data.

**Done when:** cited locations open the right region, partial documents are visibly partial, and expert-scored extraction accuracy meets the predeclared pilot threshold.

### F7 — Policy-driven model gateway

**What exists:** `model_gateway/` has several provider adapters and model/prompt rows. `service.py` largely chooses the first configured provider and can fall back from Gemini to Groq without a full per-task data-class/region/rights policy decision.

**Implement:** approved deployment registry and due-diligence record, eligible model selection, typed provider errors, tool allowlists, bounded workflow states and budgets, qualified fallback, and a release manifest with exact model, prompt, policy, retriever, reranker, corpus, tool, and calculation-rule versions.

**Approach:**

1. Extend `model_gateway/models.py` for exact deployment ID, provider, region, permitted data classes, task coverage, allowed tools, retention/training terms, approval state, and evaluation manifest. Existing rows are inactive until reviewed.
2. Replace environment-key precedence with `select_eligible_deployment(task_context, route)` and persist its decision reason.
3. Standardize adapter timeout, usage, cancellation, retryability, and errors. Record task state, maximum retrieval/tool calls, token/runtime limits, and retry ceilings. Do not turn an `[Error ...]` string into an answer. Enforce tool limits outside the model.
4. Qualify at least one independent fallback when contractually and technically eligible. Otherwise return unavailable or queue for review; never silently broaden data access.

**Done when:** outage, quota, region mismatch, data-class denial, and tool-escalation tests pass; restricted content never reaches an ineligible provider.

### F8 — Real evaluation and release qualification

**What exists:** `evaluation/service.py` and evaluation models/routes exist. The service currently derives some metrics from safety checks on gold answers and supplies fixed/simulated metrics for others, including an empty dataset. Those values cannot approve a release.

**Implement:** versioned expert corpus, frozen development/release holdouts, actual candidate execution, per-case traces, reviewer judgments, observed metrics, slice scorecards, and a promotion gate that rejects incomplete runs.

**Approach:**

1. Import at least 300 expert-authored starting cases across the three workflows, plus isolation and adversarial cases. Record source snapshot, context, expected facts/calculations, acceptable abstentions, risk, reviewer provenance, and contamination checks.
2. Execute the real orchestration path against a frozen model/prompt/policy/retriever/source/tool manifest. Persist evidence, response, latency, token/cost, and error per case.
3. Collect qualified reviewer verdicts and adjudicate disagreement. Compute retrieval recall, applicability, claim support, numeric correctness, critical escapes, selective accuracy, useful completion, reviewer minutes, and cost from actual results.
4. Mark zero-case/incomplete runs `not_evaluated`. Require approved thresholds, contamination check, no observed critical escape, and named promotion authorization. Shadow and canary test approved candidates.

**Done when:** every scorecard number traces to case-level execution and reviewer evidence; no default or invented metric can pass the gate; weak jurisdiction, language, or risk slices cannot be hidden by an overall average.

### F9 — Review, audit, incidents, and lifecycle

**What exists:** escalation/review models, `audit_ledger/`, replay, notifications, and incident modules exist. Their integration, concurrent audit ordering, rights-revocation impact, retention, and reviewer workflow need end-to-end proof.

**Implement:** complete reviewer evidence packet, maker-checker decisions, durable replay manifest, defect/affected-answer tracing, retention/legal hold, incident escalation, and operational alerts.

**Approach:**

1. Extend review cases with effective context, draft, supporting/contrary passages, calculation inputs/results, assumptions, required role, SLA, edits, and optimistic locking.
2. Link ordered audit events to answer, evidence and rights versions, model/prompt/policy IDs, tool results, reviewer actions, and exports. Make writes idempotent by task/event key and verify chain behavior under concurrency.
3. Add source-revocation and defect impact lookup; handle retention, deletion, legal hold, and incident response under access control without rewriting historical decisions. A critical escape suspends the affected route pending incident review.
4. Update review and audit UI to distinguish draft from approved output and block self-approval or unauthorized export.

**Done when:** a reviewer can decide from a complete packet, replay reconstructs a released answer, and outage/incident exercises locate affected work products.

### F10 — Migrations, CI, telemetry, and recovery

**What exists:** Docker Compose, Railway backend config, Alembic files, and startup `create_all`/ad hoc migrations in `backend/app/main.py`. They support development but are not yet a proven production migration and recovery process.

**Implement:** reviewed migrations, CI, artifact and release-manifest controls, staging parity, secure telemetry, backup/restore, rollback, kill switch, and measured budgets.

**Approach:**

1. Inventory startup DDL. Move managed-environment schema changes into Alembic revisions using expand/backfill/validate/cutover. Rehearse against a scrubbed production-like snapshot before removing startup DDL.
2. Add CI for Python/TypeScript checks, focused and integration tests, tenant/rights isolation, migration upgrade, dependency/secret scanning, and build provenance. Protect promotion and policy branches.
3. Trace task/correlation ID, stage latency, source counts and failures, model/tool route and usage, audit status, review backlog, freshness, and cost without logging raw customer content or secrets. Cost per accepted task includes model, retrieval, licensing, infrastructure, and reviewer labor; it is an internal measure unless commercial owners approve billing use.
4. Keep local Compose for development; use production-like identity, DB roles, storage, and egress controls in staging. Rehearse provider/search/database outages, restore, rollback, and the pilot kill switch.

**Done when:** clean install and upgrade pass, backup restore and rollback are measured, and pilot health/cost decisions use observed telemetry.

## 3. Delivery order and developer definition of done

Implement F0 first. F1 and F2 can run in parallel after F0; F3 depends on both. F4 depends on F3. F5 and F6 can run in parallel after the F4 contracts stabilize. F7 can start after F0 and F1; its production routing waits for policy approval. F8 case authoring starts with F0, but real candidate runs wait for F3–F7. F9 builds on F4 and is complete before pilot. F10 starts immediately and gates every rollout.

For each pull request, provide:

- A typed contract, explicit failure states, and updated API examples where applicable.
- An Alembic migration and upgrade test for storage changes; a compatibility path for API changes.
- Authorization, rights, tenant/engagement, data-class, audit, and retention handling, or a reason each is not applicable.
- Focused tests for positive and negative behavior; integration or expert review for claims code tests cannot prove.
- Diagnostics with reason codes and metrics that do not disclose customer data.
- A feature flag, owner, rollout cohort, rollback steps, and a demonstration against a frozen case.

The guideline's 12-week sequence is an indicative schedule after staffing, source access, and environment readiness are confirmed. The pilot starts only after the release gates in Section 1.5 pass and a named release authority records approval. Fine-tuning, distillation, dynamic agents, graph expansion, and self-hosting are later options justified by measured residual failures or operating economics.

## 4. Decisions and evidence still required

This document is sufficient to **start scoped engineering work and create issues**. It is not sufficient by itself to authorize a professional pilot or promise a 12-week delivery. Record each decision in the engineering register before the dependent feature is enabled:

1. **Specification precedence:** owners confirm the current approved versions of ZL-T0-08, ZL-ENG-03, ZL-ENG-05, and ZL-ENG-06 and resolve conflicts with the proposed guideline and this plan.
2. **Professional coverage:** Product and domain assurance select the first jurisdiction, accounting framework, languages, effective-period rules, three task boundaries, critical errors, qualified reviewers, and acceptable abstention/completion targets.
3. **Sources and permitted use:** source-rights owners provide the pilot corpus and explicit rights for indexing, model transmission, display, export, retention, and any proposed training. Architecture and domain owners approve source precedence and quality rules.
4. **Processing and providers:** security/privacy approve data classes, deployment regions, retention/deletion, OCR processing, model providers, fallback eligibility, and outbound network policy. Provider claims and contracts require due diligence.
5. **Release and operations:** SRE and release authority approve observed latency, concurrency, cost, recovery, and audit-availability budgets; staging parity; reviewer capacity; kill-switch ownership; and the go/no-go record.

Missing decisions remain explicit blockers for the related release gate. They must not be replaced with model guesses, mock metrics, or assumed licence permission.
