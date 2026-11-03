# WF-01 release governance — operator runbook

For the people who will run WF-01 in staging: CTO/SRE, the identity owner, Security, Document Control, the Chief Architect, QA Automation and Independent QA. Decisions D1–D8 and blockers X1–X5 are in `wf01-decision-action-plan-2026-11-03.md`.

The verdict is **NO_GO** until every gate is SATISFIED by recorded evidence. Nothing in this branch is release evidence until authorized people complete the steps below in staging.

## 1. Configure staging (CTO / SRE, Security, identity owner)

| Setting | Value |
|---|---|
| `KRITON_ENVIRONMENT` | `staging`. Only staging produces qualifying runs. |
| `KRITON_GOVERNANCE_TENANT_ID` | The platform governance tenant. If unset, every governance request is refused. |
| `KRITON_QA_ADAPTER_BASE_URL` | The staging API's base URL. |
| `KRITON_QA_ADAPTER_API_KEY` | A `zlk_` key for a **QA Automation** service account in the evaluation tenant, issued through the secrets store. |
| `KRITON_QA_ADAPTER_TENANT_B_API_KEY` | A `zlk_` key for a service account in a **second** tenant, used only to seed F7. |
| `KRITON_GOVERNANCE_SIGNING_KEY` | Issued by Security (X3). Without it, records are `UNSIGNED_NO_KEY`. |

Run `python scripts/setup_database.py`. It applies migrations `g2a3b4c5d6e7`, `h3b4c5d6e7f8` and `i4c5d6e7f8a9`.

`h3b4c5d6e7f8` adds `tenant_id` to `safety_events`, `safety_overrides` and `escalation_cases` only where the column is missing. A database built from migrations alone lacked it, and every `/ask` returned 503.

Assign the five roles to named people in the governance tenant: Document Control, Chief Architect, Independent QA, QA Automation and CTO. A tenant Admin holds none of these permissions.

## 2. Authority and ownership (Document Control, Chief Architect)

1. Document Control supplies the missing documents (X4) to `docs/` and rebuilds `registry/authority_register.json` with `scripts/build_authority_register.py`.
2. On **Release Gates**: **Import register**. Proposals go through `POST /admin/authority/proposals`; the Chief Architect then ratifies them.
3. **Adopt gap allocation** (Document Control), then **Ratify gap allocation** (Chief Architect, who must be a different person).

## 3. Fixtures and the QA pack (QA Automation, the bank's owners)

1. The bank's owners review `backend/evals/qa_fixtures/F*/MANIFEST.json`: each file's sha256, and every **derivation** beyond the bank's text. Rebuild with `python scripts/build_qa_fixtures.py`; `--check` verifies the files against their manifests.
2. Ratifying the QA manifest and the fixtures (D5) means setting their status to `RATIFIED` in a reviewed commit. The verdict's `qa_pack` gate reads that status.
3. On **Release Gates**:
   1. **Import QA pack**.
   2. **Provision fixtures**. This uploads every file a case needs and puts F7 in tenant B. PNGs are recorded UNSUPPORTED, because the target accepts .pdf/.docx/.xlsx/.pptx/.csv only.

## 4. As-built (QA Automation, CTO)

1. Deploy a **committed, clean** build to staging.
2. QA Automation: **Record manifest**. Every requirement in `registry/wf01_requirement_map.json` must be MAPPED.
3. The CTO **verifies** it. Verification is refused for an uncommitted tree or for any unmapped requirement.

## 5. Runtime QA (QA Automation, Independent QA)

1. QA Automation starts a **pinned run**. All nine fields are required. Pin `release_sha` to the verified commit; the fixture checksums are pinned automatically.
2. Run **Execute next 10** until all 292 observations are recorded. Approve the model budget first (X5).
   - Cases are recorded **BLOCKED** with the reason when the adapter can't run them:
     - H01–H06: image uploads not accepted;
     - K04: needs a role change mid-conversation;
     - L05: needs fault injection.
   - Those capabilities are WF-02 work.
3. Independent QA adjudicates every executed observation against the bank's PASS oracle. They cannot adjudicate a run they started. Each adjudication needs an oracle version and a reason.
4. A case passes only when every planned repetition in a qualifying run is adjudicated PASSED. P0 cases have 5 repetitions.

## 6. Verdict (CTO)

**Record verdict** appends the computed verdict. Promotion of a governance-tenant release (`deploy`) is refused while it is NO_GO.

## Local exercise (not evidence)

`scripts/seed_wf01_local.py` refuses any database that isn't a local `*wf01_dev*` one. It creates "LOCAL-DEV simulated" role accounts and a tenant B.

Runs made this way are `local-dev` and never qualify. Without a model key, answers are the gateway's `[mock completion]`, which the ledger flags as such.
