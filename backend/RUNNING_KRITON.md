# Running Kriton with FORCE_DIRECT_ANSWER=true

Dev/test mode that answers every query directly instead of routing HIGH-risk
questions to human review. Turn off before any shared or production use (see
bottom).

## Prerequisites

- Python venv set up at project root, `pip install -r requirements.txt` done.
- Node.js + npm for the frontend.
- A Supabase project (Auth + Postgres).
- API key for at least one LLM provider (Groq recommended).

## 1. `backend/.env`

```env
# Use the Session Pooler string from Supabase (Project Settings → Database →
# Connection String → "Session pooler"), not the direct db.<ref>.supabase.co
# host — that one is IPv6-only and unreliable on most networks.
DATABASE_URL=postgresql://postgres.<project-ref>:<postgres-password>@aws-0-<region>.pooler.supabase.com:5432/postgres

# Non-superuser role for request-time queries (auto-created on first boot).
APP_DATABASE_URL=postgresql://zoiko_app.<project-ref>:<a-password-you-choose>@aws-0-<region>.pooler.supabase.com:5432/postgres

ENABLE_ML_CLASSIFIER=true

# Testing only — see warning at the bottom of this file.
FORCE_DIRECT_ANSWER=true

# Supabase Auth — Project Settings → API. Service role key is secret,
# server-side only.
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>

# console.groq.com
GROQ_API_KEY=<gsk_...>

# Optional fallback — needs real billing on the account.
OPENAI_API_KEY=<sk-...>
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=
AZURE_OPENAI_API_KEY=

OBJECT_STORAGE_URL=
CELERY_BROKER_URL=
```

## 2. Start the backend

```bash
cd backend
../.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8010
```

Wait for `Application startup complete.` (first boot is slower — it warms up
the ML risk classifier, tables/RLS policies, and the `zoiko_app` role are
provisioned automatically). Verify: `curl http://localhost:8010/health`

## 3. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`, sign up/sign in, and go to the **Ask Kriton**
page.

## 4. Add sources to answer from

Kriton only answers from sources registered in the governed Source Library —
add some via the **Source Licensing** admin page (or `POST /sources` +
approve a version) so retrieval has something eligible to match against.

## 5. Verify

Ask a question matching a category/jurisdiction you registered a source for
(e.g. "What is FRS 100 and what does it apply to?" if you registered an FRS
100 source). You should get a direct answer — no escalation, no
clarification, no refusal (PII/jailbreak blocks still apply).

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
