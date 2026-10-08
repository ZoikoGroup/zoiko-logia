"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AlertTriangle, ArrowRight, CheckCircle2, CircleAlert, Clock3, Download, FileCheck2, Loader2 } from "lucide-react";
import { getAuthToken, getGovernanceDashboard } from "@/lib/api";

// Shape returned by GET /api/v1/governance-dashboard (backend/app/domains/governance_dashboard).
type DomainState = { name: string; state: "attention_required" | "no_open_exceptions" | "restricted" | "not_assessed"; openExceptions: number; href: string };
type GovException = { id: string; severity: "Critical" | "High"; domain: string; title: string; detail: string; openedAt: string | null; href: string };
type Decision = { id: string; kind: string; severity: string; title: string; createdAt: string | null; href: string };
type Release = { runId: string; status: string; createdAt: string | null; promotionEligible: boolean; zeroTolerancePassed: boolean | null; contaminationScan: string | null; decision: string | null; blocked: boolean };
type GovernanceData = {
  governanceScope: { workspaceName: string; environment: string; jurisdictionCodes: string[]; assessmentWindow: { label: string } };
  governanceSummary: { overallState: string; criticalExceptionCount: number; highExceptionCount: number; pendingDecisionCount: number; blockedGateCount: number; partialDataDomains: string[]; lastEvaluatedAt: string };
  domainStates: DomainState[];
  exceptions: GovException[];
  decisions: Decision[];
  releaseReadiness: Release[];
  accountabilitySummary: { mandatoryReviews: number; overdueReviews: number; boundaryEscalations: number };
  sourceGovernanceSummary: { state: string; licenseStates: Record<string, number>; expiringWithin30Days: number; expired?: number };
  auditIncidentSummary: { ledgerState: string; ledgerEventsChecked?: number; ledgerWindow?: number;openIncidentCounts: Record<string, number>; escalationCounts: Record<string, number> };
};

const OPTIONS = { environment: "PRODUCTION", jurisdiction: "US", windowDays: 30 };

const STATE_LABEL: Record<DomainState["state"], string> = {
  attention_required: "Attention required",
  no_open_exceptions: "No open exceptions",
  restricted: "Restricted for your role",
  not_assessed: "Not assessed",
};

function StatePill({ state }: { state: DomainState["state"] }) {
  const tone = state === "attention_required" ? "bg-bad/10 text-bad" : state === "no_open_exceptions" ? "bg-ok/10 text-ok" : "bg-chip text-muted";
  return <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${tone}`}>{STATE_LABEL[state]}</span>;
}

function age(iso: string | null): string {
  if (!iso) return "";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  return days <= 0 ? "opened today" : `${days}d open`;
}

function plural(n: number, one: string, many: string) {
  return `${n} ${n === 1 ? one : many}`;
}

function exportJson(data: GovernanceData) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `governance-dashboard-${new Date().toISOString().slice(0, 10)}.json`;
  link.click();
  URL.revokeObjectURL(url);
}

export function GovernanceDashboard() {
  const [data, setData] = useState<GovernanceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    getGovernanceDashboard(getAuthToken(), OPTIONS, controller.signal)
      .then((result) => setData(result as unknown as GovernanceData))
      .catch((err) => {
        if (err?.name === "AbortError") return;
        setError(err?.status === 403 ? "The Governance Dashboard is not available for your role." : "Could not load the Governance Dashboard from the server.");
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  const summary = data?.governanceSummary;
  const scope = data?.governanceScope;
  const incidents = data?.auditIncidentSummary.openIncidentCounts ?? {};
  const escalations = data?.auditIncidentSummary.escalationCounts ?? {};
  const sources = data?.sourceGovernanceSummary;

  return (
    <main className="flex-1 overflow-y-auto bg-canvas p-4 lg:p-6">
      <div className="mx-auto max-w-[1500px] space-y-5">
        <div className="rounded-2xl border border-line bg-panel p-4 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div><p className="text-sm font-semibold text-ink">{scope ? `${scope.workspaceName} · Workspace scope` : "Workspace scope"}</p><p className="mt-1 text-xs text-muted">{scope ? `${scope.environment} · Jurisdictions: ${scope.jurisdictionCodes.join(", ")} · ${scope.assessmentWindow.label}` : "Loading scope…"}</p></div>
            {summary && <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-ok"><Clock3 size={15} />Evaluated {new Date(summary.lastEvaluatedAt).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}</span>}
          </div>
        </div>

        {summary && summary.partialDataDomains.length > 0 && <div className="rounded-xl border border-warn/30 bg-warn/10 px-4 py-3 text-sm text-warn">Partial governance view: {summary.partialDataDomains.join(", ")} {summary.partialDataDomains.length === 1 ? "is" : "are"} restricted for your role or not assessed yet.</div>}

        <header className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-ink">Governance Dashboard</h1>
            <p className="mt-1 text-muted">Evidence-backed oversight of AI, source, professional, release and operational controls.</p>
            {summary && <p className="mt-2 font-semibold text-ink">{plural(summary.criticalExceptionCount, "critical exception", "critical exceptions")} · {plural(summary.highExceptionCount, "high exception", "high exceptions")} · {plural(summary.pendingDecisionCount, "decision pending", "decisions pending")} · {plural(summary.blockedGateCount, "release gate blocked", "release gates blocked")}</p>}
            {error && <p className="mt-2 text-sm text-bad">{error}</p>}
          </div>
          <div className="flex flex-wrap gap-2">
            <a href="#exceptions" className={`inline-flex min-h-11 items-center gap-2 rounded-xl px-4 text-sm font-semibold ${summary?.criticalExceptionCount ? "bg-bad text-white" : "border border-line bg-panel text-ink"}`}><AlertTriangle size={16} />Open exceptions</a>
            <a href="#decisions" className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-line bg-panel px-4 text-sm font-semibold text-ink"><FileCheck2 size={16} />Review pending decisions</a>
            <button onClick={() => data && exportJson(data)} disabled={!data} className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-line bg-panel px-4 text-sm font-semibold text-ink disabled:opacity-50"><Download size={16} />Export</button>
          </div>
        </header>

        {loading ? (
          <div className="flex items-center justify-center py-16 text-muted"><Loader2 className="mr-2 animate-spin" size={16} /> Loading Governance Dashboard…</div>
        ) : data && (
          <>
            <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {data.domainStates.map((domain) => <Link key={domain.name} href={domain.href} className="rounded-2xl border border-line bg-panel p-4 hover:bg-soft"><h2 className="font-semibold text-ink">{domain.name}</h2><div className="mt-3"><StatePill state={domain.state} /></div><p className="mt-3 text-sm text-muted">{domain.state === "restricted" || domain.state === "not_assessed" ? "No evidence shown" : plural(domain.openExceptions, "open exception", "open exceptions")}</p></Link>)}
            </section>

            <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_390px]">
              <section id="exceptions" className="overflow-hidden rounded-2xl border border-line bg-panel">
                <div className="border-b border-line px-5 py-4"><p className="text-xs font-bold uppercase tracking-[.18em] text-muted">Exception-first</p><h2 className="mt-1 text-xl font-bold text-ink">Open exceptions</h2></div>
                {data.exceptions.length ? (
                  <div className="divide-y divide-line">{data.exceptions.map((item) => <Link key={`${item.domain}:${item.id}`} href={item.href} className="block p-5 hover:bg-soft/50"><div className="flex items-start justify-between gap-4"><div><div className="flex flex-wrap items-center gap-2"><span className={`rounded-full px-2 py-0.5 text-xs font-bold ${item.severity === "Critical" ? "bg-bad/10 text-bad" : "bg-warn/10 text-warn"}`}>{item.severity}</span><span className="text-xs font-bold uppercase text-muted">{item.domain}</span></div><h3 className="mt-2 font-semibold text-ink">{item.title}</h3><p className="mt-2 text-sm text-muted">{item.detail}{item.openedAt ? ` · ${age(item.openedAt)}` : ""}</p></div><ArrowRight size={17} className="shrink-0 text-brand" /></div></Link>)}</div>
                ) : <p className="flex items-center justify-center gap-2 px-5 py-8 text-sm text-muted"><CheckCircle2 size={16} className="text-ok" />No open exceptions in the areas you can see.</p>}
              </section>

              <section id="decisions" className="overflow-hidden rounded-2xl border border-line bg-panel">
                <div className="border-b border-line px-5 py-4"><p className="text-xs font-bold uppercase tracking-[.18em] text-muted">Waiting for a decision</p><h2 className="mt-1 text-xl font-bold text-ink">Pending decisions</h2></div>
                {data.decisions.length ? (
                  <div className="divide-y divide-line">{data.decisions.map((item) => <article key={`${item.kind}:${item.id}`} className="p-5"><div className="flex justify-between gap-2"><span className={`text-xs font-bold ${item.severity === "HIGH" || item.severity === "RESTRICTED" ? "text-bad" : "text-warn"}`}>{item.severity} · {item.kind}</span>{item.createdAt && <span className="text-xs text-muted">{age(item.createdAt)}</span>}</div><h3 className="mt-3 font-semibold leading-6 text-ink">{item.title}</h3><Link href={item.href} className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-brand">Review decision <ArrowRight size={14} /></Link></article>)}</div>
                ) : <p className="px-5 py-8 text-center text-sm text-muted">No decisions are waiting for you.</p>}
              </section>
            </div>

            <section className="overflow-hidden rounded-2xl border border-line bg-panel">
              <div className="border-b border-line px-5 py-4"><p className="text-xs font-bold uppercase tracking-[.18em] text-muted">Full posture</p><h2 className="mt-1 text-xl font-bold text-ink">Control domains matrix</h2></div>
              <div className="overflow-x-auto"><table className="w-full min-w-[640px] text-left text-sm"><thead className="bg-soft text-xs uppercase text-muted"><tr><th className="px-5 py-3">Domain</th><th>State</th><th>Open exceptions</th><th>Open</th></tr></thead><tbody className="divide-y divide-line">{data.domainStates.map((domain) => <tr key={domain.name}><th className="px-5 py-4 font-semibold text-ink">{domain.name}</th><td><StatePill state={domain.state} /></td><td>{domain.state === "restricted" || domain.state === "not_assessed" ? "—" : domain.openExceptions}</td><td><Link href={domain.href} className="text-brand">Open ↗</Link></td></tr>)}</tbody></table></div>
            </section>

            {data.releaseReadiness.length > 0 && (
              <section className="overflow-hidden rounded-2xl border border-line bg-panel">
                <div className="border-b border-line px-5 py-4"><p className="text-xs font-bold uppercase tracking-[.18em] text-muted">Latest evaluation runs</p><h2 className="mt-1 text-xl font-bold text-ink">Release readiness</h2></div>
                <div className="divide-y divide-line">{data.releaseReadiness.map((run) => <div key={run.runId} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 text-sm"><span className="font-semibold text-ink">{run.runId}</span><span className="text-muted">{run.status}{run.zeroTolerancePassed === false ? " · zero-tolerance failed" : ""}{run.contaminationScan && run.contaminationScan !== "PASSED" ? " · contamination scan failed" : ""}</span><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${run.blocked ? "bg-bad/10 text-bad" : run.decision === "APPROVED" ? "bg-ok/10 text-ok" : "bg-chip text-muted"}`}>{run.blocked ? "Blocked" : run.decision ?? (run.promotionEligible ? "Awaiting sign-off" : "Not eligible")}</span></div>)}</div>
              </section>
            )}

            <div className="grid gap-5 lg:grid-cols-2">
              <section className="rounded-2xl border border-line bg-panel p-5">
                <div className="flex items-center justify-between"><h2 className="text-lg font-bold text-ink">Source & knowledge governance</h2>{sources?.state === "attention_required" ? <span className="inline-flex items-center gap-1 text-warn"><CircleAlert size={15} />Attention required</span> : <span className="text-sm text-muted">No licence exceptions</span>}</div>
                <div className="mt-4 space-y-2 text-sm text-muted"><p>{plural(sources?.expiringWithin30Days ?? 0, "licence expires", "licences expire")} within 30 days</p><p>{plural(sources?.expired ?? 0, "licence has", "licences have")} expired</p><p>Licence states: {Object.keys(sources?.licenseStates ?? {}).length ? Object.entries(sources!.licenseStates).map(([state, count]) => `${count} ${state}`).join(" · ") : "no sources on file"}</p></div>
              </section>
              <section className="rounded-2xl border border-line bg-panel p-5">
                <div className="flex items-center justify-between"><h2 className="text-lg font-bold text-ink">Audit / incident readiness</h2>{data.auditIncidentSummary.ledgerState === "verified" ? <span className="inline-flex items-center gap-1 text-sm text-ok"><CheckCircle2 size={15} />Recent ledger chain verified</span> : data.auditIncidentSummary.ledgerState === "broken" ? <span className="inline-flex items-center gap-1 text-sm text-bad"><CircleAlert size={15} />Ledger chain broken</span> : <span className="inline-flex items-center gap-1 text-sm text-warn"><CircleAlert size={15} />Ledger check unavailable</span>}</div>
                <div className="mt-4 space-y-2 text-sm text-muted"><p>Latest {plural(data.auditIncidentSummary.ledgerEventsChecked ?? 0, "audit event", "audit events")} checked{data.auditIncidentSummary.ledgerWindow ? ` (up to ${data.auditIncidentSummary.ledgerWindow}; full check on Audit Logs)` : ""}</p><p>{incidents.critical ?? 0} critical / {incidents.high ?? 0} high open incidents</p><p>{plural(Object.values(escalations).reduce((a, b) => a + b, 0), "escalation", "escalations")} open{Object.keys(escalations).length ? ` (${Object.entries(escalations).map(([s, n]) => `${n} ${s.toLowerCase().replace("_", " ")}`).join(", ")})` : ""}</p><p>{plural(data.accountabilitySummary.overdueReviews, "escalation is", "escalations are")} past SLA</p></div>
              </section>
            </div>
          </>
        )}
      </div>
    </main>
  );
}
