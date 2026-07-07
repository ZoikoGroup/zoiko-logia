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
A Next.js 15 application that visualizes the AI safety state and provides operational workflows.
- **Ask Kriton™:** An interactive query interface where you can type queries and simulate upstream source/privacy states to see the Risk Engine's real-time routing logic.
- **Escalation Queue:** A dashboard for reviewing HIGH-risk or RESTRICTED queries, complete with SLA countdowns and Maker-Checker enforcement.
- **Risk Policy & Taxonomy:** A real-time view of active risk policies and refusal templates.
- **Offline Fallback Mode:** The frontend's API client (`safety-api.ts`) includes an embedded offline classifier. If the Python backend is offline, the dashboard degrades gracefully but remains fully operational for demonstrations.

---

## Quick Start

You can run the frontend in **Offline Mode**, or you can run the **Full Stack** to leverage the ML Semantic Engine and SQLite Audit Ledger.

### Option A: Run Full Stack (Recommended)

**1. Start the Backend (Terminal 1)**
```bash
cd backend
# Install dependencies including FastAPI, SQLAlchemy, and Transformers
pip install -r requirements.txt

# Run the server (auto-creates the SQLite database on first boot)
uvicorn app.main:app --reload --port 8000
```
*Verify it's running by visiting http://localhost:8000/health*

**2. Start the Frontend (Terminal 2)**
```bash
cd frontend
npm install
npm run dev
```
*Open http://localhost:3000 to access the platform.*

### Option B: Run Frontend Only (Offline Demo Mode)

If you just want to view the UI and test basic routing logic without running the Python ML engine:
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
