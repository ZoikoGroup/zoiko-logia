# ZoikoLogia Governance Dashboard

A source-governed, jurisdiction-aware, audit-ready AI governance dashboard for ZoikoLogia — a single Next.js app, no backend service. Every page (Governance dashboard, Source licensing, Ontology & syllabus, Jurisdiction rollout, Risk policy, Evaluation gates, Escalation queue, Provider due diligence, Audit replay, Roles & release gates) is static mock data defined in `frontend/lib/governance-data.ts`.

## Structure

```
frontend/   Next.js 16 app (App Router, Tailwind) — the entire app, served on :3000
```

## Quick start

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

Or from the repo root: `npm run dev` (runs the same command via a thin wrapper script).
