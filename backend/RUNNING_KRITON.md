# Running Kriton with FORCE_DIRECT_ANSWER=true

Dev/test mode that answers every query directly instead of routing HIGH-risk
questions to human review. Turn off before any shared or production use (see
bottom).

## Prerequisites

- Python venv set up at project root, `pip install -r requirements.txt` done.
- Node.js + npm for the frontend.
- Supabase project with the `vector` extension enabled.
- API key for at least one LLM provider (Groq recommended).

## 1. `backend/.env`

```env
# Use the Session Pooler string from Supabase (Project Settings → Database →
# Connection String → "Session pooler"), not the direct db.<ref>.supabase.co
# host — that one is IPv6-only and unreliable on most networks.
DATABASE_URL=postgresql://postgres.<project-ref>:<postgres-password>@aws-0-<region>.pooler.supabase.com:5432/postgres

# Non-superuser role for request-time queries (auto-created on first boot).
APP_DATABASE_URL=postgresql://zoiko_app.<project-ref>:<a-password-you-choose>@aws-0-<region>.pooler.supabase.com:5432/postgres

ENABLE_RAG_EMBEDDINGS=true
ENABLE_ML_CLASSIFIER=true

# Testing only — see warning at the bottom of this file.
FORCE_DIRECT_ANSWER=true

JWT_SECRET_KEY=<any-random-string>
OIDC_ISSUER_URL=
OIDC_CLIENT_ID=
OIDC_CLIENT_SECRET=

# console.groq.com
GROQ_API_KEY=<gsk_...>

# Optional fallback — needs real billing on the account.
OPENAI_API_KEY=<sk-...>
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=
AZURE_OPENAI_API_KEY=

# Optional — cloud fallback parser when Docling fails on a document.
LLAMA_CLOUD_API_KEY=<llx-...>

VECTOR_INDEX_URL=
OBJECT_STORAGE_URL=
CELERY_BROKER_URL=
```

## 2. One-time Supabase setup

```sql
create extension if not exists vector;
```

Tables, RLS policies, and the `zoiko_app` role are provisioned automatically
on first boot.

## 3. Start the backend

```bash
cd backend
../.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

Wait for `Application startup complete.` (first boot is slower — it warms up
the ML models). Verify: `curl http://localhost:8000/health`

## 4. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000` and go to the **Ask Kriton** page.

## 5. Ingest reference documents

Drop PDFs into `backend/data/sources/uk/` or `backend/data/sources/us/`, add
a manifest entry in `scripts/ingest_reference_sources.py`, then:

```bash
cd backend
../.venv/Scripts/python.exe scripts/ingest_reference_sources.py
```

Idempotent — re-running only processes documents not already ingested.

## 6. Verify

Ask a question covered by what you ingested (e.g. "What is FRS 100 and what
does it apply to?"). You should get a direct answer with citations — no
escalation, no clarification, no refusal (PII/jailbreak blocks still apply).

---

## ⚠️ Turning this back off

`FORCE_DIRECT_ANSWER=true` disables the real HIGH-risk → human-review
safeguard. Before any shared or production use:

```env
FORCE_DIRECT_ANSWER=false
```

Restart the backend. Genuine tax/audit/legal-adjacent questions will then
correctly escalate to the **Escalation Queue** page instead of being
answered directly.
