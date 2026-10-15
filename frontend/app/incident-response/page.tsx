"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { AlertOctagon, CheckCircle2, Search, ShieldAlert, ShieldCheck, Siren, UserX } from "lucide-react";
import { useLiveData } from "@/components/overview/useLiveData";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import {
  Badge, Breadcrumb, Button, DetailRows, EmptyState, ErrorNote, KpiTile, OpsHero, Panel, PillTabs, ProgressRow,
  inputClass, useMutation, utcDate,
} from "@/components/operations/ui";
import {
  actOnIncident, getIncidentRegister, getReviewPeople, openIncident,
  type IncidentRegister, type IncidentRow, type ReviewPerson,
} from "@/lib/api";

type TabKey = "all" | "OPEN" | "CONTAINED" | "critical" | "RESOLVED";
const SEV_TONE = { Critical: "bad", High: "warn", Medium: "info", Low: "ok" } as const;
const STATUS = { OPEN: { label: "Open", tone: "bad" }, CONTAINED: { label: "Contained", tone: "warn" }, RESOLVED: { label: "Resolved", tone: "ok" } } as const;

export default function IncidentResponsePage() {
  const { data, error, loading, signedOut, reload } = useLiveData(
    "incident-response", (token, signal) => getIncidentRegister(token, signal), 30_000,
  );
  const people = useLiveData("review-people", (token, signal) => getReviewPeople(token, signal), 20_000);
  const [tab, setTab] = useState<TabKey>("all");
  const [selectedId, setSelectedId] = useState("");
  const [creating, setCreating] = useState(false);
  const rows = useMemo(() => data?.incidents ?? [], [data]);
  const selected = rows.find((r) => r.id === selectedId) ?? rows.find((r) => r.status !== "RESOLVED") ?? rows[0];

  return (
    <main className="flex-1 space-y-4 overflow-y-auto p-4">
      <Breadcrumb section="Review, Escalation & Audit" page="Incident Response" />
      <OpsHero icon={Siren} eyebrow="Review, Escalation & Audit" title="Incident Response"
        subtitle="Detect, contain, and resolve security incidents with accountable ownership and a complete audit trail.">
        <p className="text-base font-bold text-white">Contain first. Prove it after.</p>
        <p>Every action attributed · Linked to audit evidence</p>
      </OpsHero>
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />
      {data && (
        <>
          <Kpis data={data} />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <PillTabs label="Incident views" active={tab} onChange={setTab} tabs={[
              { key: "all", label: "All incidents" }, { key: "OPEN", label: "Open", count: data.summary.open },
              { key: "CONTAINED", label: "Contained", count: data.summary.contained }, { key: "critical", label: "Critical", count: data.summary.critical },
              { key: "RESOLVED", label: "Resolved" }]} />
            <Button variant="primary" onClick={() => setCreating(true)}>+ Open incident</Button>
          </div>
          {creating && <CreateForm onDone={() => { setCreating(false); reload(); }} />}
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_440px]">
            <Register rows={rows} tab={tab} selectedId={selected?.id} onSelect={setSelectedId} />
            {selected ? <Detail key={selected.id} i={selected} people={people.data ?? []} onChanged={reload} />
              : <Panel title="Incident"><EmptyState icon={ShieldCheck} title="No incidents">Security detections, support escalations and audit findings open incidents here.</EmptyState></Panel>}
          </div>
          <Bottom data={data} />
        </>
      )}
    </main>
  );
}

function Kpis({ data }: { data: IncidentRegister }) {
  const s = data.summary;
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <KpiTile icon={Siren} tone={s.open ? "bad" : "ok"} value={s.open} label="Open incidents" hint="Not yet contained" />
      <KpiTile icon={ShieldAlert} tone={s.contained ? "warn" : "ok"} value={s.contained} label="Contained" hint="Awaiting resolution" />
      <KpiTile icon={AlertOctagon} tone={s.critical ? "bad" : "ok"} value={`${s.critical} / ${s.high}`} label="Critical / High" hint="Unresolved" />
      <KpiTile icon={UserX} tone={s.unowned ? "warn" : "ok"} value={s.unowned} label="Without owner" hint="Assign accountable responder" />
      <KpiTile icon={CheckCircle2} tone="ok" value={s.resolved30d} label="Resolved (30 days)" hint={s.mttrHours === null ? "No resolutions yet" : `Mean time to resolve ${s.mttrHours}h`} />
    </div>
  );
}

function Register({ rows, tab, selectedId, onSelect }: { rows: IncidentRow[]; tab: TabKey; selectedId?: string; onSelect: (id: string) => void }) {
  const [query, setQuery] = useState("");
  const [sev, setSev] = useState("");
  const [source, setSource] = useState("");
  const shown = rows.filter((i) => (tab === "all" || (tab === "critical" ? i.severity === "Critical" && i.status !== "RESOLVED" : i.status === tab))
    && (!sev || i.severity === sev) && (!source || i.sourceLabel === source)
    && (!query || `${i.id} ${i.title} ${i.sourceLabel} ${i.owner ?? ""}`.toLowerCase().includes(query.toLowerCase())));
  const sources = [...new Set(rows.map((r) => r.sourceLabel))];
  return (
    <Panel title="Incident register" meta={`${shown.length} of ${rows.length}`}>
      <div className="mb-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_10rem_12rem_auto]">
        <label className="relative"><Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input className={`${inputClass} pl-9`} placeholder="Search incident ID, title, source or owner…" value={query} onChange={(e) => setQuery(e.target.value)} /></label>
        <select aria-label="Severity" className={inputClass} value={sev} onChange={(e) => setSev(e.target.value)}><option value="">All severities</option>{["Critical", "High", "Medium", "Low"].map((s) => <option key={s}>{s}</option>)}</select>
        <select aria-label="Source" className={inputClass} value={source} onChange={(e) => setSource(e.target.value)}><option value="">All sources</option>{sources.map((s) => <option key={s}>{s}</option>)}</select>
        <Button onClick={() => { setQuery(""); setSev(""); setSource(""); }}>Clear</Button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[740px] text-left text-sm">
          <thead className="bg-soft text-xs text-muted"><tr>{["Incident ID", "Title", "Source", "Severity", "Status", "Owner", "Opened (UTC)"].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr></thead>
          <tbody>{shown.map((i) => (
            <tr key={i.id} onClick={() => onSelect(i.id)} aria-selected={selectedId === i.id} className={`cursor-pointer border-b border-line hover:bg-soft ${selectedId === i.id ? "bg-info/5" : ""}`}>
              <td className="px-3 py-2.5 font-mono text-xs font-semibold text-info">{i.id}</td>
              <td className="px-3 py-2.5 font-semibold text-ink">{i.title}</td>
              <td className="px-3 py-2.5 text-ink">{i.sourceLabel}</td>
              <td className="px-3 py-2.5"><Badge tone={SEV_TONE[i.severity] ?? "warn"}>{i.severity}</Badge></td>
              <td className="px-3 py-2.5"><Badge tone={STATUS[i.status].tone}>{STATUS[i.status].label}</Badge></td>
              <td className="px-3 py-2.5 text-ink">{i.owner ?? <span className="text-muted">Unassigned</span>}</td>
              <td className="px-3 py-2.5 text-ink">{i.openedAt ? utcDate(i.openedAt) : "—"}</td>
            </tr>))}</tbody>
        </table>
        {!shown.length && <EmptyState title={rows.length ? "No incidents in this view" : "No incidents recorded"} />}
      </div>
    </Panel>
  );
}

type DetailTab = "overview" | "timeline" | "evidence";

function Detail({ i, people, onChanged }: { i: IncidentRow; people: ReviewPerson[]; onChanged: () => void }) {
  const [tab, setTab] = useState<DetailTab>("overview");
  const [note, setNote] = useState("");
  const [eventId, setEventId] = useState("");
  const { busy, error, run } = useMutation();
  const closed = i.status === "RESOLVED";
  const act = (action: string, extra: { owner_id?: string; event_id?: string; severity?: string } = {}) =>
    run(action, (t) => actOnIncident(t, i.id, { action, note, ...extra })).then((ok) => { if (ok) { setNote(""); setEventId(""); onChanged(); } });
  return (
    <Panel title={i.id} action={<Badge tone={STATUS[i.status].tone}>{STATUS[i.status].label}</Badge>}>
      <h3 className="-mt-1 text-lg font-extrabold text-ink">{i.title}</h3>
      <div className="mb-3 mt-1 flex gap-1.5"><Badge tone={SEV_TONE[i.severity] ?? "warn"}>{i.severity}</Badge><Badge tone="info">{i.sourceLabel}</Badge></div>
      <PillTabs label="Incident detail" active={tab} onChange={setTab} tabs={[
        { key: "overview", label: "Overview" }, { key: "timeline", label: "Timeline", count: i.timeline.length }, { key: "evidence", label: "Evidence", count: i.linkedEventIds.length }]} />
      <div className="mt-4 space-y-4">
        {!closed && i.severity === "Critical" && <p className="rounded-lg border border-bad/30 bg-bad/5 p-3 text-xs text-ink"><b className="text-bad">Critical incident.</b> Containment first; resolution is signed off by someone other than the owner.</p>}
        {tab === "overview" && (
          <DetailRows rows={[
            ["Severity", i.severity], ["Status", STATUS[i.status].label], ["Detected by", i.sourceLabel],
            ["Restricted class", i.subClass ?? "—"], ["Owner", i.owner ?? "Unassigned"],
            ["Opened", i.openedAt ? utcDate(i.openedAt) : "—"], ["Open for", i.hoursOpen === null ? "—" : `${i.hoursOpen}h`],
            ["Resolved", i.resolvedAt ? `${utcDate(i.resolvedAt)} · ${i.resolutionNote}` : "—"],
            ["Linked ticket", i.ticketId ? "Support ticket linked" : "None"],
          ]} />
        )}
        {tab === "timeline" && (
          <ol className="space-y-2 border-l border-line pl-4 text-sm">{[...i.timeline].reverse().map((e, k) => (
            <li key={k}><b className="text-ink">{e.action.replace(/_/g, " ")}</b> <span className="text-xs text-muted">· {e.actor} · {utcDate(e.timestamp)}</span>{e.note && <p className="text-ink">{e.note}</p>}</li>))}</ol>
        )}
        {tab === "evidence" && (
          <div className="space-y-2 text-sm">
            {i.linkedEventIds.length ? <ul className="space-y-1">{i.linkedEventIds.map((id) => <li key={id} className="font-mono text-xs text-ink">{id}</li>)}</ul>
              : <p className="text-muted">No audit events linked yet.</p>}
            {i.queryId && <Link href={`/audit-replay?correlation_id=${encodeURIComponent(i.queryId)}`} className="font-semibold text-info">Replay the triggering question →</Link>}
            {!closed && <div className="grid grid-cols-[1fr_auto] gap-2">
              <input className={inputClass} placeholder="Audit event ID from Audit Logs" value={eventId} onChange={(e) => setEventId(e.target.value)} />
              <Button disabled={!eventId.trim()} busy={busy === "link_event"} onClick={() => act("link_event", { event_id: eventId.trim() })}>Link event</Button>
            </div>}
          </div>
        )}
        <ErrorNote message={error} />
        <div className="space-y-2 border-t border-line pt-3">
          <textarea className={`${inputClass} min-h-16 py-2`} placeholder="Containment, investigation or resolution note" value={note} onChange={(e) => setNote(e.target.value)} />
          <div className="grid grid-cols-2 gap-2">
            {i.status === "OPEN" && <Button variant="primary" busy={busy === "contain"} onClick={() => act("contain")}>Mark contained</Button>}
            {!closed && <select aria-label="Assign owner" className={inputClass} value="" disabled={busy === "assign"} onChange={(e) => e.target.value && act("assign", { owner_id: e.target.value })}>
              <option value="">Assign owner…</option>{people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>}
            {!closed && <select aria-label="Severity" className={inputClass} value="" disabled={busy === "severity"} onChange={(e) => e.target.value && act("severity", { severity: e.target.value })}>
              <option value="">Change severity…</option>{["Critical", "High", "Medium", "Low"].filter((s) => s !== i.severity).map((s) => <option key={s}>{s}</option>)}</select>}
            <Button busy={busy === "note"} onClick={() => act("note")}>Add note</Button>
            {!closed ? <Button variant="primary" busy={busy === "resolve"} onClick={() => act("resolve")}>Resolve incident</Button>
              : <Button busy={busy === "reopen"} onClick={() => act("reopen")}>Reopen</Button>}
          </div>
        </div>
      </div>
    </Panel>
  );
}

function Bottom({ data }: { data: IncidentRegister }) {
  const s = data.summary;
  const unresolved = Math.max(1, s.open + s.contained);
  const maxSource = Math.max(1, ...data.sources30d.map((x) => x.count));
  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <Panel title="Unresolved by severity">
        <div className="space-y-3">{(["Critical", "High", "Medium", "Low"] as const).map((k) => (
          <ProgressRow key={k} label={k} value={s.bySeverity[k] ?? 0} total={unresolved} tone={k === "Critical" ? "bad" : k === "High" ? "warn" : k === "Medium" ? "info" : "ok"} right={s.bySeverity[k] ?? 0} />))}</div>
      </Panel>
      <Panel title="Detection sources" meta="Last 30 days">
        {data.sources30d.length ? <div className="space-y-3">{data.sources30d.map((x) => <ProgressRow key={x.source} label={x.source} value={x.count} total={maxSource} tone="info" right={x.count} />)}</div>
          : <p className="text-sm text-muted">No incidents opened in the last 30 days.</p>}
      </Panel>
      <Panel title="Response doctrine">
        <ul className="space-y-2 text-sm text-ink">
          {["Contain before investigating root cause", "Every action credited to the signed-in responder",
            "Critical incidents closed by someone other than the owner", "Evidence linked from the audit ledger, never copied",
            "Support tickets and audit findings stay linked"].map((t) => <li key={t} className="flex gap-2"><span className="text-ok">✓</span>{t}</li>)}
        </ul>
      </Panel>
    </div>
  );
}

function CreateForm({ onDone }: { onDone: () => void }) {
  const [v, setV] = useState({ title: "", severity: "High", note: "" });
  const { busy, error, run } = useMutation();
  return (
    <Panel title="Open incident" action={<Button onClick={onDone}>Cancel</Button>}>
      <form className="grid gap-3 md:grid-cols-3" onSubmit={(e) => { e.preventDefault(); run("c", (t) => openIncident(t, v)).then((ok) => ok && onDone()); }}>
        <input required minLength={3} className={`${inputClass} md:col-span-2`} placeholder="What happened?" value={v.title} onChange={(e) => setV({ ...v, title: e.target.value })} aria-label="Title" />
        <select aria-label="Severity" className={inputClass} value={v.severity} onChange={(e) => setV({ ...v, severity: e.target.value })}>{["Critical", "High", "Medium", "Low"].map((s) => <option key={s}>{s}</option>)}</select>
        <textarea required minLength={3} className={`${inputClass} min-h-16 py-2 md:col-span-3`} placeholder="Detection details and first actions" value={v.note} onChange={(e) => setV({ ...v, note: e.target.value })} aria-label="Details" />
        <div className="md:col-span-3"><ErrorNote message={error} /></div>
        <div><Button type="submit" variant="primary" busy={busy === "c"}>Open incident</Button></div>
      </form>
    </Panel>
  );
}
