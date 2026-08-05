# ZoikoLogia AI Safety & Governance Platform

A source-governed, jurisdiction-aware, audit-ready AI governance platform for ZoikoLogia. 

This repository implements the strict **AI Safety, Risk Classification & Escalation Specification (ZL-T0-04-WF-01)**. It guarantees that **every request must be classified before any LLM is allowed to generate a response.**

## Architecture

The project is structured as a full-stack application with a strict separation between the backend policy engine and the frontend governance dashboard.

### 1. Backend: AI Safety Service (`/backend`)
A deterministic Python/FastAPI service that acts as the absolute authority on risk and safety routing.
- **L1 Fast Scan:** Regex-based defense-in-depth for PII, explicit bypass attempts, and academic integrity violations.
- **L2 ML Semantic Engine:** A Zero-Shot Classification pipeline (powered by HuggingFace `transformers`) that mathematically scores the intent of a prompt against semantic labels (e.g., "regulated tax advice" vs "general educational concept").
- **Strict Governance:** Automatically triggers `CLASSIFICATION_UNCERTAIN` states for ambiguous queries, routing them to clarification workflows instead of guessing.
- **Audit Ledger:** Records 100% of routing decisions, overrides, escalations, and maker-checker violations in a local SQLite database (`zoikologia.db`), matching the exact payload schema mandated by Section 15 of ZL-T0-04.

### 2. Frontend: Governance Dashboard (`/frontend`)
A Next.js 16 application that visualizes the AI safety state and provides operational workflows.
- **Ask Kriton™:** An interactive query interface where you can type queries and simulate upstream source/privacy states to see the Risk Engine's real-time routing logic.
- **Escalation Queue:** A dashboard for reviewing HIGH-risk or RESTRICTED queries, complete with SLA countdowns and Maker-Checker enforcement.
- **Risk Policy & Taxonomy:** A real-time view of active risk policies and refusal templates.
- **Supabase Session Security:** Protected API clients send the current Supabase access token; the backend derives user and tenant identity from verified claims.

## Canonical Ask Kriton workflow

The implementation follows `backend/uploads/ZL-ENG-02` and `ZL-ENG-03`:

1. Authenticate, rate-limit, validate and apply idempotency.
2. Generate query, request, correlation and audit-chain identifiers.
3. Run the safety pre-screen before any retrieval.
4. Plan retrieval and apply licence Checkpoint A to create a tenant-scoped source allow-list.
5. Retrieve only allowed sources, rerank candidates, and build the immutable SourceBundle with Checkpoint B.
6. Classify professional risk and select a deterministic route from the versioned policy matrix.
7. On the LLM route, fit context, re-evaluate downgraded confidence, redact external-provider input, compose, assemble citations and validate output with Checkpoint C.
8. Persist ordered audit events before returning the structured route/outcome response.

---

## Quick Start

Run the full stack for authenticated, tenant-scoped workflows. A frontend-only start can render public/authentication surfaces but does not provide a governed Ask Kriton backend.

### Option A: Run Full Stack (Recommended)

Before starting Docker Compose, provide `SUPABASE_URL`,
`SUPABASE_SERVICE_ROLE_KEY`, `NEXT_PUBLIC_SUPABASE_URL`, and
`NEXT_PUBLIC_SUPABASE_ANON_KEY` in the shell or a root `.env` file. The
`NEXT_PUBLIC_*` values are embedded during `next build` and cannot be added
only after the frontend image has been built.

**1. Start the Backend (Terminal 1)**
```bash
cd backend
# Install dependencies including FastAPI, SQLAlchemy, and Transformers
pip install -r requirements.txt

# Run the server (auto-creates the SQLite database on first boot)
uvicorn app.main:app --reload --port 8010
```
*Verify liveness at http://localhost:8010/health and dependency readiness at http://localhost:8010/ready.*

**2. Start the Frontend (Terminal 2)**
```bash
cd frontend
npm install
npm run dev
```
*Open http://localhost:3000 to access the platform.*

### Option B: Run Frontend Only (UI development)

If you only need to work on UI rendering:
```bash
cd frontend
npm install
npm run dev
```

---

## Key Compliance Features (ZL-T0-04-WF-01)

- **CLASSIFICATION_UNCERTAIN State:** If the ML classifier's confidence falls below `0.65`, the system refuses to guess and triggers a safe clarification workflow.
- **Maker-Checker Rules:** Reviewers cannot approve their own queries or policy edits. 
- **Professional Boundary Controls:** Post-generation validators block prohibited statements (like *"I certify"* or *"I advise as your accountant"*).
- **Time-Bounded Overrides:** Emergency safety blocks and routing overrides are strictly limited to 72 hours.
- **Advanced State Routing:** Properly handles `LOW_CONFIDENCE`, `ONTOLOGY_UNRESOLVED`, and `PII` by falling back to refusal templates, clarification routes, or immediate security incident generation.
