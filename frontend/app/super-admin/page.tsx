"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Activity, AlertTriangle, BadgeCheck, Building2, Clock, Cpu, CreditCard, FileSearch, KeyRound, Lock,
  ShieldAlert, ShieldCheck, ShieldX,
} from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { useLiveData } from "@/components/overview/useLiveData";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import {
  Badge, Breadcrumb, DetailRows, EmptyState, KpiRow, KpiTile, OpsHero, Panel, PillTabs, humanize, timeAgo, utcDate,
} from "@/components/operations/ui";
import { getPlatformCommand, type PlatformCommand, type PlatformControlState } from "@/lib/api";
import { usePlatformDirectory } from "@/components/platform/directory";

/** Super Admin Command Center: platform metadata across every tenant. The
 * API returns counts, states and references only; nothing on this page is a
 * tenant's financial record, document or Kriton conversation. */

const STATE: Record<PlatformControlState, { tone: "ok" | "warn" | "bad" | "neutral" | "info"; label: string }> = {
  pass: { tone: "ok", label: "Enforced" },
  review: { tone: "warn", label: "Review" },
  pending: { tone: "info", label: "Pending" },
  fail: { tone: "bad", label: "Failed" },
  unknown: { tone: "neutral", label: "Unknown" },
};
const PRIORITY_TONE = { Critical: "bad", High: "warn", Medium: "info" } as const;
type PriorityTab = "all" | "Critical" | "High" | "Medium";

function money(byCurrency: Record<string, number>): string {
  const entries = Object.entries(byCurrency);
  if (!entries.length) return "—";
  return entries.map(([currency, cents]) =>
    new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: 0 }).format(cents / 100)).join(" · ");
}

export default function SuperAdminPage() {
  const { profile, profileLoading } = useAuth();
  if (!profile && profileLoading) return <main className="flex-1 p-4" aria-busy="true" />;
  if (profile?.platform_role !== "super_admin") {
    return (
      <main className="flex-1 p-4">
        <EmptyState icon={ShieldX} title="Platform Super Admin access required">
          The control plane is granted separately from your workspace role. Ask the platform security owner if you need it.
        </EmptyState>
      </main>
    );
  }
  return <CommandCenter />;
}

function CommandCenter() {
  const { data, error, loading, signedOut, reload } = useLiveData("platform-command", (token, signal) => getPlatformCommand(token, signal), 60_000);
  const [tab, setTab] = useState<PriorityTab>("all");

  return (
    <main className="flex-1 space-y-4 overflow-y-auto p-4">
      <Breadcrumb section="Platform control plane" page="Super Admin Command" />
      <OpsHero icon={ShieldCheck} eyebrow="Platform command" title="Super Admin Command Center"
        subtitle="Platform assurance, executive decisions, and governed Kriton operations.">
        {data && (data.summary.controlExceptions > 0
          ? <p className="font-bold text-accent">Attention required · {data.summary.controlExceptions} control exception{data.summary.controlExceptions === 1 ? "" : "s"}</p>
          : <p className="font-bold text-white">No control exceptions</p>)}
        <p>Global platform · all tenants</p>
        {data && <p className="text-xs text-white/70">Measured {utcDate(data.generatedAt)}</p>}
      </OpsHero>
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />
      {data && <Body data={data} tab={tab} setTab={setTab} />}
    </main>
  );
}

function Body({ data, tab, setTab }: { data: PlatformCommand; tab: PriorityTab; setTab: (t: PriorityTab) => void }) {
  const s = data.summary;
  const now = new Date(data.generatedAt).getTime();
  const decisions = tab === "all" ? data.decisions : data.decisions.filter((d) => d.priority === tab);
  const isolation = STATE[s.isolation];
  const availability = s.availabilityPct;

  return (
    <>
      <KpiRow>
        <KpiTile icon={AlertTriangle} value={s.criticalIncidents} label="Critical incidents" tone={s.criticalIncidents ? "bad" : "ok"}
          hint={`${s.openIncidents} open · ${s.unassignedIncidents} unassigned`} hintTone={s.unassignedIncidents ? "bad" : undefined} />
        <KpiTile icon={Lock} value={s.releaseHolds} label="Release holds" tone={s.releaseHolds ? "bad" : "ok"}
          hint={`${s.openReleases} open candidate${s.openReleases === 1 ? "" : "s"}`} />
        <KpiTile icon={Clock} value={s.decisions} label="Decisions requiring action" tone={s.decisions ? "warn" : "ok"}
          hint={["Critical", "High", "Medium"].map((p) => `${s.decisionsByPriority[p] ?? 0} ${p.toLowerCase()}`).join(" · ")} />
        <KpiTile icon={ShieldCheck} value={s.isolation === "pass" ? "Active" : isolation.label} label="Tenant isolation controls"
          tone={s.isolation === "pass" ? "ok" : s.isolation === "fail" ? "bad" : "neutral"} hint="No standing data access" />
        <KpiTile icon={Activity} value={availability === null ? "Unknown" : `${availability}%`} label="30-day API availability"
          tone={availability === null ? "neutral" : availability >= s.objectivePct ? "ok" : "bad"}
          hint={availability === null ? "No health samples yet" : `Objective ${s.objectivePct}%${availability < s.objectivePct ? " · below objective" : ""}`} />
        <KpiTile icon={KeyRound} value={s.privilegedRequests} label="Privileged-access requests" tone={s.privilegedAwaitingApproval ? "warn" : "ok"}
          hint={`${s.privilegedAwaitingApproval} awaiting independent approval`} />
      </KpiRow>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <Panel title="Executive Decision Queue" meta="Risk-ranked items needing an accountable decision">
          <PillTabs label="Priority" active={tab} onChange={setTab} tabs={[
            { key: "all", label: "All", count: data.decisions.length },
            ...(["Critical", "High", "Medium"] as const).map((p) => ({ key: p, label: p, count: s.decisionsByPriority[p] ?? 0 })),
          ]} />
          {decisions.length ? (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[640px] text-sm">
                <thead><tr className="border-b border-line text-left text-[11px] uppercase tracking-wide text-muted">
                  <th className="py-2 pr-3">Priority</th><th className="py-2 pr-3">Decision</th><th className="py-2 pr-3">Owner</th>
                  <th className="py-2 pr-3">Tenant</th><th className="py-2">Waiting</th></tr></thead>
                <tbody>{decisions.map((d) => (
                  <tr key={`${d.area}-${d.id}`} className="border-b border-line last:border-0">
                    <td className="py-2.5 pr-3"><Badge tone={PRIORITY_TONE[d.priority]}>{d.priority}</Badge></td>
                    <td className="py-2.5 pr-3"><div className="text-xs text-muted">{d.ref}</div><div className="font-semibold text-ink">{d.title}</div>
                      <div className="text-xs text-muted">{d.area} · {d.state}</div></td>
                    <td className="py-2.5 pr-3 text-ink">{d.owner}</td>
                    <td className="py-2.5 pr-3 text-ink">{d.tenant}</td>
                    <td className="py-2.5 text-ink">{timeAgo(d.since, now)}</td>
                  </tr>))}</tbody>
              </table>
            </div>
          ) : <EmptyState icon={BadgeCheck} title="Nothing waiting for a decision" />}
        </Panel>

        <Panel title="Global Platform Assurance" meta="Each control from its own evidence, never averaged">
          <ul className="divide-y divide-line">
            {data.controls.map((c) => (
              <li key={c.key} className="flex items-start justify-between gap-3 py-2.5">
                <div className="min-w-0"><div className="text-sm font-semibold text-ink">{c.label}</div><div className="text-xs text-muted">{c.detail}</div></div>
                <Badge tone={STATE[c.state].tone}>{STATE[c.state].label}</Badge>
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Reliability & Service Impact" meta="Latest check in the last 15 minutes">
          <div className="grid grid-cols-3 gap-2">
            {[[availability === null ? "—" : `${availability}%`, "API availability · 30d"],
              [data.health.p95LatencyMs === null ? "—" : `${data.health.p95LatencyMs} ms`, "p95 response · 24h"],
              [data.health.sampled ? `${data.health.degraded} / ${data.health.measured}` : "—", "Services not operational"]].map(([v, l]) => (
              <div key={l} className="rounded-lg border border-line p-2.5"><div className="text-lg font-extrabold text-ink">{v}</div><div className="text-[11px] text-muted">{l}</div></div>
            ))}
          </div>
          {data.health.sampled ? (
            <ul className="mt-3 divide-y divide-line text-sm">
              {data.health.services.map((svc) => (
                <li key={svc.key} className="flex items-center justify-between gap-2 py-1.5">
                  <span className="flex items-center gap-2 text-ink">
                    <span aria-hidden className={`h-2 w-2 rounded-full ${svc.state === "operational" ? "bg-ok" : svc.state === "down" ? "bg-bad" : "bg-muted"}`} />
                    {svc.name}{svc.core && <span className="text-[10px] font-bold uppercase text-muted">core</span>}
                  </span>
                  <span className="text-xs text-muted">{humanize(svc.state)}{svc.latencyMs !== null ? ` · ${svc.latencyMs} ms` : ""}</span>
                </li>
              ))}
            </ul>
          ) : <EmptyState icon={Activity} title="Unknown: no health samples in the last 15 minutes" />}
        </Panel>

        <Panel title="Kriton AI Control Plane" meta="Release eligibility and evaluation evidence">
          <DetailRows rows={[
            ["Latest evaluation", data.evaluation.latest ? `${humanize(data.evaluation.latest.status.toLowerCase())} · ${timeAgo(data.evaluation.latest.at, now)}` : "No run recorded"],
            ["Last 10 runs", `${data.evaluation.recent.completed} completed · ${data.evaluation.recent.failed} failed`],
            ["Release candidates", `${data.releases.open} open · ${data.releases.held} held`],
          ]} />
          {data.evaluation.metrics.length > 0 && (
            <ul className="mt-3 space-y-1 text-sm">
              {data.evaluation.metrics.map((m) => (
                <li key={m.name} className="flex justify-between gap-2"><span className="text-ink">{humanize(m.name)}</span><span className="font-semibold text-ink">{m.value}</span></li>
              ))}
            </ul>
          )}
          {data.releases.items.length > 0 && (
            <ul className="mt-3 space-y-1.5">
              {data.releases.items.map((r) => (
                <li key={`${r.tenant}-${r.ref}`} className="flex items-center justify-between gap-2 rounded-lg border border-line px-2.5 py-1.5 text-sm">
                  <span className="min-w-0"><span className="font-semibold text-ink">{r.name} {r.version}</span><span className="block text-xs text-muted">{r.ref} · {r.tenant}</span></span>
                  <Badge tone={r.held ? "bad" : "info"}>{r.held ? "Hold" : "In progress"}</Badge>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <TenantGovernance data={data} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Commercial Assurance" meta={`Statement totals · ${data.commercial.month}`}>
          <div className="grid grid-cols-3 gap-2">
            {[[money(data.commercial.invoiced), "Invoiced MTD"], [money(data.commercial.collected), "Collected MTD"],
              [money(data.commercial.receivable), "Open receivables"]].map(([v, l]) => (
              <div key={l} className="rounded-lg border border-line p-2.5"><div className="break-words text-base font-extrabold text-ink">{v}</div><div className="text-[11px] text-muted">{l}</div></div>
            ))}
          </div>
          <DetailRows rows={[
            ["Unpaid statements", data.commercial.unpaidStatements],
            ["Metering disputes open", data.commercial.openDisputes],
            ["Credits pending approval", data.commercial.pendingCredits],
          ]} />
        </Panel>

        <Panel title="Privileged Access Oversight" meta="Emergency access, two-person controlled">
          <DetailRows rows={[
            ["Awaiting approval", data.privileged.awaitingApproval],
            ["Active grants", data.privileged.active],
            ["Awaiting post-access review", data.privileged.awaitingReview],
          ]} />
          {data.privileged.activeGrants.length > 0 ? (
            <ul className="mt-3 space-y-1.5">
              {data.privileged.activeGrants.map((g) => (
                <li key={g.ref} className="flex items-center justify-between gap-2 rounded-lg border border-accent/40 bg-accent/5 px-2.5 py-1.5 text-sm">
                  <span><span className="font-semibold text-ink">{g.ref}</span><span className="block text-xs text-muted">{g.tenant}</span></span>
                  <span className="text-xs font-semibold text-accent-ink">Expires {timeAgo(g.expiresAt, now).replace(" ago", "")}</span>
                </li>
              ))}
            </ul>
          ) : <p className="mt-3 flex items-center gap-2 text-sm text-muted"><ShieldAlert size={14} /> No active emergency access</p>}
        </Panel>

        <Panel title="Evidence & Audit" meta="Integrity and controlled exports">
          <DetailRows rows={[
            ["Audit events · 24h", data.audit.events24h],
            ["Evidence exports pending", data.audit.exportsPending],
            ["Refused access attempts · 30d", data.audit.deniedAttempts30d],
          ]} />
          <p className="mt-3 flex items-center gap-2 text-xs text-muted"><FileSearch size={14} /> Every refusal is recorded in the audit ledger.</p>
        </Panel>
      </div>

      <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
        <span className="flex items-center gap-1"><Building2 size={12} /> Tenant names are shown as metadata only</span>
        <span className="flex items-center gap-1"><CreditCard size={12} /> Billing shows statement totals, never invoice lines</span>
        <span className="flex items-center gap-1"><Cpu size={12} /> No Kriton prompts or answers</span>
      </p>
    </>
  );
}

/** Companies and sign-ins at a glance, from the platform directory, with the
 * way into the full Companies and Accounts pages. */
function TenantGovernance({ data }: { data: PlatformCommand }) {
  const { data: directory } = usePlatformDirectory();
  const d = directory?.summary;
  return (
    <Panel title="Companies & Accounts" meta="Live sign-in activity"
      action={<Link href="/super-admin/companies" className="text-xs font-semibold text-info hover:underline">View all</Link>}>
      <DetailRows rows={[
        ["Companies", d ? `${d.companies} · ${d.personalWorkspaces} personal` : data.tenants.total],
        ["Online now", d ? `${d.companiesOnline} companies · ${d.online} accounts` : "—"],
        ["Signed in · 24 h", d ? `${d.companiesSignedIn24h} companies · ${d.signedIn24h} accounts` : "—"],
        ["Active in 30 days", d ? d.companiesActive30d : data.tenants.active30d],
        ["Accounts", d ? d.accounts : data.tenants.users],
        ["Approved billing plan", data.tenants.withApprovedPlan],
      ]} />
      <div className="mt-3 flex gap-3 text-sm">
        <Link href="/super-admin/companies" className="font-semibold text-info hover:underline">Companies</Link>
        <Link href="/super-admin/accounts" className="font-semibold text-info hover:underline">Accounts</Link>
      </div>
    </Panel>
  );
}
