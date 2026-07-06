# ZoikoLogia Backend — Structure Only

This is a **folder/file skeleton, not an implementation**. Every `.py` file (except `__init__.py`) contains a single one-line comment describing its intended purpose — no classes, no routes, no logic. It was scaffolded by reading all 26 specification documents in `../docs/` and organizing their requirements into a concrete backend layout, so implementation work has a place to land.

## Tech stack (per `ZoikoLogia_Project_Execution_Roadmap.docx`)

The other architecture docs (Back-End Architecture Spec, Master Architecture Build Doctrine) deliberately leave the stack as an open decision. The Roadmap doc is the one place a concrete recommendation is made:

- **FastAPI** (async) — API framework
- **PostgreSQL + pgvector** — relational store + embeddings, in one database
- **SQLAlchemy + Alembic** — ORM and migrations
- **httpx / pdfplumber / BeautifulSoup** — source ingestion
- **Celery or APScheduler** — background jobs
- Provider-agnostic **model gateway** in front of Claude / GPT / Gemini / self-hosted models

See `requirements.txt` (names only, unpinned) and `.env.example` (variable names only, no values).

## Layout

```
app/
  main.py                  FastAPI entrypoint
  core/                    config, security (OIDC/JWT/RBAC+ABAC), db session, event bus
  db/                      SQLAlchemy base + Alembic migrations folder
  api/v1/                  aggregates every domain router under /api/v1
  events/                  canonical event catalog + event envelope schema
  jobs/                    Celery/APScheduler background jobs
  domains/                 16 domain modules, one per service boundary (below)
tests/
scripts/
```

Each domain folder generally has `models.py` / `schemas.py` / `router.py` / `service.py`, plus extra files for named sub-components the docs called out explicitly.

## The 16 domains, and which doc each comes from

| Domain | Source doc(s) | Frontend page(s) it backs |
|---|---|---|
| `identity/` | Back-End Architecture Spec | — (cross-cutting auth) |
| `source_library/` | Kriton Authoritative Source Library & Licensing Register | Source licensing |
| `ontology/` | Kriton Knowledge Graph Accounting Ontology | Ontology & syllabus (graph half) |
| `rag/` | Kriton RAG Specification | — (query/answer pipeline, no direct admin page) |
| `model_gateway/` | Kriton LLM System Architecture & Model Strategy | Model & prompt registry |
| `risk_safety/` | Kriton AI Safety Risk Classification & Escalation | Risk policy, Escalation queue |
| `evaluation/` | Kriton LLM Evaluation & Benchmarking, QA Test Plan & Release Gate | Evaluation gates, Release gates |
| `audit_ledger/` | Kriton Audit Logging & Evidence Ledger | Audit replay |
| `privacy_security/` | Kriton Privacy Security & Data Protection | — (DSR/legal hold/breach clock, no direct page yet) |
| `provider_registry/` | Kriton Provider Due Diligence Register | Provider register |
| `admin_governance/` | Admin Governance Console Wireframe | Governance dashboard, Compliance calendar, Alerts center, Roles & permissions |
| `learning_cpd/` | Learning Practice CPD Workspace | — (learner-facing, not yet in this admin frontend) |
| `support_incident/` | Customer Support Incident Response Trust Operations | Incident response |
| `jurisdiction_locale/` | (Jurisdiction rollout content, cross-referenced in Back-End spec) | Jurisdiction rollout |
| `zoikosuite_integration/` | ZoikoSuite Embedded Kriton UX Specification | — (embed contract, no admin page) |
| `notifications_workflow/` | Back-End Architecture Spec (Notification & Workflow Queue Services) | — (cross-cutting SLA/queue engine) |

## What's deliberately not here

- No actual route handlers, ORM column definitions, or business logic — every file is a stub comment.
- No `alembic.ini` / migration files — `app/db/migrations/` is an empty folder waiting for `alembic init`.
- No Dockerfile or CI config — not specified in the docs read so far; the docs defer full API contracts to two documents that weren't in this doc set (`ZL-T1-03 API Specification`, `ZL-T1-14` integration architecture).
- Not wired to the frontend — `frontend/` still runs entirely on static mock data (see `frontend/lib/governance-data.ts`). Connecting the two is a separate step.

## Naming rule for when this gets implemented (ZL-ENG-01)

Two-tier advisor naming — enforce this the moment real code lands here:

- **Kriton™** is the only name allowed on any customer-visible surface: API response bodies, error payloads/messages, OpenAPI docs, logs shipped to the frontend, exported files, analytics events.
- **Massarius™** is the internal engine/reasoning-layer name. It may be used freely in internal module names, service boundaries, and code comments (e.g. `massarius_engine`, `massarius_reasoning_layer`, `massarius_evidence_chain`), but must **never** appear in anything a client or end user can see.
- Public API surface must use functional names instead: routes like `/advisor`, `/source-review`, `/evidence-trace`, `/standard-reference`; response fields like `advisor_service`, `accounting_intelligence`, `source_governed_reasoning`, `evidence_trace`, `source_review`, `standards_reference`.
- `kriton_ui` is an acceptable internal name for the UI-facing module/service.
- Before shipping any endpoint, grep its response models and error handlers for `massarius` — it should never match.

The frontend side of this rule already exists at `frontend/lib/advisor.ts` — reuse that file's `ADVISOR.about.engineLine` string (the one place Massarius may be shown to a user, inside an About/Info panel) rather than inventing new copy.

## Where the entity list came from

`Data_Model_Database_Schema_Specification_Wireframe.docx` names ~90 entities (tenants, sources, escalations, audit_events, evaluation_runs, cpd_records, etc.). Rather than one file per entity, they're grouped into each domain's `models.py` by the service boundary defined in `Back_End_Architecture_Specification_Wireframe.docx` §4 ("Service Domain" breakdown) — that doc is the most authoritative source for how the domains are drawn.
