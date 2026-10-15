"use client";

import Link from "next/link";
import { useState } from "react";
import { Ban, Download, FileClock, Flag, Layers, ScrollText, Search, ShieldCheck, ShieldX } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { useLiveData } from "@/components/overview/useLiveData";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import {
  Badge, Breadcrumb, Button, DetailRows, EmptyState, ErrorNote, KpiTile, OpsHero, Panel, PillTabs, ProgressRow,
  humanize, inputClass, useMutation, utcDate,
} from "@/components/operations/ui";
import {
  actOnIncident, decideAuditExport, downloadAuditExport, getAuditEvents, getAuditOverview, openIncident, requestAuditExport,
  type AuditEventRow, type AuditExport, type AuditOverview,
} from "@/lib/api";

type FamilyTab = "" | "access" | "privileged" | "ai" | "source" | "user";
const RISK_TONE = { critical: "bad", high: "warn", medium: "info", low: "ok" } as const;
const OUTCOME_TONE = { denied: "bad", blocked: "bad", failed: "bad", pending: "warn", recorded: "ok" } as const;
const PAGE = 50;

export default function AuditLogsPage() {
  const { profile } = useAuth();
  const isAdmin = profile?.role === "Admin";
  const [family, setFamily] = useState<FamilyTab>("");
  const [risk, setRisk] = useState("");
  const [outcome, setOutcome] = useState("");
  const [days, setDays] = useState(30);
  const [draft, setDraft] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [selectedId, setSelectedId] = useState("");
  const [exporting, setExporting] = useState(false);
  const overview = useLiveData("audit-overview", (token, signal, fresh) => getAuditOverview(token, signal, fresh), 60_000);
  const filters = { family, risk, outcome, q, days, offset, limit: PAGE };
  const page = useLiveData(`audit-events:${JSON.stringify(filters)}`, (token, signal) => getAuditEvents(token, filters, signal), 45_000);
  const events = page.data?.events ?? [];
  const selected = events.find((e) => e.id === selectedId) ?? events[0];
  const reset = () => setOffset(0);

  return (
    <main className="flex-1 space-y-4 overflow-y-auto p-4">
      <Breadcrumb section="Review, Escalation & Audit" page="Audit Logs" />
      <OpsHero icon={ScrollText} title="Audit Logs"
        subtitle="Search and investigate authoritative activity records across users, AI, sources, and privileged access.">
        <p>Traceable events</p><p>Tenant-protected evidence</p><p>Integrity-first investigations</p><p>Controlled retention and exports</p>
      </OpsHero>
      <LiveSourceStatus loading={overview.loading} error={overview.error} signedOut={overview.signedOut} reload={overview.reload} />
      {overview.data && <Kpis data={overview.data} />}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <PillTabs label="Event families" active={family} onChange={(f) => { setFamily(f); reset(); }} tabs={[
          { key: "", label: "All Events" }, { key: "access", label: "Access Denials" }, { key: "privileged", label: "Privileged / Admin" },
          { key: "ai", label: "AI & Policy" }, { key: "source", label: "Source Changes" }, { key: "user", label: "User Activity" }]} />
      </div>
      {exporting && <ExportForm filters={{ family, risk, outcome, q, days }} onDone={() => { setExporting(false); overview.reload(); }} />}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_440px]">
        <Panel title="Event register" meta={page.data ? `${page.data.total.toLocaleString()} events · last ${days} days · newest first (UTC)` : "Loading…"}>
          <form className="mb-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_auto_auto]" onSubmit={(e) => { e.preventDefault(); setQ(draft); reset(); }}>
            <label className="relative"><Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
              <input className={`${inputClass} pl-9`} placeholder="Search event ID, actor, event, subject or correlation ID…" value={draft} onChange={(e) => setDraft(e.target.value)} /></label>
            <Button type="submit">Search</Button>
            <Button variant="primary" onClick={() => setExporting(true)}>Request Export ↗</Button>
          </form>
          <div className="mb-3 grid gap-2 sm:grid-cols-3">
            <select aria-label="Risk" className={inputClass} value={risk} onChange={(e) => { setRisk(e.target.value); reset(); }}><option value="">All risk levels</option>{["critical", "high", "medium", "low"].map((r) => <option key={r} value={r}>{humanize(r)}</option>)}</select>
            <select aria-label="Outcome" className={inputClass} value={outcome} onChange={(e) => { setOutcome(e.target.value); reset(); }}><option value="">All outcomes</option>{["denied", "blocked", "failed", "pending", "recorded"].map((o) => <option key={o} value={o}>{humanize(o)}</option>)}</select>
            <select aria-label="Window" className={inputClass} value={days} onChange={(e) => { setDays(Number(e.target.value)); reset(); }}>{[1, 7, 30, 90, 365].map((d) => <option key={d} value={d}>Last {d} day{d === 1 ? "" : "s"}</option>)}</select>
          </div>
          {page.error && <ErrorNote message={page.error} />}
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-left text-sm">
              <thead className="bg-soft text-xs text-muted"><tr>{["Timestamp (UTC)", "Event ID", "Actor", "Event", "Resource / scope", "Risk", "Outcome"].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr></thead>
              <tbody>{events.map((e) => (
                <tr key={e.id} onClick={() => setSelectedId(e.id)} aria-selected={selected?.id === e.id} className={`cursor-pointer border-b border-line hover:bg-soft ${selected?.id === e.id ? "bg-info/5" : ""}`}>
                  <td className="whitespace-nowrap px-3 py-2 text-ink">{e.at ? utcDate(e.at) : "—"}</td>
                  <td className="px-3 py-2 font-mono text-xs font-semibold text-info">{e.id.slice(0, 12)}</td>
                  <td className="max-w-[10rem] truncate px-3 py-2 text-ink">{e.actor}</td>
                  <td className="px-3 py-2 text-ink">{humanize(e.event.replace(/\./g, " "))}</td>
                  <td className="max-w-[12rem] truncate px-3 py-2 text-xs text-ink">{e.subjectType}: {e.subjectId}</td>
                  <td className="px-3 py-2"><Badge tone={RISK_TONE[e.risk]}>{humanize(e.risk)}</Badge></td>
                  <td className="px-3 py-2"><Badge tone={OUTCOME_TONE[e.outcome]}>{humanize(e.outcome)}</Badge></td>
                </tr>))}</tbody>
            </table>
            {page.data && !events.length && <EmptyState title="No audit events match this search" />}
          </div>
          {page.data && (
            <div className="mt-3 flex items-center justify-between text-xs text-muted">
              <span>Showing {page.data.total ? offset + 1 : 0}–{offset + events.length} of {page.data.total.toLocaleString()}</span>
              <span className="flex gap-1">
                <button aria-label="Previous page" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))} className="h-7 w-7 rounded border border-line disabled:opacity-40">‹</button>
                <span className="grid h-7 min-w-7 place-items-center rounded bg-hero px-2 font-bold text-white">{Math.floor(offset / PAGE) + 1}</span>
                <button aria-label="Next page" disabled={offset + PAGE >= page.data.total} onClick={() => setOffset(offset + PAGE)} className="h-7 w-7 rounded border border-line disabled:opacity-40">›</button>
              </span>
              <span>All timestamps UTC · tenant-scoped</span>
            </div>
          )}
        </Panel>
        {selected ? <Inspector key={selected.id} e={selected} overview={overview.data} onFilterCorrelation={(c) => { setDraft(c); setQ(c); reset(); }} />
          : <Panel title="Event inspector"><EmptyState icon={ScrollText} title="Select an event" /></Panel>}
      </div>
      {overview.data && <Bottom data={overview.data} isAdmin={isAdmin} selfId={profile?.id} onChanged={overview.reload} />}
    </main>
  );
}

function Kpis({ data }: { data: AuditOverview }) {
  const s = data.summary;
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <KpiTile icon={Layers} value={s.total.toLocaleString()} label="Events recorded" hint={`${s.last30d.toLocaleString()} in the last 30 days`} />
      <KpiTile icon={Ban} tone={s.denied30d ? "bad" : "ok"} value={s.denied30d} label="Denied sensitive actions" hint={`${s.deniedHighRisk30d} high-risk · last 30 days`} />
      <KpiTile icon={Flag} tone={s.openInvestigations ? "warn" : "ok"} value={s.openInvestigations} label="Open investigations" hint={`${s.investigationsWithEvidence} with linked audit evidence`} />
      <KpiTile icon={s.chainPassed ? ShieldCheck : ShieldX} tone={s.chainPassed ? "ok" : "bad"} value={s.chainPassed ? "Verified" : "Broken"} label="Hash-chain integrity"
        hint={s.chainPassed ? `${s.eventsChecked.toLocaleString()} events checked` : `Broken at ${s.brokenAt}`} hintTone={s.chainPassed ? undefined : "bad"} />
      <KpiTile icon={FileClock} tone={s.exportsPending ? "warn" : "ok"} value={s.exportsPending} label="Export requests pending" hint="Approved purpose & scope required" />
    </div>
  );
}

type InspectorTab = "overview" | "integrity" | "correlations" | "investigation";

function Inspector({ e, overview, onFilterCorrelation }: { e: AuditEventRow; overview: AuditOverview | null; onFilterCorrelation: (c: string) => void }) {
  const [tab, setTab] = useState<InspectorTab>("overview");
  const [showPayload, setShowPayload] = useState(false);
  const [incidentId, setIncidentId] = useState("");
  const [note, setNote] = useState("");
  const [done, setDone] = useState("");
  const { busy, error, run } = useMutation();
  return (
    <Panel title="Event inspector" action={<Badge tone={OUTCOME_TONE[e.outcome]}>{humanize(e.outcome)} · {humanize(e.risk)}</Badge>}>
      <p className="-mt-1 break-all font-mono text-sm font-bold text-info">{e.id}</p>
      <h3 className="mb-3 text-lg font-extrabold text-ink">{humanize(e.event.replace(/\./g, " "))}</h3>
      <PillTabs label="Event detail" active={tab} onChange={setTab} tabs={[
        { key: "overview", label: "Overview" }, { key: "integrity", label: "Integrity" },
        { key: "correlations", label: "Correlations" }, { key: "investigation", label: "Investigation" }]} />
      <div className="mt-4 space-y-4">
        {tab === "overview" && (
          <>
            <DetailRows rows={[
              ["Actor / principal", `${e.actor}${e.actorType && e.actorType !== "user" ? ` (${e.actorType})` : ""}`], ["Action / family", e.familyLabel],
              ["Outcome", humanize(e.outcome)], ["Risk classification", humanize(e.risk)], ["Timestamp UTC", e.at ? utcDate(e.at) : "—"],
              ["Subject", `${e.subjectType}: ${e.subjectId}`], ["Emitting service", e.service], ["Correlation", e.correlationId ?? "—"],
              ["Data access", showPayload ? "Payload shown" : "No payload displayed"],
            ]} />
            <p className="rounded-lg border border-accent/40 bg-accent/5 p-3 text-xs text-ink">⚠ Event metadata is visible under audit permissions. The payload can contain customer content and is hidden unless you open it for this investigation.</p>
            <Button onClick={() => setShowPayload((v) => !v)}>{showPayload ? "Hide payload" : "Show payload"}</Button>
            {showPayload && <pre className="max-h-64 overflow-auto rounded-lg border border-line bg-soft p-2 text-[11px] text-ink">{JSON.stringify(e.payload, null, 2)}</pre>}
          </>
        )}
        {tab === "integrity" && (
          <DetailRows rows={[
            ["Hash-chained", e.chainHashed ? "Yes: part of the tenant's hash chain" : "No (legacy risk-safety log)"],
            ["Tenant chain", overview ? (overview.summary.chainPassed ? `Verified · ${overview.summary.eventsChecked.toLocaleString()} events` : `Broken at ${overview.summary.brokenAt}`) : "—"],
            ["Chain checked", overview ? utcDate(overview.summary.chainVerifiedAt) : "—"],
            ["Ingested", e.ingestedAt ? utcDate(e.ingestedAt) : "—"], ["Classification", e.classification],
          ]} />
        )}
        {tab === "correlations" && (
          <div className="space-y-2 text-sm">
            {e.correlationId ? (
              <>
                <p className="text-ink">Correlation <span className="font-mono text-xs">{e.correlationId}</span> groups every event of the same request or case.</p>
                <div className="flex flex-wrap gap-2">
                  <Button onClick={() => onFilterCorrelation(e.correlationId!)}>Show related events</Button>
                  <Link href={`/audit-replay?correlation_id=${encodeURIComponent(e.correlationId)}`} className="inline-flex min-h-10 items-center rounded-lg border border-line bg-panel px-3 text-sm font-semibold text-info hover:bg-soft">Audit Replay →</Link>
                </div>
              </>
            ) : <p className="text-muted">This event has no correlation ID.</p>}
          </div>
        )}
        {tab === "investigation" && (
          <div className="space-y-2">
            <textarea className={`${inputClass} min-h-16 py-2`} placeholder="Why this event needs investigation" value={note} onChange={(ev) => setNote(ev.target.value)} />
            <div className="grid grid-cols-2 gap-2">
              <Button variant="primary" disabled={note.trim().length < 3} busy={busy === "open"}
                onClick={() => run("open", async (t) => { const r = await openIncident(t, { title: `Investigate ${humanize(e.event)}`, severity: e.risk === "critical" ? "Critical" : e.risk === "high" ? "High" : "Medium", note, event_id: e.id }); setDone(`Incident ${r.id} opened with this event linked.`); })}>Investigate event</Button>
              <Link href={`/audit-replay${e.correlationId ? `?correlation_id=${encodeURIComponent(e.correlationId)}` : ""}`} className="inline-flex min-h-10 items-center justify-center rounded-lg border border-line bg-panel text-sm font-semibold text-info hover:bg-soft">Audit Replay</Link>
            </div>
            <div className="grid grid-cols-[1fr_auto] gap-2">
              <input className={inputClass} placeholder="Existing incident ID (inc-…)" value={incidentId} onChange={(ev) => setIncidentId(ev.target.value)} />
              <Button disabled={!incidentId.trim()} busy={busy === "link"} onClick={() => run("link", async (t) => { await actOnIncident(t, incidentId.trim(), { action: "link_event", event_id: e.id, note }); setDone(`Linked to ${incidentId.trim()}.`); })}>Link incident</Button>
            </div>
            {done && <p role="status" className="text-sm text-ok">{done}</p>}
          </div>
        )}
        <ErrorNote message={error} />
      </div>
    </Panel>
  );
}

function ExportForm({ filters, onDone }: { filters: Record<string, string | number>; onDone: () => void }) {
  const [purpose, setPurpose] = useState("");
  const { busy, error, run } = useMutation();
  const scope = Object.entries(filters).filter(([, v]) => v !== "" && v !== undefined).map(([k, v]) => `${k}: ${v}`).join(" · ");
  return (
    <Panel title="Request an audit export" meta="A different Admin approves · metadata only, no payloads · expires after 7 days" action={<Button onClick={onDone}>Cancel</Button>}>
      <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); run("x", (t) => requestAuditExport(t, purpose, filters)).then((ok) => ok && onDone()); }}>
        <p className="text-sm text-ink"><b>Scope:</b> {scope || "All events, last 30 days"} (the current filters)</p>
        <textarea required minLength={10} className={`${inputClass} min-h-16 py-2`} placeholder="Purpose, e.g. quarterly access review evidence for the external auditor" value={purpose} onChange={(e) => setPurpose(e.target.value)} />
        <ErrorNote message={error} />
        <Button type="submit" variant="primary" busy={busy === "x"}>Submit for approval</Button>
      </form>
    </Panel>
  );
}

function Bottom({ data, isAdmin, selfId, onChanged }: { data: AuditOverview; isAdmin: boolean; selfId?: string; onChanged: () => void }) {
  const s = data.summary;
  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <Panel title="Recorded events by family" meta="Last 30 days">
        <div className="space-y-3">{data.families.map((f) => <ProgressRow key={f.key} label={f.label} value={f.pct} total={100}
          tone={f.key === "access" ? "bad" : f.key === "privileged" ? "warn" : "info"} right={`${f.pct}%`} />)}</div>
      </Panel>
      <Panel title="Log ingestion & integrity">
        <ul className="divide-y divide-line text-sm">
          <li className="flex justify-between py-2"><span className="text-ink">Ingestion lag (p95, recent)</span><b className="text-ink">{s.ingestionLagP95Seconds === null ? "—" : `${s.ingestionLagP95Seconds}s`}</b></li>
          <li className="flex justify-between py-2"><span className="text-ink">Hash chain</span><b className={s.chainPassed ? "text-ok" : "text-bad"}>{s.chainPassed ? "Verified" : "Broken"}</b></li>
          <li className="flex justify-between py-2"><span className="text-ink">Events checked</span><b className="text-ink">{s.eventsChecked.toLocaleString()}</b></li>
          <li className="flex justify-between py-2"><span className="text-ink">Evidence export gate</span><Badge tone="warn">APPROVAL REQUIRED</Badge></li>
        </ul>
        <p className="mt-2 text-xs text-muted">An intact chain proves records were not altered; it is not evidence that the activity itself was safe.</p>
      </Panel>
      <Panel title="Priority audit actions">
        <ul className="space-y-2 text-sm">
          {data.priority.slice(0, 3).map((e) => (
            <li key={e.id} className={`rounded-lg border-l-4 p-2.5 ${e.risk === "critical" ? "border-l-bad bg-bad/5" : "border-l-accent bg-accent/5"}`}>
              <b className="text-ink">{humanize(e.risk)} · {humanize(e.event.replace(/\./g, " "))}</b>
              <span className="block text-xs text-muted">{e.actor} · {e.at ? utcDate(e.at) : ""}</span></li>))}
          {data.exports.slice(0, 4).map((x) => <ExportRow key={x.id} x={x} isAdmin={isAdmin} selfId={selfId} onChanged={onChanged} />)}
          {!data.priority.length && !data.exports.length && <li className="text-muted">Nothing needs attention.</li>}
        </ul>
      </Panel>
    </div>
  );
}

function ExportRow({ x, isAdmin, selfId, onChanged }: { x: AuditExport; isAdmin: boolean; selfId?: string; onChanged: () => void }) {
  const { busy, error, run } = useMutation();
  return (
    <li className="rounded-lg border border-line p-2.5">
      <b className="text-ink">{x.ref} · export {x.status}</b>
      <span className="block text-xs text-muted">{x.purpose} · {x.requestedBy}</span>
      <div className="mt-1.5 flex flex-wrap gap-2">
        {x.status === "pending" && isAdmin && x.requestedById !== selfId && <>
          <Button busy={busy === "a"} onClick={() => run("a", (t) => decideAuditExport(t, x.id, true, "")).then((ok) => ok && onChanged())}>Approve</Button>
          <Button variant="danger" busy={busy === "r"} onClick={() => { const note = window.prompt("Reason for refusing this export?") ?? ""; if (note.trim()) run("r", (t) => decideAuditExport(t, x.id, false, note)).then((ok) => ok && onChanged()); }}>Refuse</Button>
        </>}
        {x.status === "pending" && x.requestedById === selfId && <span className="text-xs text-muted">Awaiting another Admin</span>}
        {x.downloadable && <Button busy={busy === "d"} onClick={() => run("d", (t) => downloadAuditExport(t, x.id))}><Download size={13} /> Download CSV</Button>}
      </div>
      <ErrorNote message={error} />
    </li>
  );
}
