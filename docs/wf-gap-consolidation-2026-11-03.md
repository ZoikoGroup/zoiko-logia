# Consolidated gap list (G01–G30): ownership, scope and prerequisites

3 November 2026. **Status: PROPOSED.** This document becomes authoritative only when the document owners ratify the
resolutions in §3. It changes no gate status and is not release evidence.

## 1. Sources compared

| Source | Identifier | What it says about allocation |
|---|---|---|
| Summary board | *Three Wireframes, 30 Gaps*, 31 Oct 2026 | "Primary gap allocation is mutually exclusive." WF-01: 12 gaps, WF-02: 13, WF-03: 5. |
| WF-01 | ZL-WF-GAP-01 v1.0 | §01 and §02 claim **G01–G07, G10–G12, G16, G18–G20, G28–G30** (17 gaps). §02 row 03 also gives **G28–G30** to WF-03. |
| WF-02 | ZL-WF-GAP-02 | No allocation table. Its screens list G07, G10, G11 and G12 among their primary gaps. "Supersedes nothing by itself." |
| WF-03 | ZL-WF-GAP-03 | Traceability §20A/20B gives a primary owning wireframe for **all 30 gaps**. It says "Wireframe 01 owns evidence, rights, approval, release and claims governance". |
| Underlying analysis | ZL-GAP-2026-10 v1.0 | The primary source cited by all three wireframes. |

**Finding:** the summary board and WF-03 §20A/20B agree on every gap, and WF-02's screens are consistent with them.
Only WF-01 §01/§02 differs, in two ways:
- it claims G07, G10–G12 and G28;
- its own §02 assigns G28–G30 to both WF-01 and WF-03.

## 2. Consolidated list

**Primary owner** is the proposed resolution: the summary board's allocation, which WF-03 §20A/20B matches. **WF-01
governance interface** marks gaps where WF-01 supplies controls (rights, approvals, release and claims gates) that the
owning wireframe consumes.

**As-built status** comes from the Phase 1 reconciliation for WF-01's gaps only. "Not assessed" means not yet
reconciled. It does not mean missing.

| Gap | Title | Primary owner | Sources agreeing | WF-01 governance interface | As-built status (3 Nov) | In scope now |
|---|---|---|---|---|---|---|
| G01 | Canonical document IDs / precedence | WF-01 | all | — | **PARTIAL**: A1 step 1 register and CI check only (§5) | **Yes** (A1) |
| G02 | As-built architecture and release proof | WF-01 | all | — | PARTIAL | Yes (A2), **blocked** (§4) |
| G03 | Production-connected QA execution | WF-01 | all | — | PARTIAL, fixture-only | Yes (A3), **blocked** (§4) |
| G04 | Supported-capability and claims matrix | WF-01 | all | — | MISSING (`jurisdiction_locale` is empty stubs) | Later in WF-01 |
| G05 | Source rights and entitlements | WF-01 | all | — | PARTIAL | Later in WF-01 |
| G06 | Ratified quality thresholds and policies | WF-01 | all | — | PARTIAL (defaults pass unknowns) | Later in WF-01 |
| G07 | Source freshness and historical truth | **WF-02** | board, WF-03, WF-02 screens | yes (WF-01 claims it) | not assessed | No (WF-02) |
| G08 | Deterministic accounting and consistency | WF-02 | all | shared | not assessed | No |
| G09 | Ledger / document connector qualification | WF-02 | all | shared | not assessed | No |
| G10 | Professional review and sign-off | **WF-02** | board, WF-03, WF-02 screens | yes (WF-01 claims it) | not assessed | No (WF-02) |
| G11 | Cross-service states, signatures, events | **WF-02** | board, WF-03, WF-02 screens | yes (WF-01 claims it) | not assessed | No (WF-02) |
| G12 | Bounded, recoverable agent execution | **WF-02** | board, WF-03, WF-02 screens | yes (WF-01 claims it) | not assessed | No (WF-02) |
| G13 | Spreadsheet-native accounting workflows | WF-02 | all | — | not assessed | No |
| G14 | Bulk evidence review and cell lineage | WF-02 | all | — | not assessed | No |
| G15 | Engagement memory and collaboration | WF-02 | all | — | not assessed | No |
| G16 | Model, retrieval and evaluator qualification | WF-01 | all | — | PARTIAL | Later in WF-01 |
| G17 | Multimodal evidence integrity | WF-02 | all | shared | not assessed | No |
| G18 | Tenant / tool security boundaries | WF-01 | all | — | PARTIAL | Later in WF-01 |
| G19 | Regional privacy, deletion and retention | WF-01 | all | — | MISSING (`privacy_security` is empty stubs) | Later in WF-01 |
| G20 | Reliability and disaster recovery | WF-01 | all | — | PARTIAL | Later in WF-01 |
| G21 | Global and multilingual qualification | WF-03 | all | shared | not assessed | No |
| G22 | Learning efficacy and student safeguards | WF-03 | all | — | not assessed | No |
| G23 | Audit analytics and evidence sufficiency | WF-03 | all | — | not assessed | No |
| G24 | Financial-markets research boundaries | WF-03 | all | — | not assessed | No |
| G25 | Standards changes and affected work | WF-02 | all | shared | not assessed | No |
| G26 | Complete professional user journeys | WF-02 | all | shared | not assessed | No |
| G27 | Accessible, parity-checked deliverables | WF-02 | all | shared | not assessed | No |
| G28 | Reviewer labor and licensed-content economics | **WF-03** | board, WF-03 | yes (WF-01 claims it) | not assessed | No (WF-03) |
| G29 | Enterprise assurance and public claims | WF-01 | board, WF-03 (WF-01 §02 also gives it to WF-03) | — | MISSING | Later in WF-01 |
| G30 | Independent competitive effectiveness | WF-01 | board, WF-03 (WF-01 §02 also gives it to WF-03) | — | MISSING | Later in WF-01 |

## 3. Contradictions and proposed resolutions

| # | Contradiction | Proposed resolution | Who ratifies |
|---|---|---|---|
| C1 | WF-01 §01/§02 claims G07, G10, G11, G12 and G28 as its own, while the board, WF-03 §20A/20B and WF-02's screens give them to WF-02 (G07, G10–G12) and WF-03 (G28). | **Primary ownership follows the board and WF-03 §20A/20B.** WF-01's wording ("establishes governance for") becomes a governance interface: WF-01 supplies the rights, approval and release controls these gaps consume, and does not own their closure. WF-01 §01/§02 would be amended to match. | Document Control + Chief Architect |
| C2 | WF-01 §02 assigns G28–G30 to both WF-01 and WF-03. | G29 and G30 to WF-01; G28 to WF-03 (as in C1). | Document Control |
| C3 | ZL-ENG-06 identifies two different standards: information quality and model tiering (Gap Analysis; Architecture and QA Handoff). | **Unresolved.** Recorded as `COLLISION_UNRESOLVED` (§5). Needs both standards' texts and two new canonical IDs. | Document Control proposes, Chief Architect ratifies |
| C4 | ZL-T0-05 and ZL-T0-06 are cited by 15+ controlled documents but are not in the repository; the gap analysis says they are unrecovered. | **Unresolved.** Recorded as `EVIDENCE_UNAVAILABLE_IN_REPO`, not as non-existent or approved. | Document Control (retrieve) |
| C5 | The PRD declares two identifiers for itself: `ZL-T1-01` and `ZL-T1-01-WF (provisional)`. | **Unresolved.** Recorded as `MULTIPLE_DECLARED_IDS`. | Document Control |
| C6 | Five controlled documents declare no identifier: the 4-Person Execution Plan, the Engineering Architecture and Implementation Guide, the AI Advisor Combined Wireframe, the LLM Evaluation and Benchmarking Wireframe, and the Project Execution Roadmap. | **Unresolved.** Recorded as `ID_NOT_FOUND`. | Document Control |
| C7 | The Tier-0 standards themselves (ZL-T0-01 to ZL-T0-14) and the ZL-T1 series are cited but only their wireframes are in the repository. | Recorded as `EVIDENCE_UNAVAILABLE_IN_REPO`, with each one's wireframes listed. Retrieval is needed before precedence can be applied. | Document Control |

## 4. Prerequisites before A2 and A3

None of these can be met by engineering alone. Each blocks the workcard shown.

| # | Prerequisite | Blocks | Status | Needed from |
|---|---|---|---|---|
| P1 | Ratify C1/C2 (ownership) | scope of A2/A3 traceability | not ratified | Document Control + Chief Architect |
| P2 | **A deployed, committed build**: 8010 runs an uncommitted working tree, so no commit SHA describes it | A2 (deployment_commit), A3 (pinned release SHA) | **missing** | CTO: a committed, deployed environment (staging) |
| P3 | **A staging environment** with its own identity (WF-01 RG-006: "pinned staging release") | A3 | **missing**: work is local-only | CTO / SRE |
| P4 | **A service-account credential** for the runtime QA adapter, through the API, not in-process | A3 (adapter CONNECTED) | **missing**: no evaluation credential configured | Identity owner |
| P5 | **A machine-readable 72-case manifest** with exactly 38 P0 cases, and the 292-row NOT_RUN baseline | A3 | **missing**: the question bank is a docx only; no 292-row baseline found | QA Automation |
| P6 | Signer roles (Document Control, Chief Architect, Independent QA, CTO) mapped to identities and permissions | A1 ratification, A2/A3 verification and adjudication | **missing** in `identity` | Identity / Governance |
| P7 | Signing mechanism for observations and approvals (cryptographic or signed event) | A2/A3 hash-bound records | **missing** (`privacy_security/encryption_keys.py` is a stub) | Security |
| P8 | Release-control scope decision: tenant-scoped (as built) or the platform / Super Admin plane | A2/A3 storage location | undecided | CTO |
| P9 | Clean evaluation data: test tenants and users sit in what is recorded as the production database | A3 observation integrity | known issue | Data owner |
| P10 | Correct the existing PASS defaults (`ResultPack` contamination/zero-tolerance defaults; `restricted_block_rate` = 1.0 with no cases) | any gate built on evaluation runs | not started (behaviour change, needs approval) | QA Automation |

## 5. Release evidence vs development material

| Item | Where | Release evidence? |
|---|---|---|
| A1 step 1 authority register and CI check | `backend/registry/authority_register.json`, `backend/scripts/{build_authority_register,check_authority_ids}.py`, `backend/tests/test_authority_register.py` | **No.** `release_evidence: false`. It records what the documents declare; it ratifies nothing. |
| Kriton capability suite, offline and live runs | `backend/evals/capability_suite.json`, `backend/tests/capability_suite_report.py`, `backend/scripts/live_capability_run.py` | **No.** Development measurement: unpinned, unsigned, uncommitted code, and the live runner skips sign-in. |
| Evaluation Gates runs (`POST /evaluation/run`) | `domains/evaluation` | **No.** They grade gold answers, not runtime output (Phase 1). |
| Uncommitted working tree on 8010 | main `Naresh-new` | **No.** No commit SHA describes it. |

No gate in this document or the register is marked PASS. Until §4 is met, A2 and A3 can be designed but cannot produce
qualifying evidence.
