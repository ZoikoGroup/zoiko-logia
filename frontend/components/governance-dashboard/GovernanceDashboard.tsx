"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { AlertTriangle, ArrowRight, CheckCircle2, Clock3, Download, FileCheck2 } from "lucide-react";
import { getGovernanceDashboard } from "@/lib/api";
import type { GovernanceDashboardViewModel } from "@/lib/governance-dashboard-types";
import { useLiveData } from "@/components/overview/useLiveData";
import { EmptyRow, ErrorBlock, LoadingBlock, RefreshButton, SignedOutBlock } from "@/components/overview/states";

const WINDOWS = [7, 30, 90] as const;

function StatePill({ label }: { label: string }) {
  const danger = /failure/i.test(label);
  const good = /^effective$/i.test(label);
  const observations = /observations/i.test(label);
  return <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${danger ? "bg-bad/10 text-bad" : good ? "bg-ok/10 text-ok" : observations ? "bg-info/10 text-info" : "bg-warn/10 text-warn"}`}>{label}</span>;
}

function plural(n: number, word: string) {
  return `${n} ${n === 1 ? word : `${word}s`}`;
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });
}

function exportJson(view: GovernanceDashboardViewModel) {
  const blob = new Blob([JSON.stringify(view, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `governance-dashboard-${view.generatedAt.slice(0, 10)}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

export function GovernanceDashboard() {
  const environment = "CONNECTED";
  const [windowDays, setWindowDays] = useState<number>(30);
  const options = useRef({ environment: "CONNECTED", windowDays: 30 });
  const { data: view, error, loading, signedOut, reload } = useLiveData(`governance:${environment}:${windowDays}`, (token, signal, fresh) =>
    getGovernanceDashboard(token, { environment: options.current.environment, jurisdiction: "US", windowDays: options.current.windowDays }, signal, fresh),
  );

  function change(next: { windowDays?: number }) {
    if (next.windowDays) setWindowDays(next.windowDays);
    options.current = { environment, windowDays: next.windowDays ?? windowDays };
    reload();
  }

  if (signedOut) return <main className="flex-1 overflow-y-auto bg-canvas p-4 lg:p-6"><div className="mx-auto max-w-[1500px]"><SignedOutBlock /></div></main>;

  const s = view?.summary;
  const freshnessTone = view?.scope.evidenceFreshness === "current" ? "text-ok" : "text-warn";

  return (
    <main className="flex-1 overflow-y-auto bg-canvas p-4 lg:p-6">
      <div className="mx-auto max-w-[1500px] space-y-5">
        <div className="rounded-2xl border border-line bg-panel p-4 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-ink">{view?.scope.workspaceName ?? "Loading workspace…"} · Workspace scope</p>
              <p className="mt-1 text-xs text-muted">Connected workspace · Jurisdictions: {view?.scope.jurisdictions.join(", ") || "—"}{view ? ` · ${formatDate(view.scope.windowStart)} – ${formatDate(view.scope.windowEnd)}` : ""}</p>
            </div>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <label className="flex items-center gap-1.5 text-xs text-muted">Window
                <select value={windowDays} onChange={(e) => change({ windowDays: Number(e.target.value) })} className="rounded-lg border border-line bg-panel px-2 py-1 text-sm font-semibold text-ink">{WINDOWS.map((w) => <option key={w} value={w}>Last {w} days</option>)}</select>
              </label>
            </div>
          </div>
          {view && <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 border-t border-line pt-3 text-xs text-muted"><span>Tenant isolation: <b className="text-ok">boundary enforced</b></span><span>Evidence freshness: <b className={freshnessTone}>{view.scope.evidenceFreshness}</b></span><span>Audit ledger: <b className="text-ink">{view.scope.auditLedger.eventsInWindow.toLocaleString()} events · last {view.scope.auditLedger.lastEventAge}</b></span><span>Risk policy: <b className="text-ink">{view.scope.policyVersion}</b></span></div>}
        </div>

        {view && view.staleDomains.length > 0 && <div className="flex items-start gap-2 rounded-xl border border-warn/30 bg-warn/10 px-4 py-3 text-sm text-warn"><Clock3 size={16} className="mt-0.5 shrink-0" /><span>Partial governance view: {view.staleDomains.join(", ")} {view.staleDomains.length === 1 ? "has" : "have"} no evidence from the last {view.scope.windowDays} days.</span></div>}

        <header className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-ink">Governance Dashboard</h1>
            <p className="mt-1 text-muted">Evidence-backed oversight of AI, source, professional, release and operational controls.</p>
            {s && <p className="mt-2 font-semibold text-ink">{plural(s.criticalExceptionCount, "critical exception")} · {plural(s.highExceptionCount, "high exception")} · {plural(s.pendingDecisionCount, "decision")} pending · {plural(s.blockedGateCount, "release gate")} blocked</p>}
          </div>
          <div className="flex flex-wrap gap-2">
            <Link href="#exceptions" className={`inline-flex min-h-11 items-center gap-2 rounded-xl px-4 text-sm font-semibold ${s?.criticalExceptionCount ? "bg-bad text-white" : "border border-line bg-panel text-ink"}`}><AlertTriangle size={16} />Open exceptions</Link>
            <Link href="#decisions" className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-line bg-panel px-4 text-sm font-semibold text-ink"><FileCheck2 size={16} />Review pending decisions</Link>
            <button onClick={() => view && exportJson(view)} disabled={!view} className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-line bg-panel px-4 text-sm font-semibold text-ink disabled:opacity-60"><Download size={16} />Export</button>
            <RefreshButton onClick={reload} loading={loading} generatedAt={view?.generatedAt} />
          </div>
        </header>

        {error && <ErrorBlock message={error} onRetry={reload} />}
        {!view && loading && <LoadingBlock label="Loading Governance Dashboard" />}

        {view && <>
          <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {view.domains.map((d) => <Link href={d.href} key={d.key} className="rounded-2xl border border-line bg-panel p-4 hover:border-brand/40"><h2 className="font-semibold text-ink">{d.name}</h2><div className="mt-3"><StatePill label={d.state} /></div><p className="mt-3 text-sm text-muted">{d.metric}</p><p className={`mt-4 border-t border-line pt-3 text-sm font-semibold ${d.freshness.state === "current" ? "text-ok" : "text-warn"}`}>{d.freshness.label}</p></Link>)}
          </section>

          <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_390px]">
            <section id="exceptions" className="overflow-hidden rounded-2xl border border-line bg-panel">
              <div className="flex items-center justify-between border-b border-line px-5 py-4"><div><p className="text-xs font-bold uppercase tracking-[.18em] text-muted">Exception-first</p><h2 className="mt-1 text-xl font-bold text-ink">Open exceptions</h2></div><Link href="/alerts-center" className="text-sm font-semibold text-brand">Alerts center</Link></div>
              <div className="divide-y divide-line">
                {view.exceptions.length === 0 && <EmptyRow>No open exceptions. Incidents, overdue escalations, failed evaluation gates and expired licences appear here.</EmptyRow>}
                {view.exceptions.map((e) => <Link href={e.href} key={e.id} className="block p-5 hover:bg-soft/50"><div className="flex items-start justify-between gap-4"><div><div className="flex flex-wrap items-center gap-2"><span className={`rounded-full px-2 py-0.5 text-xs font-bold ${e.severity === "Critical" ? "bg-bad/10 text-bad" : "bg-warn/10 text-warn"}`}>{e.severity}</span><span className="text-xs font-bold uppercase text-muted">{e.domain}</span></div><h3 className="mt-2 font-semibold text-ink">{e.title}</h3><p className="mt-2 text-sm text-muted">{e.detail}</p></div><ArrowRight size={17} className="shrink-0 text-brand" /></div></Link>)}
              </div>
            </section>

            <section id="decisions" className="overflow-hidden rounded-2xl border border-line bg-panel">
              <div className="border-b border-line px-5 py-4"><p className="text-xs font-bold uppercase tracking-[.18em] text-muted">Assigned to your role</p><h2 className="mt-1 text-xl font-bold text-ink">Pending decisions</h2></div>
              <div className="divide-y divide-line">
                {view.decisions.length === 0 && <EmptyRow>No decisions are waiting on your role.</EmptyRow>}
                {view.decisions.map((d) => <article key={d.id} className="p-5"><div className="flex justify-between gap-2"><span className={`text-xs font-bold ${["HIGH", "REPORTED", "RESTRICTED"].includes(d.severity) ? "text-bad" : "text-warn"}`}>{d.severity} · {d.kind}</span><span className="text-xs text-muted">{d.due}</span></div><h3 className="mt-3 font-semibold leading-6 text-ink">{d.title}</h3><Link href={d.href} className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-brand">Review decision <ArrowRight size={14} /></Link></article>)}
                {s && s.pendingDecisionCount > view.decisions.length && <p className="px-5 py-3 text-xs text-muted">Showing {view.decisions.length} of {s.pendingDecisionCount} pending decisions.</p>}
              </div>
            </section>
          </div>

          <section className="overflow-hidden rounded-2xl border border-line bg-panel"><div className="border-b border-line px-5 py-4"><p className="text-xs font-bold uppercase tracking-[.18em] text-muted">Full posture</p><h2 className="mt-1 text-xl font-bold text-ink">Control domains matrix</h2></div><div className="overflow-x-auto"><table className="w-full min-w-[980px] text-left text-sm"><thead className="bg-soft text-xs uppercase text-muted"><tr><th className="px-5 py-3">Domain</th><th>State</th><th>Measure</th><th>Exceptions</th><th>Evidence freshness</th><th>Next obligation</th><th className="pr-5">Open</th></tr></thead><tbody className="divide-y divide-line">{view.domains.map((d) => <tr key={d.key}><th className="px-5 py-4 font-semibold text-ink">{d.name}</th><td><StatePill label={d.state} /></td><td className="font-semibold text-brand">{d.metric}</td><td>{d.exceptions}</td><td className={d.freshness.state === "current" ? "text-ok" : "text-warn"}>{d.freshness.label}</td><td>{d.next}</td><td className="pr-5"><Link href={d.href} className="text-brand">Open ↗</Link></td></tr>)}</tbody></table></div></section>

          <div className="grid gap-5 lg:grid-cols-2">
            <section className="rounded-2xl border border-line bg-panel p-5"><div className="flex items-center justify-between"><h2 className="text-lg font-bold text-ink">Source & knowledge governance</h2><StatePill label={view.panels.sources.state} /></div><div className="mt-4 space-y-2 text-sm text-muted">{view.panels.sources.lines.map((line) => <p key={line}>{line}</p>)}</div></section>
            <section className="rounded-2xl border border-line bg-panel p-5"><div className="flex items-center justify-between"><h2 className="text-lg font-bold text-ink">Audit / incident readiness</h2>{/^effective$/i.test(view.panels.audit.state) ? <span className="inline-flex items-center gap-1 text-ok"><CheckCircle2 size={15} />Effective</span> : <StatePill label={view.panels.audit.state} />}</div><div className="mt-4 space-y-2 text-sm text-muted">{view.panels.audit.lines.map((line) => <p key={line}>{line}</p>)}</div></section>
          </div>
        </>}
      </div>
    </main>
  );
}
