"use client";

import { Fragment, useState, type ReactNode } from "react";
import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import {
  Activity, AlertTriangle, ArrowRight, BadgeCheck, CircleCheck, Clock, CreditCard, KeyRound, Lock, Server, ShieldCheck, ShieldX, Zap,
} from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { useLiveData } from "@/components/overview/useLiveData";
import { EmptyState, humanize, timeAgo, utcDate } from "@/components/operations/ui";
import { getPlatformCommand, type PlatformCommand, type PlatformControlState } from "@/lib/api";
import { usePlatformDirectory } from "@/components/platform/directory";

/** Building blocks of the Super Admin Command Center and its section pages,
 * laid out after the ZoikoLogia command-center design. Platform metadata
 * only: the API returns counts, states and references, never a tenant's
 * financial record, document or Kriton conversation, and every figure is
 * live (the design's sample figures are never shown). */

export type Tone = "ok" | "warn" | "bad" | "info" | "neutral";

export const STATE: Record<PlatformControlState, { tone: Tone; label: string }> = {
  pass: { tone: "ok", label: "Enforced" },
  review: { tone: "warn", label: "Review" },
  pending: { tone: "warn", label: "Pending" },
  fail: { tone: "bad", label: "Failed" },
  unknown: { tone: "neutral", label: "Unknown" },
};
const PRIORITY_TONE = { Critical: "bad", High: "warn", Medium: "info" } as const;
type PriorityTab = "all" | "Critical" | "High" | "Medium";

const PILL: Record<Tone, string> = {
  ok: "bg-[#E3F5EA] text-[#1F7A4D]",
  warn: "bg-[#FDEBD3] text-[#B45309]",
  bad: "bg-[#FBE3E1] text-[#C0392B]",
  info: "bg-[#E3EDFB] text-[#1F5FAE]",
  neutral: "bg-chip text-muted",
};
const ICON_BOX: Record<Tone, string> = {
  ok: "bg-[#E3F5EA] text-[#1F7A4D]",
  warn: "bg-[#FDEBD3] text-[#D9761A]",
  bad: "bg-[#FBE3E1] text-[#C0392B]",
  info: "bg-[#E3EDFB] text-[#1F5FAE]",
  neutral: "bg-chip text-muted",
};
const HINT: Record<Tone, string> = {
  ok: "font-semibold text-[#1F7A4D]", warn: "font-semibold text-[#B45309]", bad: "font-semibold text-[#C0392B]",
  info: "text-muted", neutral: "text-muted",
};
const DOT: Record<Tone, string> = { ok: "bg-[#1F9D60]", warn: "bg-[#E8862A]", bad: "bg-[#D64545]", info: "bg-[#2F6FC4]", neutral: "bg-muted" };
const BAR: Record<Tone, string> = { ok: "bg-[#2F6FC4]", warn: "bg-[#F0962F]", bad: "bg-[#D9534F]", info: "bg-[#2F6FC4]", neutral: "bg-muted" };

// Keys from the backend's platform controls (domains/platform/service.py).
const CONTROL_ICON: Record<string, LucideIcon> = {
  isolation: Lock, privileged: KeyRound, releases: Zap, evaluation: CircleCheck, providers: Server, resilience: Activity,
  billing: CreditCard,
};

function money(byCurrency: Record<string, number>): string {
  const entries = Object.entries(byCurrency);
  if (!entries.length) return "—";
  return entries.map(([currency, cents]) =>
    new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: 0 }).format(cents / 100)).join(" · ");
}

export function Pill({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className={`inline-flex items-center whitespace-nowrap rounded-md px-2 py-0.5 text-[11px] font-bold ${PILL[tone]}`}>{children}</span>;
}

export function Card({ title, meta, aside, children, className = "" }: {
  title: string; meta: string; aside?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={`flex flex-col rounded-xl border border-line bg-panel shadow-[0_2px_10px_rgba(13,34,64,0.04)] ${className}`}>
      <header className="flex items-start justify-between gap-3 border-b border-line px-[18px] py-3.5">
        <div className="min-w-0">
          <h2 className="text-[17px] font-bold leading-tight text-ink">{title}</h2>
          <p className="mt-0.5 text-xs text-muted">{meta}</p>
        </div>
        {aside}
      </header>
      <div className="flex-1 px-[18px] py-4">{children}</div>
    </section>
  );
}

function Tile({ icon: Icon, tone, label, value, hint, hintTone }: {
  icon: LucideIcon; tone: Tone; label: string; value: ReactNode; hint: string; hintTone: Tone;
}) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-line bg-panel p-3.5 shadow-[0_2px_10px_rgba(13,34,64,0.04)]">
      <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg ${ICON_BOX[tone]}`}><Icon size={18} /></span>
      <div className="min-w-0">
        <div className="text-[11px] font-semibold text-ink/80">{label}</div>
        <div className="text-[26px] font-extrabold leading-tight tracking-tight text-ink">{value}</div>
        <div className={`truncate text-[11px] ${HINT[hintTone]}`}>{hint}</div>
      </div>
    </div>
  );
}

function StatBox({ value, label }: { value: ReactNode; label: string }) {
  return (
    <div className="rounded-lg border border-line p-2.5">
      <div className="break-words text-lg font-extrabold text-ink">{value}</div>
      <div className="text-[10px] text-muted">{label}</div>
    </div>
  );
}

function Row({ title, detail, right }: { title: ReactNode; detail?: ReactNode; right: ReactNode }) {
  return (
    <li className="flex items-center justify-between gap-3 border-b border-line py-2.5 last:border-0">
      <div className="min-w-0">
        <div className="text-sm font-semibold text-ink">{title}</div>
        {detail && <div className="text-xs text-muted">{detail}</div>}
      </div>
      <div className="shrink-0">{right}</div>
    </li>
  );
}

export function CommandMark() {
  return (
    <span className="grid h-16 w-16 shrink-0 place-items-center rounded-2xl border-2 border-white/70 bg-[#123A66]">
      <svg width="34" height="34" viewBox="0 0 34 34" aria-hidden="true">
        <rect x="3" y="4" width="28" height="26" rx="3" fill="none" stroke="#F28C28" strokeWidth="2.5" />
        {[10, 15.5, 21].map((x) => <rect key={x} x={x} y="9" width="3.5" height="16" rx="1" fill="#F28C28" />)}
      </svg>
    </span>
  );
}

/** Platform Super Admins only; nobody else's view calls the API. */
export function SuperAdminGate({ children }: { children: ReactNode }) {
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
  return <>{children}</>;
}

export function usePlatformCommand() {
  return useLiveData("platform-command", (token, signal) => getPlatformCommand(token, signal), 60_000);
}

/** A platform control's own detail line, from its evidence (backend
 * domains/platform/service.py), or null when the control is not reported. */
function controlDetail(data: PlatformCommand, key: string): string | null {
  return data.controls.find((c) => c.key === key)?.detail ?? null;
}

export function SummaryTiles({ data }: { data: PlatformCommand }) {
  const s = data.summary;
  const availability = s.availabilityPct;
  const byPriority = (p: string) => s.decisionsByPriority[p] ?? 0;
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6">
      <Tile icon={AlertTriangle} tone={s.criticalIncidents ? "warn" : "ok"} label="Critical incidents" value={s.criticalIncidents}
        hint={`${s.openIncidents} open · ${s.unassignedIncidents} unassigned`} hintTone={s.unassignedIncidents ? "bad" : "neutral"} />
      <Tile icon={Lock} tone={s.releaseHolds ? "bad" : "ok"} label="Production release holds" value={s.releaseHolds}
        hint={`${s.openReleases} open candidate${s.openReleases === 1 ? "" : "s"}`} hintTone={s.releaseHolds ? "bad" : "neutral"} />
      <Tile icon={Clock} tone={s.decisions ? "warn" : "ok"} label="Decisions requiring action" value={s.decisions}
        hint={["Critical", "High", "Medium"].map((p) => `${byPriority(p)} ${p.toLowerCase()}`).join(" · ")} hintTone="neutral" />
      <Tile icon={ShieldCheck} tone={s.isolation === "pass" ? "ok" : s.isolation === "fail" ? "bad" : "neutral"} label="Tenant isolation controls"
        value={s.isolation === "pass" ? "Active" : STATE[s.isolation].label} hint={controlDetail(data, "isolation") ?? "Not reported"}
        hintTone={s.isolation === "pass" ? "ok" : "neutral"} />
      <Tile icon={Activity} tone="info" label="30-day API availability" value={availability === null ? "Unknown" : `${availability}%`}
        hint={availability === null ? "No health samples yet" : `Target ${s.objectivePct}%${availability < s.objectivePct ? " · below SLO" : ""}`}
        hintTone={availability !== null && availability < s.objectivePct ? "bad" : "neutral"} />
      <Tile icon={KeyRound} tone={s.privilegedAwaitingApproval ? "warn" : "ok"} label="Privileged-access requests" value={s.privilegedRequests}
        hint={`${s.privilegedAwaitingApproval} awaiting dual approval`} hintTone={s.privilegedAwaitingApproval ? "bad" : "neutral"} />
    </div>
  );
}

/** When the longest-waiting decision began waiting (null when none says). */
function oldestSince(decisions: PlatformCommand["decisions"]): string | null {
  return decisions.map((d) => d.since).filter((since): since is string => Boolean(since)).sort()[0] ?? null;
}

export function DecisionQueue({ data, areas }: { data: PlatformCommand; areas?: RegExp }) {
  const [tab, setTab] = useState<PriorityTab>("all");
  const [open, setOpen] = useState<string | null>(null);
  const now = new Date(data.generatedAt).getTime();
  const all = areas ? data.decisions.filter((d) => areas.test(d.area)) : data.decisions;
  const decisions = tab === "all" ? all : all.filter((d) => d.priority === tab);
  const count = (p: string) => all.filter((d) => d.priority === p).length;
  const tabs: { key: PriorityTab; label: string; count: number }[] = [
    { key: "all", label: "All", count: all.length },
    ...(["Critical", "High", "Medium"] as const).map((p) => ({ key: p, label: p, count: count(p) })),
  ];

  return (
    <Card title="Executive Decision Queue" meta={all.length ? `${all.length} waiting · oldest ${timeAgo(oldestSince(all), now)}` : "Nothing waiting"}
      aside={<span className="rounded-md border border-accent/50 bg-[#FDF1E3] px-2 py-1 text-[11px] font-bold text-[#B45309]">
        {all.length} decision{all.length === 1 ? "" : "s"} · {count("Critical")} critical</span>}>
      <div role="tablist" aria-label="Priority" className="flex flex-wrap gap-2">
        {tabs.map((t) => (
          <button key={t.key} role="tab" aria-selected={t.key === tab} onClick={() => setTab(t.key)}
            className={`h-8 rounded-full border px-3.5 text-xs font-semibold transition ${t.key === tab
              ? "border-accent bg-[#FDF1E3] text-[#B45309]" : "border-line bg-panel text-ink hover:bg-soft"}`}>
            {t.label} ({t.count})
          </button>
        ))}
      </div>
      {decisions.length ? (
        <div className="-mx-[18px] mt-3 overflow-x-auto">
          <table className="w-full min-w-[680px] text-sm">
            <thead><tr className="bg-soft text-left text-[10px] font-bold uppercase tracking-[0.08em] text-muted">
              <th className="px-[18px] py-2.5">Priority</th><th className="py-2.5 pr-3">Control decision</th><th className="py-2.5 pr-3">Accountable owner</th>
              <th className="py-2.5 pr-3">Tenant</th><th className="py-2.5 pr-3">Waiting</th><th className="py-2.5 pr-[18px]">Action</th></tr></thead>
            <tbody>{decisions.map((d) => {
              const key = `${d.area}-${d.id}`;
              return (
                <Fragment key={key}>
                  <tr className="border-b border-line">
                    <td className="px-[18px] py-3"><Pill tone={PRIORITY_TONE[d.priority]}>{d.priority}</Pill></td>
                    <td className="py-3 pr-3"><div className="text-[11px] text-muted">{d.ref}</div><div className="font-bold text-ink">{d.title}</div>
                      <div className="text-[11px] text-muted">{d.area}</div></td>
                    <td className="py-3 pr-3 text-ink">{d.owner}</td>
                    <td className="py-3 pr-3 text-ink">{d.tenant}</td>
                    <td className="py-3 pr-3 font-semibold text-ink">{timeAgo(d.since, now)}</td>
                    <td className="py-3 pr-[18px]">
                      <button type="button" onClick={() => setOpen(open === key ? null : key)} aria-expanded={open === key}
                        className="inline-flex items-center gap-1 rounded-md border border-line px-2.5 py-1 text-xs font-bold text-[#1F5FAE] hover:bg-soft">
                        Inspect <ArrowRight size={12} />
                      </button>
                    </td>
                  </tr>
                  {open === key && (
                    <tr className="border-b border-line bg-soft/60"><td colSpan={6} className="px-[18px] py-2.5 text-xs text-ink">
                      <span className="font-semibold">State:</span> {d.state} · <span className="font-semibold">Area:</span> {d.area} ·{" "}
                      <span className="font-semibold">Owner:</span> {d.owner} · <span className="font-semibold">Since:</span> {d.since ? utcDate(d.since) : "Unknown"}
                    </td></tr>
                  )}
                </Fragment>
              );
            })}</tbody>
          </table>
        </div>
      ) : <EmptyState icon={BadgeCheck} title="Nothing waiting for a decision" />}
      <p className="mt-3 text-xs text-muted">Showing {decisions.length} of {all.length} decision{all.length === 1 ? "" : "s"}</p>
    </Card>
  );
}

export function Assurance({ data, keys }: { data: PlatformCommand; keys?: RegExp }) {
  const controls = keys ? data.controls.filter((c) => keys.test(c.key) || keys.test(c.label)) : data.controls;
  const failed = controls.filter((c) => c.state === "fail");
  const exceptions = controls.filter((c) => c.state === "fail" || c.state === "review").length;
  return (
    <Card title="Global Platform Assurance" meta={`${controls.length} control${controls.length === 1 ? "" : "s"} · measured ${utcDate(data.generatedAt)}`}
      aside={<Pill tone={failed.length ? "bad" : exceptions ? "warn" : "ok"}>
        {exceptions ? `${exceptions} exception${exceptions === 1 ? "" : "s"}` : `${controls.length} enforced`}</Pill>}>
      {!keys && data.releases.held > 0 ? (
        <div className="mb-3 flex items-start gap-3 rounded-lg border border-accent/50 bg-[#FDF1E3] p-3">
          <AlertTriangle size={20} className="mt-0.5 shrink-0 text-[#D9761A]" />
          <div><p className="text-sm font-bold text-[#B45309]">Release assurance is on hold</p>
            <p className="text-xs text-[#B45309]/90">{data.releases.held} release candidate{data.releases.held === 1 ? "" : "s"} held; production promotion blocked</p></div>
        </div>
      ) : failed.length > 0 && (
        <div className="mb-3 flex items-start gap-3 rounded-lg border border-[#C0392B]/30 bg-[#FBE3E1] p-3">
          <AlertTriangle size={20} className="mt-0.5 shrink-0 text-[#C0392B]" />
          <div><p className="text-sm font-bold text-[#C0392B]">{failed.length} mandatory control{failed.length === 1 ? "" : "s"} failed</p>
            <p className="text-xs text-[#C0392B]/90">{failed.map((c) => c.label).join(" · ")}</p></div>
        </div>
      )}
      {controls.length ? (
        <ul>
          {controls.map((c) => {
            const Icon = CONTROL_ICON[c.key] ?? ShieldCheck;
            return (
              <li key={c.key} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 border-b border-line py-2.5 last:border-0">
                <span className="flex min-w-0 items-center gap-2.5 text-sm font-semibold text-ink"><Icon size={15} className="shrink-0 text-muted" /> {c.label}</span>
                <Pill tone={STATE[c.state].tone}>{STATE[c.state].label}</Pill>
                <span className="col-span-2 pl-[26px] text-[11px] text-muted">{c.detail}</span>
              </li>
            );
          })}
        </ul>
      ) : <p className="text-sm text-muted">No platform control reports on this area yet.</p>}
    </Card>
  );
}

export function Reliability({ data }: { data: PlatformCommand }) {
  const h = data.health;
  const availability = data.summary.availabilityPct;
  const notOk = h.services.filter((svc) => svc.state !== "operational");
  return (
    <Card title="Reliability & Service Impact" meta={h.sampled ? `${h.measured} services measured · objective ${h.objectivePct}%` : "No health samples in the last 15 minutes"}>
      {h.sampled && notOk.length > 0 && (
        <div className="mb-3 flex items-start gap-3 rounded-lg border border-accent/50 bg-[#FDF1E3] p-3">
          <Activity size={18} className="mt-0.5 shrink-0 text-[#D9761A]" />
          <div><p className="text-sm font-bold text-[#B45309]">{humanize(notOk[0].state)} · {notOk[0].name}</p>
            <p className="text-xs text-[#B45309]/90">{notOk.length} service{notOk.length === 1 ? "" : "s"} not operational{h.coreDown.length ? ` · core down: ${h.coreDown.join(", ")}` : ""}</p></div>
        </div>
      )}
      <div className="grid grid-cols-3 gap-2">
        <StatBox value={availability === null ? "—" : `${availability}%`} label="API availability · 30d" />
        <StatBox value={h.p95LatencyMs === null ? "—" : `${h.p95LatencyMs} ms`} label="p95 response · 24h" />
        <StatBox value={h.sampled ? `${h.degraded} / ${h.measured}` : "—"} label="Services not operational" />
      </div>
      {h.sampled ? (
        <ul className="mt-2">
          {h.services.map((svc) => {
            const tone: Tone = svc.state === "operational" ? "ok" : svc.state === "down" ? "bad" : "warn";
            return (
              <li key={svc.key} className="flex items-center justify-between gap-2 border-b border-line py-2 text-sm last:border-0">
                <span className="flex items-center gap-2 font-semibold text-ink">
                  <span aria-hidden className={`h-2 w-2 rounded-full ${DOT[tone]}`} />{svc.name}
                  {svc.core && <span className="text-[10px] font-bold uppercase text-muted">core</span>}
                </span>
                <span className="text-xs text-muted">{humanize(svc.state)}{svc.latencyMs !== null ? ` · ${svc.latencyMs} ms` : ""}</span>
              </li>
            );
          })}
        </ul>
      ) : <EmptyState icon={Activity} title="Unknown: no health samples in the last 15 minutes" />}
    </Card>
  );
}

export function KritonControlPlane({ data }: { data: PlatformCommand }) {
  const e = data.evaluation;
  const now = new Date(data.generatedAt).getTime();
  const held = data.releases.held > 0;
  return (
    <Card title="Kriton AI Control Plane" meta={`${data.releases.open} open release candidate${data.releases.open === 1 ? "" : "s"} · ${data.releases.held} held`}
      aside={held ? <Pill tone="bad">Release HOLD</Pill> : <Pill tone={STATE[e.state].tone}>{STATE[e.state].label}</Pill>}>
      {e.metrics.length > 0 ? (
        <ul className="space-y-2.5">
          {e.metrics.map((m) => {
            const pct = Math.max(0, Math.min(100, m.value <= 1 ? m.value * 100 : m.value));
            const tone: Tone = pct >= 90 ? "ok" : pct >= 70 ? "warn" : "bad";
            return (
              <li key={m.name} className="grid grid-cols-[minmax(0,8.5rem)_minmax(0,1fr)_3.5rem] items-center gap-3 text-xs">
                <span className="truncate font-semibold text-ink">{humanize(m.name)}</span>
                <span className="h-2 overflow-hidden rounded-full bg-soft" role="img" aria-label={`${humanize(m.name)}: ${m.value}`}>
                  <span className={`block h-full rounded-full ${BAR[tone]}`} style={{ width: `${pct}%` }} />
                </span>
                <span className="text-right text-muted">{m.value <= 1 ? `${Math.round(pct)}%` : m.value}</span>
              </li>
            );
          })}
        </ul>
      ) : <p className="text-sm text-muted">No evaluation metrics recorded yet.</p>}
      <div className="mt-4 space-y-2">
        <div className="rounded-lg border border-line p-3">
          <p className="text-sm font-bold text-ink">Latest evaluation</p>
          <p className="mt-0.5 text-xs text-muted">
            {e.latest ? `${humanize(e.latest.status.toLowerCase())} · ${timeAgo(e.latest.at, now)}` : "No run recorded"}
            {" · "}last 10 runs: {e.recent.completed} completed, {e.recent.failed} failed
          </p>
        </div>
        {data.releases.items.map((r) => (
          <div key={`${r.tenant}-${r.ref}`} className="flex items-center justify-between gap-2 rounded-lg border border-line p-3">
            <span className="min-w-0"><span className="block text-sm font-bold text-ink">{r.name} {r.version} · Candidate</span>
              <span className="block text-xs text-muted">{r.ref} · {r.tenant}</span></span>
            <Pill tone={r.held ? "bad" : "info"}>{r.held ? "Hold" : "In progress"}</Pill>
          </div>
        ))}
      </div>
    </Card>
  );
}

/** Companies and sign-ins at a glance, from the platform directory, with the
 * way into the full Companies and Accounts pages. */
export function TenantGovernance({ data }: { data: PlatformCommand }) {
  const { data: directory } = usePlatformDirectory();
  const d = directory?.summary;
  const rows: [string, ReactNode, string, Tone][] = [
    ["Companies", d ? d.companies : data.tenants.total, d ? `${d.personalWorkspaces} personal workspaces` : "", "ok"],
    ["Active in 30 days", d ? d.companiesActive30d : data.tenants.active30d, "companies", "ok"],
    ["Signed in · 24 h", d ? d.companiesSignedIn24h : "—", d ? `${d.signedIn24h} accounts` : "", "info"],
    ["Online now", d ? d.online : "—", d ? `${d.companiesOnline} companies` : "", "info"],
    ["Accounts", d ? d.accounts : data.tenants.users, "", "ok"],
    ["Approved billing plan", data.tenants.withApprovedPlan, "companies", data.tenants.withApprovedPlan < data.tenants.total ? "warn" : "ok"],
  ];
  return (
    <Card title="Tenant Governance" meta={`${data.tenants.total} tenants · ${data.tenants.users} accounts`}
      aside={<Link href="/super-admin/companies" className="inline-flex items-center gap-1 text-xs font-bold text-[#1F5FAE] hover:underline">
        Tenant register <ArrowRight size={12} /></Link>}>
      <ul>
        {rows.map(([label, value, note, tone]) => (
          <li key={label} className="flex items-center justify-between gap-3 border-b border-line py-2.5 text-sm last:border-0">
            <span className="flex items-center gap-2.5 font-semibold text-ink"><span aria-hidden className={`h-2 w-2 rounded-full ${DOT[tone]}`} />{label}</span>
            <span className="flex items-baseline gap-2"><span className="font-extrabold text-ink">{value}</span>
              {note && <span className="text-[11px] text-muted">{note}</span>}</span>
          </li>
        ))}
      </ul>
      <div className="mt-3 flex gap-3 text-sm">
        <Link href="/super-admin/companies" className="font-semibold text-[#1F5FAE] hover:underline">Companies</Link>
        <Link href="/super-admin/accounts" className="font-semibold text-[#1F5FAE] hover:underline">Accounts</Link>
      </div>
    </Card>
  );
}

export function CommercialAssurance({ data }: { data: PlatformCommand }) {
  const c = data.commercial;
  return (
    <Card title="Commercial Assurance" meta={`Statement totals · ${c.month}`}>
      <div className="grid grid-cols-3 gap-2">
        <StatBox value={money(c.invoiced)} label="Invoiced MTD" />
        <StatBox value={money(c.collected)} label="Collected MTD" />
        <StatBox value={money(c.receivable)} label="Open receivables" />
      </div>
      <ul className="mt-2">
        <ControlRow data={data} controlKey="billing" />
        <Row title="Usage metering disputes" right={<Pill tone={c.openDisputes ? "warn" : "ok"}>{c.openDisputes} open</Pill>} />
        <Row title="Unpaid statements" right={<Pill tone={c.unpaidStatements ? "warn" : "ok"}>{c.unpaidStatements}</Pill>} />
        <Row title="Credits pending approval" right={<Pill tone={c.pendingCredits ? "warn" : "ok"}>{c.pendingCredits}</Pill>} />
      </ul>
    </Card>
  );
}

/** A platform control as a row: its label, its own evidence detail and its
 * state, all from the backend; nothing when the control is not reported. */
function ControlRow({ data, controlKey }: { data: PlatformCommand; controlKey: string }) {
  const control = data.controls.find((c) => c.key === controlKey);
  if (!control) return null;
  return <Row title={control.label} detail={control.detail}
    right={<Pill tone={STATE[control.state].tone}>{STATE[control.state].label}</Pill>} />;
}

export function PrivilegedAccess({ data }: { data: PlatformCommand }) {
  const p = data.privileged;
  const now = new Date(data.generatedAt).getTime();
  return (
    <Card title="Privileged Access Oversight" meta={`Emergency access · measured ${utcDate(data.generatedAt)}`}>
      <ul>
        <ControlRow data={data} controlKey="privileged" />
        <Row title="Awaiting approval" right={<Pill tone={p.awaitingApproval ? "bad" : "ok"}>{p.awaitingApproval || "None"}</Pill>} />
        <Row title="Active emergency grants" right={<Pill tone={p.active ? "warn" : "ok"}>{p.active || "None"}</Pill>} />
        <Row title="Awaiting post-access review" right={<Pill tone={p.awaitingReview ? "warn" : "ok"}>{p.awaitingReview || "None"}</Pill>} />
        {p.activeGrants.map((g) => (
          <Row key={g.ref} title={g.ref} detail={g.tenant}
            right={<Pill tone="warn">Expires {timeAgo(g.expiresAt, now).replace(" ago", "")}</Pill>} />
        ))}
      </ul>
    </Card>
  );
}

export function EvidenceAudit({ data }: { data: PlatformCommand }) {
  const a = data.audit;
  return (
    <Card title="Evidence & Audit" meta={`Audit ledger · measured ${utcDate(data.generatedAt)}`}>
      <ul>
        <Row title="Audit events · 24 h" right={<Pill tone="info">{a.events24h}</Pill>} />
        <Row title="Evidence exports pending"
          right={<Pill tone={a.exportsPending ? "warn" : "ok"}>{a.exportsPending || "None"}</Pill>} />
        <Row title="Refused access attempts · 30 days"
          right={<Pill tone={a.deniedAttempts30d ? "warn" : "ok"}>{a.deniedAttempts30d}</Pill>} />
      </ul>
    </Card>
  );
}
