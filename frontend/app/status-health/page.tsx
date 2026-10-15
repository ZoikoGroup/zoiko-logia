"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  Activity, AlertTriangle, CheckCircle2, Clock3, Gauge, HeartPulse, PauseCircle, Search, ServerCrash, Siren,
} from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { useLiveData } from "@/components/overview/useLiveData";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import { AvailabilityChart, LatencyChart } from "@/components/operations/charts";
import {
  Badge, Button, DetailRows, EmptyState, ErrorNote, KpiRow, KpiTile, OpsHero, Panel, PillTabs, inputClass,
  timeAgo, useMutation, utcDate, utcTime,
} from "@/components/operations/ui";
import {
  getAssignees, getOperationsStatus, raiseAlert, setServiceOwner,
  type Assignee, type DependencyNode, type HealthState, type MonitoredService, type StatusOverview,
} from "@/lib/api";

type TabKey = "overview" | "services" | "dependencies" | "slo" | "jobs" | "events";
const TABS: { key: TabKey; label: string }[] = [
  { key: "overview", label: "Overview" }, { key: "services", label: "Services" },
  { key: "dependencies", label: "Dependencies" }, { key: "slo", label: "SLO & Error Budget" },
  { key: "jobs", label: "Background Jobs" }, { key: "events", label: "Events" },
];

const STATE: Record<HealthState | "impacted", { label: string; tone: "ok" | "warn" | "bad" | "neutral"; node: string }> = {
  operational: { label: "Healthy", tone: "ok", node: "border-ok/30 bg-ok/10 text-ok" },
  degraded: { label: "Degraded", tone: "warn", node: "border-accent/40 bg-accent/10 text-accent-ink" },
  impacted: { label: "Impacted", tone: "warn", node: "border-accent/40 bg-accent/10 text-accent-ink" },
  down: { label: "Unavailable", tone: "bad", node: "border-bad/40 bg-bad/10 text-bad" },
  not_configured: { label: "Not configured", tone: "neutral", node: "border-line bg-soft text-muted" },
};
const PLATFORM = {
  operational: { label: "Operational", tone: "ok" as const },
  degraded: { label: "Degraded", tone: "warn" as const },
  down: { label: "Outage", tone: "bad" as const },
};
const PAGE_SIZE = 10;
const fmtMs = (v: number | null) => (v === null ? "—" : `${v.toLocaleString()} ms`);
const fmtPct = (v: number | null) => (v === null ? "—" : `${v.toFixed(2)}%`);

export default function StatusHealthPage() {
  const { profile } = useAuth();
  const isAdmin = profile?.role === "Admin";
  const canRaise = Boolean(profile?.role) && profile?.role !== "System Auditor";
  const { data, error, loading, signedOut, reload } = useLiveData(
    "status-health", (token, signal) => getOperationsStatus(token, signal), 45_000,
  );
  const people = useLiveData("ops-assignees", (token, signal) => getAssignees(token, signal), 20_000);
  const [tab, setTab] = useState<TabKey>("overview");
  const [selectedKey, setSelectedKey] = useState<string>("");
  const [raising, setRaising] = useState(false);

  const services = data?.services ?? [];
  const selected = services.find((s) => s.key === selectedKey)
    ?? services.find((s) => s.state === "down") ?? services.find((s) => s.state === "degraded") ?? services[0];

  return (
    <main className="flex-1 space-y-4 overflow-y-auto p-4">
      <OpsHero icon={Activity} title="Status & Health"
        subtitle="Service observability, dependency impact, and governed recovery across ZoikoLogia and Kriton.">
        <p className="text-xs font-bold uppercase tracking-wider text-white">Reliability operations</p>
        <p className="text-white/75">Availability · Latency · Dependencies · Recovery</p>
      </OpsHero>

      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />
      {data && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
            <span className="flex items-center gap-2">
              <Badge tone="ok">● LIVE · MEASURED TELEMETRY</Badge>
              Checked {utcDate(data.checkedAt)} · samples every {Math.round(data.jobs.sampler.intervalSeconds / 60)} min
            </span>
            <span>Live checks and stored samples only · All times UTC</span>
          </div>
          <Kpis data={data} />
          <ImpactBanner data={data} onView={() => setTab("dependencies")} />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <PillTabs label="Status sections" tabs={TABS} active={tab} onChange={setTab} />
            <div className="flex gap-2">
              <Link href="/alerts-center" className="inline-flex min-h-10 items-center rounded-lg border border-line bg-panel px-3 text-sm font-semibold text-info hover:bg-soft">View alerts</Link>
              {canRaise && <Button variant="primary" onClick={() => setRaising(true)}>+ Raise alert</Button>}
            </div>
          </div>
          {raising && <RaiseAlertForm services={services} initialKey={selected?.key ?? ""}
            onDone={() => { setRaising(false); reload(); }} />}

          {tab === "overview" && (
            <>
              <div className="grid gap-4 xl:grid-cols-3">
                <AvailabilityPanel data={data} />
                <LatencyPanel data={data} />
                <Panel title="Dependency Health" meta="Live dependency graph">
                  <DependencyTree node={data.dependencyMap} compact />
                </Panel>
              </div>
              <RegisterWithDetail services={services} selected={selected} onSelect={setSelectedKey}
                data={data} isAdmin={isAdmin} people={people.data ?? []} onChanged={reload} />
              <div className="grid gap-4 xl:grid-cols-3">
                <EventsPanel events={data.events.slice(0, 6)} />
                <RecoveryGates service={selected} />
                <GovernancePanel />
              </div>
            </>
          )}
          {tab === "services" && (
            <RegisterWithDetail services={services} selected={selected} onSelect={setSelectedKey}
              data={data} isAdmin={isAdmin} people={people.data ?? []} onChanged={reload} />
          )}
          {tab === "dependencies" && (
            <Panel title="Dependency map" meta="What each part of the platform relies on, coloured by its live state">
              <DependencyTree node={data.dependencyMap} />
              <p className="mt-4 text-xs text-muted">A dependency that is unavailable marks everything above it as impacted. The map follows how the backend calls each service.</p>
            </Panel>
          )}
          {tab === "slo" && <SloPanel data={data} />}
          {tab === "jobs" && <JobsPanel data={data} />}
          {tab === "events" && <EventsPanel events={data.events} full />}
        </>
      )}
    </main>
  );
}

function Kpis({ data }: { data: StatusOverview }) {
  const s = data.summary;
  const platform = PLATFORM[s.platformState];
  return (
    <KpiRow>
      <KpiTile icon={HeartPulse} tone={platform.tone === "ok" ? "ok" : platform.tone === "warn" ? "warn" : "bad"}
        value={platform.label} label="Platform state"
        hint={s.impacted.length ? `${s.impacted.length} impacted service${s.impacted.length === 1 ? "" : "s"}` : "All monitored services healthy"} />
      <KpiTile icon={CheckCircle2} value={fmtPct(s.availability24h)} label="Availability"
        hint={s.availability24h === null ? "No samples in the last 24h yet" : `Share of checks passing · last 24h`} />
      <KpiTile icon={Clock3} tone={s.apiP95Ms !== null && s.apiP95Ms > s.apiP95ObjectiveMs ? "warn" : "neutral"}
        value={fmtMs(s.apiP95Ms)} label="API p95 latency"
        hint={s.apiP95Ms === null ? "No API samples yet" : `${s.apiP95Ms > s.apiP95ObjectiveMs ? "Above" : "Within"} ${s.apiP95ObjectiveMs.toLocaleString()} ms objective`} />
      <KpiTile icon={AlertTriangle} tone={s.activeAlerts ? "bad" : "ok"} value={s.activeAlerts} label="Active alerts"
        hint="Open in Alerts Center" />
      <KpiTile icon={ServerCrash} tone={s.unavailable ? "bad" : "ok"} value={s.unavailable}
        label={s.unavailable === 1 ? "Unavailable service" : "Unavailable services"}
        hint={s.unavailable ? s.impacted.slice(0, 2).join(" · ") : "None right now"} />
      <KpiTile icon={PauseCircle} tone={s.blockedJobs ? "warn" : "ok"} value={s.blockedJobs} label="Blocked jobs"
        hint={`Uploads stuck or failed · last 24h`} />
    </KpiRow>
  );
}

function impactedParents(node: DependencyNode, down: Set<string>, path: string[] = []): string[] {
  const hits = node.children.flatMap((c) => impactedParents(c, down, [...path, node.name]));
  return down.has(node.key) ? [...hits, ...path] : hits;
}

function ImpactBanner({ data, onView }: { data: StatusOverview; onView: () => void }) {
  const down = data.services.filter((s) => s.state === "down" || s.state === "degraded");
  if (!down.length) return null;
  const affected = [...new Set(impactedParents(data.dependencyMap, new Set(down.map((s) => s.key))))];
  const outage = down.some((s) => s.state === "down");
  return (
    <section className="flex flex-col gap-3 rounded-xl border border-accent/40 border-l-4 border-l-accent bg-accent/5 p-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-start gap-3">
        <Badge tone="warn">{outage ? "SERVICE UNAVAILABLE" : "DEGRADED SERVICE"}</Badge>
        <div>
          <p className="font-bold text-ink">{down.map((s) => s.name).join(", ")} {down.length === 1 ? "is" : "are"} {outage ? "unavailable" : "degraded"}</p>
          <p className="text-sm text-muted">
            {down.map((s) => `${s.name}: ${s.detail}`).join(" · ")}
            {affected.length > 0 && <> · Impacts {affected.join(", ")}.</>}
          </p>
        </div>
      </div>
      <Button onClick={onView}>View impact assessment ↗</Button>
    </section>
  );
}

function AvailabilityPanel({ data }: { data: StatusOverview }) {
  const has = data.hourly.some((h) => h.availability !== null);
  const s = data.summary;
  return (
    <Panel title="Availability & Error Budget" meta="Last 24 hours">
      {has ? <AvailabilityChart hours={data.hourly} objective={s.availabilityObjective} />
        : <EmptyState icon={Gauge} title="No history yet">Samples are taken every {Math.round(data.jobs.sampler.intervalSeconds / 60)} minutes; the chart fills in as they arrive.</EmptyState>}
      <div className="mt-2 flex justify-between text-xs">
        <span className="text-muted">Share of health checks passing · {fmtPct(s.availability24h)}</span>
        {s.availability24h !== null && (
          <span className={`font-bold ${s.availability24h < s.availabilityObjective ? "text-accent-ink" : "text-ok"}`}>
            {s.availability24h < s.availabilityObjective ? "Below" : "Meets"} {s.availabilityObjective}% objective
          </span>
        )}
      </div>
    </Panel>
  );
}

function LatencyPanel({ data }: { data: StatusOverview }) {
  const has = data.hourly.some((h) => h.p95 !== null);
  return (
    <Panel title="API Response Latency" meta="Measured from real requests">
      {has ? <LatencyChart hours={data.hourly} />
        : <EmptyState icon={Clock3} title="No request timings yet">Every API request is timed; hourly p50 and p95 appear after the first sample.</EmptyState>}
      <div className="mt-2 flex justify-between text-xs">
        <span className="text-muted">Last 24 hours · milliseconds</span>
        {data.summary.apiP95Ms !== null && <span className="font-bold text-accent-ink">p95 {fmtMs(data.summary.apiP95Ms)}</span>}
      </div>
    </Panel>
  );
}

function DependencyTree({ node, compact = false }: { node: DependencyNode; compact?: boolean }) {
  const s = STATE[node.state];
  const children = compact ? node.children.filter((c) => c.state !== "not_configured") : node.children;
  return (
    <div className="flex flex-col items-center">
      <span className={`rounded-lg border px-3 py-1.5 text-center text-xs font-bold ${s.node}`} title={s.label}>
        {node.name}<span className="sr-only"> ({s.label})</span>
      </span>
      {children.length > 0 && (
        <>
          <span aria-hidden className="h-3 w-px bg-line" />
          <div className={`flex flex-wrap justify-center gap-2 border-t border-line pt-3 ${compact ? "" : "gap-4"}`}>
            {children.map((c) => <DependencyTree key={c.key} node={c} compact={compact} />)}
          </div>
        </>
      )}
    </div>
  );
}

function RegisterWithDetail({ services, selected, onSelect, data, isAdmin, people, onChanged }: {
  services: MonitoredService[]; selected?: MonitoredService; onSelect: (key: string) => void; data: StatusOverview;
  isAdmin: boolean; people: Assignee[]; onChanged: () => void;
}) {
  const [query, setQuery] = useState("");
  const [state, setState] = useState("");
  const [category, setCategory] = useState("");
  const [page, setPage] = useState(0);
  const categories = [...new Set(services.map((s) => s.category))];
  const rows = useMemo(() => services.filter((s) =>
    (!state || s.state === state) && (!category || s.category === category)
    && (!query || `${s.name} ${s.key} ${s.component} ${s.owner ?? ""}`.toLowerCase().includes(query.toLowerCase()))),
  [services, state, category, query]);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const shown = rows.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
      <Panel title="Service Health Register" meta={`${services.length} monitored services · select one to inspect`}>
        <div className="mb-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_auto]">
          <label className="relative">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input className={`${inputClass} pl-9`} placeholder="Search by service, owner or component…" value={query}
              onChange={(e) => { setQuery(e.target.value); setPage(0); }} />
          </label>
          <Button onClick={() => { setQuery(""); setState(""); setCategory(""); setPage(0); }}>Clear filters</Button>
        </div>
        <div className="mb-3 grid gap-2 sm:grid-cols-2">
          <select aria-label="Status" className={inputClass} value={state} onChange={(e) => { setState(e.target.value); setPage(0); }}>
            <option value="">All statuses</option>
            {(["operational", "degraded", "down", "not_configured"] as HealthState[]).map((k) => <option key={k} value={k}>{STATE[k].label}</option>)}
          </select>
          <select aria-label="Category" className={inputClass} value={category} onChange={(e) => { setCategory(e.target.value); setPage(0); }}>
            <option value="">All categories</option>
            {categories.map((c) => <option key={c}>{c}</option>)}
          </select>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="bg-soft text-xs text-muted">
              <tr>{["Service", "Component", "Location", "Status", "Availability", "p95 latency", "Open alerts", "Owner"].map((h) =>
                <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr>
            </thead>
            <tbody>
              {shown.map((s) => (
                <tr key={s.key} onClick={() => onSelect(s.key)} aria-selected={selected?.key === s.key}
                  className={`cursor-pointer border-b border-line hover:bg-soft ${selected?.key === s.key ? "bg-info/5" : ""}`}>
                  <td className="px-3 py-2"><span className="block font-semibold text-ink">{s.name}</span><span className="text-[11px] text-muted">{s.key}</span></td>
                  <td className="px-3 py-2 text-ink">{s.component}</td>
                  <td className="px-3 py-2 text-ink">{s.location}</td>
                  <td className="px-3 py-2"><Badge tone={STATE[s.state].tone}>{STATE[s.state].label}</Badge></td>
                  <td className="px-3 py-2 text-ink">{fmtPct(s.availability24h)}</td>
                  <td className="px-3 py-2 text-ink">{fmtMs(s.p95LatencyMs24h ?? s.latencyMs)}</td>
                  <td className={`px-3 py-2 font-semibold ${s.openAlerts.length ? "text-accent-ink" : "text-muted"}`}>{s.openAlerts.length || "—"}</td>
                  <td className="px-3 py-2 text-ink">{s.owner ?? <span className="text-muted">Unassigned</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!shown.length && <EmptyState title="No services match these filters" />}
        </div>
        <div className="mt-3 flex items-center justify-between text-xs text-muted">
          <span>Showing {rows.length ? page * PAGE_SIZE + 1 : 0}–{Math.min(rows.length, (page + 1) * PAGE_SIZE)} of {rows.length} services</span>
          <span className="flex gap-1">
            <button aria-label="Previous page" disabled={page === 0} onClick={() => setPage(page - 1)} className="h-7 w-7 rounded border border-line disabled:opacity-40">‹</button>
            <span className="grid h-7 min-w-7 place-items-center rounded bg-hero px-2 font-bold text-white">{page + 1}</span>
            <button aria-label="Next page" disabled={page >= pages - 1} onClick={() => setPage(page + 1)} className="h-7 w-7 rounded border border-line disabled:opacity-40">›</button>
          </span>
          <span>Live check + 24h of samples</span>
        </div>
      </Panel>
      {selected ? <ServiceDetail service={selected} data={data} isAdmin={isAdmin} people={people} onChanged={onChanged} />
        : <Panel title="Service"><EmptyState title="No services monitored yet" /></Panel>}
    </div>
  );
}

type DetailTab = "health" | "dependencies" | "events" | "slo";

function ServiceDetail({ service: s, data, isAdmin, people, onChanged }: {
  service: MonitoredService; data: StatusOverview; isAdmin: boolean; people: Assignee[]; onChanged: () => void;
}) {
  const [tab, setTab] = useState<DetailTab>("health");
  const { busy, error, run } = useMutation();
  const events = data.events.filter((e) => e.serviceKey === s.key);
  const slo = data.slo.find((r) => r.key === s.key);
  const interpretation = s.state === "down"
    ? "Unavailable now. Features that depend on it are impacted until the next sample records recovery."
    : s.state === "degraded" ? "Responding, but outside its objective (errors or latency). Investigate before it degrades further."
    : s.availability24h !== null && s.availability24h < data.summary.availabilityObjective
      ? "Healthy now, but it was unavailable earlier today; check the events for the outage window."
      : "Healthy now and within its objective over the last 24 hours.";

  return (
    <Panel title={s.name} meta={s.key} action={<Badge tone={STATE[s.state].tone}>{STATE[s.state].label}</Badge>}>
      <PillTabs label="Service detail" active={tab} onChange={setTab}
        tabs={[{ key: "health", label: "Health" }, { key: "dependencies", label: "Dependencies" },
          { key: "events", label: "Events", count: events.length }, { key: "slo", label: "SLO & Recovery" }]} />
      <div className="mt-4 space-y-4">
        {tab === "health" && (
          <>
            <DetailRows rows={[
              ["Component", s.component], ["Category", s.category], ["Location", s.location],
              ["Availability (24h)", fmtPct(s.availability24h)], ["p95 latency (24h)", fmtMs(s.p95LatencyMs24h)],
              ["Latency now", fmtMs(s.latencyMs)],
              ...(s.errorRate24h !== null ? [["Error rate (24h)", `${s.errorRate24h}%`] as [string, string]] : []),
              ["Open alerts", s.openAlerts.length ? s.openAlerts.map((a) => a.ref).join(", ") : "None"],
              ["Responsible owner", s.owner ?? "Unassigned"], ["Last check", s.detail],
              ["Last sample", s.lastSampleAt ? `${utcDate(s.lastSampleAt)} (${timeAgo(s.lastSampleAt)})` : "Live check only"],
            ]} />
            {isAdmin && (
              <label className="block text-sm">
                <span className="mb-1 block text-muted">Assign owner</span>
                <select className={inputClass} value={s.ownerId ?? ""} disabled={busy === "owner"}
                  onChange={(e) => e.target.value && run("owner", (t) => setServiceOwner(t, s.key, e.target.value)).then((ok) => ok && onChanged())}>
                  <option value="">Choose a person…</option>
                  {people.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.role}</option>)}
                </select>
              </label>
            )}
            <ErrorNote message={error} />
            <p className="rounded-lg border border-line bg-soft p-3 text-sm text-ink"><b>Health interpretation:</b> {interpretation}</p>
            <div className="grid grid-cols-2 gap-2">
              <Link href="/alerts-center" className="inline-flex min-h-10 items-center justify-center rounded-lg border border-line bg-panel text-sm font-semibold text-info hover:bg-soft">View alerts</Link>
              <Link href="/audit-logs" className="inline-flex min-h-10 items-center justify-center rounded-lg border border-line bg-panel text-sm font-semibold text-info hover:bg-soft">Audit events</Link>
            </div>
          </>
        )}
        {tab === "dependencies" && (
          s.dependsOn.length
            ? <ul className="space-y-2 text-sm">{s.dependsOn.map((k) => {
              const dep = data.services.find((d) => d.key === k);
              return <li key={k} className="flex justify-between"><span className="text-ink">{dep?.name ?? (k === "ai_models" ? "AI model providers" : k)}</span>
                {dep ? <Badge tone={STATE[dep.state].tone}>{STATE[dep.state].label}</Badge> : <span className="text-muted">See map</span>}</li>;
            })}</ul>
            : <p className="text-sm text-muted">{s.name} has no monitored dependencies of its own. It is used by the Kriton API.</p>
        )}
        {tab === "events" && (events.length
          ? <EventList events={events} />
          : <p className="text-sm text-muted">No state changes in the last 24 hours.</p>)}
        {tab === "slo" && (
          <>
            <DetailRows rows={[
              ["Objective", `${data.summary.availabilityObjective}% availability`],
              ["30-day availability", slo ? `${slo.availability}% (${slo.samples} samples)` : "No samples yet"],
              ["Error budget left", slo?.budgetRemainingPct != null ? `${slo.budgetRemainingPct}%` : "—"],
            ]} />
            <p className="rounded-lg border border-line bg-soft p-3 text-sm text-ink">
              <b>Recovery:</b> this console does not restart services. Restore the dependency; the next sample records the recovery and its alert resolves automatically.
            </p>
          </>
        )}
      </div>
    </Panel>
  );
}

function EventList({ events }: { events: StatusOverview["events"] }) {
  return (
    <ul className="space-y-2 text-sm">
      {events.map((e) => {
        const to = STATE[e.to as HealthState] ?? STATE.not_configured;
        return (
          <li key={`${e.serviceKey}-${e.at}`} className="flex items-start justify-between gap-3">
            <span className="flex items-start gap-2">
              <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${to.tone === "ok" ? "bg-ok" : to.tone === "bad" ? "bg-bad" : "bg-accent"}`} />
              <span><b className="text-ink">{utcTime(e.at)}</b> <span className="text-ink">{e.service} {to.tone === "ok" ? "recovered" : `became ${to.label.toLowerCase()}`}</span>
                {e.detail && <span className="block text-xs text-muted">{e.detail}</span>}</span>
            </span>
            <span className="shrink-0 text-xs uppercase text-muted">{to.label}</span>
          </li>
        );
      })}
    </ul>
  );
}

function EventsPanel({ events, full = false }: { events: StatusOverview["events"]; full?: boolean }) {
  return (
    <Panel title="Recent Operations Events" meta={full ? "State changes · last 24 hours" : "Measured state changes"}>
      {events.length ? <EventList events={events} /> : <p className="text-sm text-muted">No service changed state in the last 24 hours.</p>}
    </Panel>
  );
}

function RecoveryGates({ service }: { service?: MonitoredService }) {
  if (!service) return <Panel title="Recovery & Change Gates"><p className="text-sm text-muted">Select a service.</p></Panel>;
  const acknowledged = service.openAlerts.length > 0 && service.openAlerts.every((a) => a.state !== "unacknowledged");
  const gates: [string, "pass" | "fail" | "wait", string][] = [
    ["Owner assigned", service.owner ? "pass" : "wait", service.owner ? "Pass" : "Wait"],
    ["Health check passing", service.state === "down" ? "fail" : "pass", service.state === "down" ? "Fail" : "Pass"],
    ["Alerts acknowledged", !service.openAlerts.length ? "pass" : acknowledged ? "pass" : "wait",
      !service.openAlerts.length ? "None open" : acknowledged ? "Pass" : "Wait"],
    ["Within 24h objective", service.availability24h === null ? "wait" : service.availability24h >= 99.5 ? "pass" : "fail",
      service.availability24h === null ? "No data" : service.availability24h >= 99.5 ? "Pass" : "Hold"],
  ];
  const bar = { pass: "bg-ok w-full", fail: "bg-bad w-1/3", wait: "bg-soft w-0" };
  return (
    <Panel title="Recovery & Change Gates" meta={service.name}>
      <ul className="space-y-3 text-sm">
        {gates.map(([label, state, text]) => (
          <li key={label} className="grid grid-cols-[minmax(0,9rem)_1fr_auto] items-center gap-3">
            <span className="text-ink">{label}</span>
            <span className="h-2 overflow-hidden rounded-full bg-soft"><span className={`block h-full rounded-full ${bar[state]}`} /></span>
            <span className={`text-xs font-bold ${state === "pass" ? "text-ok" : state === "fail" ? "text-bad" : "text-muted"}`}>{text}</span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function GovernancePanel() {
  return (
    <Panel title="Operational Governance" meta="Release-state safeguards">
      <div className="space-y-2 text-sm text-ink">
        <p><b>Fail closed:</b> tenant boundaries (row-level security) and source eligibility hold during a degraded service; nothing is bypassed to restore availability.</p>
        <p><b>Evidence:</b> every alert action and owner change is written to the hash-chained audit ledger.</p>
        <p><b>Status communications:</b> figures on this page are measured, never estimated; a service with no samples shows no number.</p>
      </div>
    </Panel>
  );
}

function SloPanel({ data }: { data: StatusOverview }) {
  return (
    <Panel title="SLO & Error Budget" meta={`Objective ${data.summary.availabilityObjective}% availability · rolling 30 days`}>
      {data.slo.length ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-left text-sm">
            <thead className="bg-soft text-xs text-muted"><tr>{["Service", "Samples", "Availability", "Error budget left", "Objective"].map((h) => <th key={h} className="px-3 py-2">{h}</th>)}</tr></thead>
            <tbody>{data.slo.map((r) => (
              <tr key={r.key} className="border-b border-line">
                <td className="px-3 py-2 font-semibold text-ink">{r.name}</td>
                <td className="px-3 py-2 text-ink">{r.samples.toLocaleString()}</td>
                <td className="px-3 py-2 text-ink">{r.availability}%</td>
                <td className="px-3 py-2 text-ink">{r.budgetRemainingPct === null ? "—" : `${r.budgetRemainingPct}%`}</td>
                <td className="px-3 py-2"><Badge tone={r.met ? "ok" : "bad"}>{r.met ? "Met" : "Missed"}</Badge></td>
              </tr>))}</tbody>
          </table>
        </div>
      ) : <EmptyState icon={Gauge} title="No samples yet">The error budget is computed from stored samples once they exist.</EmptyState>}
    </Panel>
  );
}

function JobsPanel({ data }: { data: StatusOverview }) {
  const { sampler, documents, queue } = data.jobs;
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Panel title="Health sampler" meta="Feeds this page">
        <DetailRows rows={[
          ["State", sampler.enabled ? "Running" : "Switched off (HEALTH_SAMPLER_ENABLED)"],
          ["Interval", `Every ${Math.round(sampler.intervalSeconds / 60)} min`],
          ["Retention", `${sampler.retentionDays} days`],
          ["Last sample", sampler.lastSampleAt ? `${utcDate(sampler.lastSampleAt)} (${timeAgo(sampler.lastSampleAt)})` : "None yet"],
        ]} />
      </Panel>
      <Panel title="Document processing" meta="This workspace">
        {documents.available ? (
          <DetailRows rows={[
            ["Processing now", documents.processing], ["Stuck (over 15 min)", documents.stuck], ["Failed (24h)", documents.failed24h],
          ]} />
        ) : <p className="text-sm text-muted">Document counts are not available on this database.</p>}
      </Panel>
      <Panel title="Job queue" meta="Redis / Celery">
        <div className="flex items-center justify-between text-sm">
          <span className="text-ink">{queue.detail}</span><Badge tone={STATE[queue.state].tone}>{STATE[queue.state].label}</Badge>
        </div>
        {queue.state === "not_configured" && <p className="mt-2 text-xs text-muted">Background work runs inside the API process; no separate queue is configured.</p>}
      </Panel>
    </div>
  );
}

function RaiseAlertForm({ services, initialKey, onDone }: { services: MonitoredService[]; initialKey: string; onDone: () => void }) {
  const [title, setTitle] = useState("");
  const [severity, setSeverity] = useState<"Critical" | "High" | "Medium" | "Low">("High");
  const [serviceKey, setServiceKey] = useState(initialKey);
  const [detail, setDetail] = useState("");
  const { busy, error, run } = useMutation();
  return (
    <Panel title="Raise an alert" meta="Recorded in Alerts Center and the audit ledger"
      action={<Button onClick={onDone}>Cancel</Button>}>
      <form className="grid gap-3 md:grid-cols-2" onSubmit={(e) => {
        e.preventDefault();
        run("raise", (t) => raiseAlert(t, { title, severity, category: "Platform operations", detail, service_key: serviceKey || null }))
          .then((ok) => ok && onDone());
      }}>
        <input required minLength={3} className={inputClass} placeholder="What is wrong?" value={title} onChange={(e) => setTitle(e.target.value)} />
        <div className="grid grid-cols-2 gap-2">
          <select aria-label="Severity" className={inputClass} value={severity} onChange={(e) => setSeverity(e.target.value as typeof severity)}>
            {["Critical", "High", "Medium", "Low"].map((s) => <option key={s}>{s}</option>)}
          </select>
          <select aria-label="Service" className={inputClass} value={serviceKey} onChange={(e) => setServiceKey(e.target.value)}>
            <option value="">No specific service</option>
            {services.map((s) => <option key={s.key} value={s.key}>{s.name}</option>)}
          </select>
        </div>
        <textarea className={`${inputClass} min-h-20 py-2 md:col-span-2`} placeholder="Detail (optional)" value={detail} onChange={(e) => setDetail(e.target.value)} />
        <div className="md:col-span-2"><ErrorNote message={error} /></div>
        <div className="md:col-span-2"><Button type="submit" variant="primary" busy={busy === "raise"}><Siren size={14} /> Raise alert</Button></div>
      </form>
    </Panel>
  );
}
