# WF-01: decision and action plan for the remaining prerequisites

3 November 2026. Companion to `docs/wf-gap-consolidation-2026-11-03.md`. A2 and A3 stay **NOT_RUN**; no gate is PASS and
release readiness is not claimed. Nothing has been committed, pushed or deployed, and production has not been changed.

## 1. Decisions and approvals (you, or the named owner)

| ID | Prerequisite | Decision needed, in plain English | Owner | Recommended answer | Unblocks |
|---|---|---|---|---|---|
| **D1** | P1 | Which wireframe owns G07, G10–G12 and G28? | Founder → ratified by Document Control + Chief Architect | **Follow the summary board and WF-03 §20A/20B** (G07, G10–G12 → WF-02; G28 → WF-03). WF-01 only supplies the governance controls they use. | A2/A3 scope; WF-01 §01/§02 amendment |
| **D2** | P6 | Who holds Document Control, Chief Architect, Independent QA and CTO sign-off, and may four new permissions be added to the existing role table? | Founder | Name one person per role, and require each to be different from the author of whatever they sign. Add `authority.propose`, `authority.ratify`, `qa.adjudicate` and `release.verify` to `identity/permissions.py`. No new service. | A1 step 2 (ratifying the ZL-ENG-06 fix), A3 adjudication |
| **D3** | P8 | Is release control per tenant (as built) or platform-wide? | CTO | **Platform-wide**, metadata-only, in the existing Super Admin plane, as WF-01 §02 places "Platform release control (privileged)". | Where A2/A3 records are stored |
| **D4** | P10 | May the evaluation service stop defaulting unknown results to "passed"? | Founder / QA lead | **Yes.** Unknown becomes NOT_RUN. The one existing result pack (14 Jul 2026) would display as unverified, not passed. | Any gate built on evaluation runs |
| **D5** | P5 | Is the draft 72-case manifest the agreed test list, and does a separate original 292-row baseline exist? | QA Automation | Ratify the draft (it matches: 72 cases, 38 P0, 292 planned observations). If the original baseline exists, provide it; otherwise accept the derived plan as the baseline. | A3 |
| **D6** | P2 | May the current working tree be committed to a branch, so a build can be tied to a commit? | Founder | Commit to a feature branch only. No merge, push or deploy without a separate approval. | A2 (commit binding) |
| **D7** | P9 | What happens to the test data in the hosted database: 33 of 62 tenants and 58 of 85 users look like test data? | Founder / data owner | Don't delete yet. Approve a reviewed cleanup plan, and meanwhile run evaluations only in a separate evaluation tenant. Any production change needs your explicit authorisation. | Clean A3 observations |
| **D8** | C3–C7 | Retrieve ZL-ENG-06's two standards and ZL-T0-05/06, or accept them as "evidence unavailable" for this release scope? | Document Control | Retrieve them. Until then they stay unresolved, and anything that depends on them stays unqualified. | A1 step 2 |

## 2. Engineering tasks we can complete independently

| ID | Task | Status | Owner |
|---|---|---|---|
| E1 | A1 step 1: authority register, duplicate-ID CI check, 13 tests | **Done** (uncommitted, both copies) | Engineering |
| E2 | Draft machine-readable 72-case manifest with 292 planned NOT_RUN observations, read from the question bank (`evals/qa_pack_72_manifest.DRAFT.json`, 4 tests) | **Done**: `DRAFT_UNRATIFIED`, not release evidence | Engineering |
| E3 | Read-only inventories: roles/permissions (P6), test data (P9), existing evaluation/release records | **Done** (results in §1, D2/D4/D7) | Engineering |
| E4 | A1 step 2: database tables, resolver and propose/ratify endpoints with revision checks and idempotency | Waits for D2, D3 | Engineering |
| E5 | Correct the PASS defaults and add a test that unknown never counts as pass | Waits for D4 (about half a day) | Engineering |
| E6 | A2 as-built generator (routes, schema head, flag names, commit; refuses an uncommitted tree) | Waits for D6 and X1 | Engineering |
| E7 | A3 observation ledger (append-only with triggers) and HTTP runtime adapter | Waits for D3, D5, X1, X2, X3 | Engineering |

## 3. External dependencies (access, infrastructure, credentials)

| ID | Dependency | Owner | Exact action |
|---|---|---|---|
| **X1** | A committed, deployed **staging** environment with its own identity (P2, P3) | CTO / SRE | Provision staging; deploy a named commit; record its URL and environment ID. |
| **X2** | A **service account** for the QA adapter on staging (P4) | Identity owner | Create a service account with read-only ask permission in the evaluation tenant; issue the credential through the secrets store, not in chat. |
| **X3** | **Signing keys** for observations and approvals (P7) | Security | Choose a key service and issue a signing key for the evaluation service. |
| **X4** | The missing documents: both ZL-ENG-06 standards, ZL-T0-05/06 and the Tier-0 texts | Document Control | Supply the files for `docs/`; the register then picks them up and the CI check enforces it. |
| **X5** | Model-provider budget for 292 observations | Finance / you | Approve about 3–12 million tokens on the configured provider (about **$5–15** at current Groq rates). |

## 4. Order of work once decided

1. **D1, D2, D3, D8** → E4 (A1 step 2: ratify the ZL-ENG-06 resolution once the texts and roles exist).
2. **D4** → E5.
3. **D6 + X1** → E6 (A2).
4. **D5 + X1 + X2 + X3 + X5** → E7 (A3), executed against staging, independently adjudicated.

Until a row's prerequisites are met, its outputs stay NOT_RUN.
