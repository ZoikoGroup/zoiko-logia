# Kriton™ Implementation README

This document outlines the implementation details, functional architecture, run commands, and external services utilized in the Kriton™ Backend system (powered by the Massarius™ engine).

## 1. System Overview and Functioning

The Kriton™ backend is a **FastAPI** service that orchestrates query safety screening, source-governed retrieval, and answer composition against a curated, licensed source library.

### Core Workflow: Ask Kriton™
1. **Query Ingress & Validation**: User submits a query. The backend performs structural validation.
2. **Pre-screen Safety**: Regex-based defense-in-depth for PII, jailbreak/bypass attempts, and academic integrity violations, before retrieval runs.
3. **Retrieval**: `keyword_mvp` — category + jurisdiction keyword matching against the governed Source Library (`sources`/`source_versions`), producing a `SourceBundle` with a confidence state.
4. **Risk Classification & Routing**: A risk classifier (HuggingFace zero-shot, when `ENABLE_ML_CLASSIFIER=true`) plus the versioned policy matrix decide whether to answer directly, escalate to human review, refuse, or ask for clarification.
5. **Response Composition**: An LLM call (Groq) synthesizes an answer grounded in the retrieved `SourceBundle`, followed by a post-composition validation checkpoint (grounding, prohibited-claim, disclaimer) before the mandatory Kriton™ disclaimer is appended.
6. **Audit Ledger**: The entire transaction (query, retrieval, risk score, composed answer, route) is recorded for compliance.

## 2. Services and Components

| Component / Function | Service / Library Utilized | Details |
| --- | --- | --- |
| **API Framework** | FastAPI | Asynchronous Python backend framework handling HTTP requests and routing. |
| **Retrieval** | `keyword_mvp` (in-house) | Category + jurisdiction keyword matching against the governed Source Library — no embeddings/vector search. |
| **Risk Classification** | HuggingFace `transformers` zero-shot pipeline | Scores query intent against risk labels when `ENABLE_ML_CLASSIFIER=true`. |
| **LLM / Generation** | Groq API (`llama3-70b-8192` / `llama3-8b-8192`) | High-speed LLM inference used for final answer composition. |

## 3. Run Commands

### Backend (FastAPI)
Ensure you have activated your virtual environment and installed all dependencies from `requirements.txt`.
Make sure you have populated `.env` with your `GROQ_API_KEY` and Supabase credentials (see `.env.example`).

```bash
# Start the FastAPI development server
cd backend
uvicorn app.main:app --reload --port 8010
```
*The API will be available at `http://localhost:8010`. Swagger documentation is at `http://localhost:8010/docs`.*

### Frontend (Next.js / React)
```bash
# Start the frontend development server
cd frontend
npm install
npm run dev
```
*The frontend application will be available at `http://localhost:3000`.*

### Accessing the Dashboard (Login)
Once the frontend and backend servers are running, sign up (or sign in) at:
- **URL**: [http://localhost:3000/login](http://localhost:3000/login)

Authentication is Supabase-backed — see the root `README.md` and `RUNNING_KRITON.md` for setup.

## 4. Environment Configuration (`.env`)

Before running the application, you must configure the backend environment variables. Create a `.env` file in the `backend/` directory (copy `.env.example`) and add your actual credentials:

```env
# LLM Provider (Groq for high-speed Llama-3 inference)
GROQ_API_KEY=your_groq_api_key_here

# Supabase Auth
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>
```

## 5. Architectural Naming Conventions (ZL-ENG-01)
- **Kriton™**: The public-facing name used on all customer-visible surfaces, UI, and API responses.
- **Massarius™**: The internal reasoning engine. This name is used in codebase structures and comments but must never be exposed to the end user.
