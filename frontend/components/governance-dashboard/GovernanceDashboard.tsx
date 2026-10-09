"use client";

import Link from "next/link";
import { AlertTriangle, ArrowRight, CheckCircle2, Clock3, Download, FileCheck2 } from "lucide-react";

const domains = [
  ["AI Safety & Risk Controls", "Control failure", "29/33", "1 critical · 1 high", "Current · 25d ago", "Quarterly red-team evaluation"],
  ["Source & Knowledge Governance", "Assessment overdue", "14/17", "None", "Stale · 42d ago", "UK source licence renewal"],
  ["Evaluation & Release Readiness", "Attention required", "11/13", "2 high", "Current · 25d ago", "Grounding gate re-evaluation"],
  ["Audit & Incident Readiness", "Attention required", "7/8", "None", "Delayed · 25d ago", "Corrective-action verification"],
  ["Professional Boundaries", "Effective with observations", "9/9", "1 high", "Current · 25d ago", "None scheduled"],
  ["Human Accountability", "Effective", "6/6", "None", "Current · 25d ago", "None scheduled"],
  ["Jurisdiction & Provider Coverage", "Not assessed", "0/5", "None", "Unknown · 70d ago", "US rollout assessment"],
];

const exceptions = [
  ["Critical", "AI Safety & Risk Controls", "Post-composition validation gate failed open for 12 minutes"],
  ["High", "AI Safety & Risk Controls", "High-risk route confidence degraded to LOW_CONFIDENCE for tax queries"],
  ["High", "Evaluation & Release Readiness", "Grounding/citation gate failed for release candidate rc-2026.07.2"],
  ["High", "Evaluation & Release Readiness", "Safety/risk gate blocked pending updated red-team evidence"],
  ["High", "Professional Boundaries", "Boundary escalation SLA approaching breach — audit advice request"],
];

const decisions = [
  ["HIGH", "EXCEPTION ACCEPTANCE", "Accept residual risk — LOW_CONFIDENCE routing for UK tax queries", "17/07/2026"],
  ["HIGH", "RELEASE", "Release authority sign-off — rc-2026.07.2", "19/07/2026"],
  ["MEDIUM", "SOURCE LICENSE", "Renew UK FRS source license — expires within 30 days", "15/07/2026"],
];

function StatePill({ label }: { label: string }) {
  const danger = /failure/i.test(label);
  const good = /effective/i.test(label);
  return <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${danger ? "bg-bad/10 text-bad" : good ? "bg-ok/10 text-ok" : "bg-warn/10 text-warn"}`}>{label}</span>;
}

export function GovernanceDashboard() {
  return (
    <main className="flex-1 overflow-y-auto bg-canvas p-4 lg:p-6">
      <div className="mx-auto max-w-[1500px] space-y-5">
        <div className="rounded-2xl border border-line bg-panel p-4 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div><p className="text-sm font-semibold text-ink">ws_uk_advisory · Workspace scope</p><p className="mt-1 text-xs text-muted">PRODUCTION · Jurisdictions: UK, US · Entities: 1 · 16/06/2026 – 16/07/2026</p></div>
            <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-warn"><Clock3 size={15} />Delayed · 25d ago</span>
          </div>
          <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 border-t border-line pt-3 text-xs text-muted"><span>Tenant isolation: <b className="text-ok">boundary enforced</b></span><span>Evidence freshness: <b className="text-warn">degraded</b></span><span>Audit ledger: <b className="text-ok">writable, verified</b></span><span>Policy matrix: <b className="text-ink">v1</b></span></div>
        </div>

        <div className="rounded-xl border border-warn/30 bg-warn/10 px-4 py-3 text-sm text-warn">Partial governance view — Audit & Incident Readiness are delayed. Other modules were evaluated as of 16 Jul 2026, 03:30.</div>

        <header className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div><h1 className="text-3xl font-bold tracking-tight text-ink">Governance Dashboard</h1><p className="mt-1 text-muted">Evidence-backed oversight of AI, source, professional, release and operational controls.</p><p className="mt-2 font-semibold text-ink">1 critical exception · 3 decisions pending · 2 release gates blocked</p></div>
          <div className="flex flex-wrap gap-2"><Link href="/alerts-center" className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-bad px-4 text-sm font-semibold text-white"><AlertTriangle size={16} />Open critical exceptions</Link><Link href="/risk-policy" className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-line bg-panel px-4 text-sm font-semibold text-ink"><FileCheck2 size={16} />Review pending decisions</Link><button className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-line bg-panel px-4 text-sm font-semibold text-ink"><Download size={16} />Export</button></div>
        </header>

        <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {domains.slice(0, 7).map(([name, state, controls, , freshness]) => <article key={name} className="rounded-2xl border border-line bg-panel p-4"><h2 className="font-semibold text-ink">{name}</h2><div className="mt-3"><StatePill label={state} /></div><p className="mt-3 text-sm text-muted">Controls {controls} · AI Governance Lead</p><p className={`mt-4 border-t border-line pt-3 text-sm font-semibold ${/Stale|Delayed|Unknown/.test(freshness) ? "text-warn" : "text-ok"}`}>{freshness}</p></article>)}
        </section>

        <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_390px]">
          <section className="overflow-hidden rounded-2xl border border-line bg-panel">
            <div className="flex items-center justify-between border-b border-line px-5 py-4"><div><p className="text-xs font-bold uppercase tracking-[.18em] text-muted">Exception-first</p><h2 className="mt-1 text-xl font-bold text-ink">Critical exceptions</h2></div><Link href="/alerts-center" className="text-sm font-semibold text-brand">View all critical exceptions</Link></div>
            <div className="divide-y divide-line">{exceptions.map(([severity, domain, title]) => <article key={title} className="p-5"><div className="flex items-start justify-between gap-4"><div><div className="flex flex-wrap items-center gap-2"><span className={`rounded-full px-2 py-0.5 text-xs font-bold ${severity === "Critical" ? "bg-bad/10 text-bad" : "bg-warn/10 text-warn"}`}>{severity}</span><span className="text-xs font-bold uppercase text-muted">{domain}</span></div><h3 className="mt-2 font-semibold text-ink">{title}</h3><p className="mt-2 text-sm text-muted">Scope: Production · Owner: AI Governance Lead · 26d open · SLA breached · Evidence: current</p></div><ArrowRight size={17} className="shrink-0 text-brand" /></div></article>)}</div>
          </section>

          <section className="overflow-hidden rounded-2xl border border-line bg-panel"><div className="border-b border-line px-5 py-4"><p className="text-xs font-bold uppercase tracking-[.18em] text-muted">Assigned to you</p><h2 className="mt-1 text-xl font-bold text-ink">Pending decisions</h2></div><div className="divide-y divide-line">{decisions.map(([severity, kind, title, due]) => <article key={title} className="p-5"><div className="flex justify-between gap-2"><span className="text-xs font-bold text-bad">{severity} · {kind}</span><span className="text-xs text-muted">Due {due}</span></div><h3 className="mt-3 font-semibold leading-6 text-ink">{title}</h3><Link href="/risk-policy" className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-brand">Review decision <ArrowRight size={14} /></Link></article>)}</div></section>
        </div>

        <section className="overflow-hidden rounded-2xl border border-line bg-panel"><div className="border-b border-line px-5 py-4"><p className="text-xs font-bold uppercase tracking-[.18em] text-muted">Full posture</p><h2 className="mt-1 text-xl font-bold text-ink">Control domains matrix</h2></div><div className="overflow-x-auto"><table className="w-full min-w-[980px] text-left text-sm"><thead className="bg-soft text-xs uppercase text-muted"><tr><th className="px-5 py-3">Domain</th><th>State</th><th>Controls</th><th>Exceptions</th><th>Evidence freshness</th><th>Next obligation</th><th>Open</th></tr></thead><tbody className="divide-y divide-line">{domains.map(([name,state,controls,exceptionsCount,freshness,next]) => <tr key={name}><th className="px-5 py-4 font-semibold text-ink">{name}</th><td><StatePill label={state} /></td><td className="font-semibold text-brand">{controls}</td><td>{exceptionsCount}</td><td>{freshness}</td><td>{next}</td><td><Link href="/risk-policy" className="text-brand">Open ↗</Link></td></tr>)}</tbody></table></div></section>

        <div className="grid gap-5 lg:grid-cols-2"><section className="rounded-2xl border border-line bg-panel p-5"><div className="flex items-center justify-between"><h2 className="text-lg font-bold text-ink">Source & knowledge governance</h2><StatePill label="Assessment overdue" /></div><div className="mt-4 space-y-2 text-sm text-muted"><p>2 licenses expire within 30 days</p><p>3 source bundles have delayed evidence</p><p>1 blocked production bundle</p><p>1 provenance exception</p></div></section><section className="rounded-2xl border border-line bg-panel p-5"><div className="flex items-center justify-between"><h2 className="text-lg font-bold text-ink">Audit / incident readiness</h2><span className="inline-flex items-center gap-1 text-ok"><CheckCircle2 size={15} />Effective</span></div><div className="mt-4 space-y-2 text-sm text-muted"><p>0 critical / 1 high open incidents</p><p>2 escalations in progress</p><p>1 overdue corrective action</p></div></section></div>
      </div>
    </main>
  );
}
