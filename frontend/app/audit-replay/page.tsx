"use client";

import Link from "next/link";
import { Suspense, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { CheckCircle2, ClipboardList, FileLock2, History, Search, ShieldAlert, UserCheck } from "lucide-react";
import { useLiveData } from "@/components/overview/useLiveData";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import {
  Badge, Breadcrumb, Button, DetailRows, EmptyState, KpiTile, OpsHero, Panel, PillTabs, ProgressRow, humanize, inputClass, utcDate,
} from "@/components/operations/ui";
import { getReplayManifest, getTraceRegister, type ReplayManifest, type TraceRegister, type TraceRow } from "@/lib/api";

const STATE: Record<TraceRow["state"], { label: string; tone: "ok" | "warn" | "bad" | "info" | "neutral" }> = {
  verified: { label: "Verified", tone: "ok" }, partial: { label: "Partial", tone: "warn" }, restricted: { label: "Restricted", tone: "bad" },
  review_open: { label: "Review open", tone: "warn" }, refused: { label: "Refused", tone: "info" },
};
const TRUST_TONE = { AUTHORITATIVE: "ok", LIMITED: "warn", INCONCLUSIVE: "bad" } as const;

export default function AuditReplayPage() {
  return <Suspense fallback={null}><AuditReplay /></Suspense>;
}

function AuditReplay() {
  const params = useSearchParams();
  const deepLink = params.get("correlation_id") ?? "";
  const { data, error, loading, signedOut, reload } = useLiveData("audit-traces", (token, signal) => getTraceRegister(token, signal), 60_000);
  const [selectedId, setSelectedId] = useState("");
  const [lookup, setLookup] = useState("");
  const traces = useMemo(() => data?.traces ?? [], [data]);
  const current = selectedId || deepLink || traces[0]?.correlationId || "";
  const trace = traces.find((t) => t.correlationId === current);

  return (
    <main className="flex-1 space-y-4 overflow-y-auto p-4">
      <Breadcrumb section="Review, Escalation & Audit" page="Audit Replay" />
      <OpsHero icon={History} eyebrow="Review, Escalation & Audit" title="Audit Replay"
        subtitle="Reconstruct recorded decisions, verify evidence integrity, and trace human oversight—without re-executing AI or tools.">
        <p className="text-base font-bold text-white">Recorded evidence. Verifiable decisions.</p>
        <p>Tenant-scoped · Read-only by design</p>
      </OpsHero>
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />
      {data && <Kpis data={data} />}
      <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); if (lookup.trim()) setSelectedId(lookup.trim()); }}>
        <input className={`${inputClass} max-w-md`} placeholder="Replay any query, source or prompt ID…" value={lookup} onChange={(e) => setLookup(e.target.value)} aria-label="Correlation ID" />
        <Button type="submit">Replay</Button>
      </form>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_480px]">
        {data ? <Register data={data} selectedId={current} onSelect={setSelectedId} /> : <Panel title="Trace register"><EmptyState title="Loading traces…" /></Panel>}
        {current ? <TraceDetail key={current} correlationId={current} trace={trace} /> : <Panel title="Selected trace"><EmptyState icon={History} title="No traces recorded yet" /></Panel>}
      </div>
      {data && <Bottom data={data} onSelect={setSelectedId} />}
    </main>
  );
}

function Kpis({ data }: { data: TraceRegister }) {
  const s = data.summary;
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <KpiTile icon={ClipboardList} value={s.recorded30d.toLocaleString()} label="Recorded traces" hint="Distinct correlations · last 30 days" />
      <KpiTile icon={CheckCircle2} tone="ok" value={s.replayReady} label="Replay-ready traces" hint={`Of the ${s.shown} most recent: complete and hash-verified`} />
      <KpiTile icon={ShieldAlert} tone={s.holds ? "bad" : "ok"} value={s.holds} label="Integrity / restriction holds" hint="Partial, unverified or restricted" />
      <KpiTile icon={UserCheck} tone={s.humanReviewsOpen ? "warn" : "ok"} value={s.humanReviewsOpen} label="Human reviews open" hint="Decision evidence required" />
      <KpiTile icon={FileLock2} tone="info" value={s.exportHolds} label="Controlled export holds" hint="Awaiting an Admin's approval" />
    </div>
  );
}

function Register({ data, selectedId, onSelect }: { data: TraceRegister; selectedId: string; onSelect: (id: string) => void }) {
  const [query, setQuery] = useState("");
  const [state, setState] = useState("");
  const [kind, setKind] = useState("");
  const rows = data.traces.filter((t) => (!state || t.state === state) && (!kind || t.kind === kind)
    && (!query || `${t.correlationId} ${t.title} ${t.kind}`.toLowerCase().includes(query.toLowerCase())));
  return (
    <Panel title="Trace register" meta={`${rows.length} of the ${data.traces.length} most recent traces`}>
      <div className="mb-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_10rem_10rem_auto]">
        <label className="relative"><Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input className={`${inputClass} pl-9`} placeholder="Search trace ID, question or type…" value={query} onChange={(e) => setQuery(e.target.value)} /></label>
        <select aria-label="Trace state" className={inputClass} value={state} onChange={(e) => setState(e.target.value)}><option value="">All trace states</option>{Object.entries(STATE).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select>
        <select aria-label="Type" className={inputClass} value={kind} onChange={(e) => setKind(e.target.value)}><option value="">All types</option>{[...new Set(data.traces.map((t) => t.kind))].map((k) => <option key={k}>{k}</option>)}</select>
        <Button onClick={() => { setQuery(""); setState(""); setKind(""); }}>Clear</Button>
      </div>
      <p className="mb-3 rounded-lg border border-accent/30 bg-accent/5 px-3 py-2 text-xs text-ink">⚑ Evidence replay is not re-inference. Original events are frozen; missing, unverified or restricted records stay visibly flagged.</p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead className="bg-soft text-xs text-muted"><tr>{["Trace ID", "Recorded matter", "Type", "Integrity", "Trace state", "Recorded (UTC)"].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr></thead>
          <tbody>{rows.map((t) => (
            <tr key={t.correlationId} onClick={() => onSelect(t.correlationId)} aria-selected={selectedId === t.correlationId} className={`cursor-pointer border-b border-line hover:bg-soft ${selectedId === t.correlationId ? "bg-info/5" : ""}`}>
              <td className="px-3 py-2.5 font-mono text-xs font-semibold text-info">{t.correlationId.slice(0, 14)}</td>
              <td className="max-w-xs px-3 py-2.5"><b className="block truncate text-ink">{t.title}</b><span className="text-xs text-muted">{t.events} events</span></td>
              <td className="px-3 py-2.5 text-ink">{t.kind}</td>
              <td className="px-3 py-2.5"><Badge tone={t.integrity === "verified" ? "ok" : "bad"}>{t.integrity === "verified" ? "Verified" : "Exception"}</Badge></td>
              <td className="px-3 py-2.5"><Badge tone={STATE[t.state].tone}>{STATE[t.state].label}</Badge></td>
              <td className="whitespace-nowrap px-3 py-2.5 text-ink">{t.lastAt ? utcDate(t.lastAt) : "—"}</td>
            </tr>))}</tbody>
        </table>
        {!rows.length && <EmptyState title="No traces match these filters" />}
      </div>
    </Panel>
  );
}

type DetailTab = "overview" | "events" | "decisions" | "manifest";

function TraceDetail({ correlationId, trace }: { correlationId: string; trace?: TraceRow }) {
  const [tab, setTab] = useState<DetailTab>("overview");
  const m = useLiveData(`replay:${correlationId}`, (token) => getReplayManifest(token, correlationId), 45_000);
  const manifest: ReplayManifest | null = m.data;
  const decisions = manifest?.events.filter((e) => /review|decision|approv|refus|escalat|incident/i.test(e.event_name)) ?? [];
  const restricted = trace && (trace.state === "restricted" || trace.state === "partial" || trace.integrity === "exception");
  return (
    <Panel title={`Selected trace · ${correlationId.slice(0, 18)}`} action={trace ? <Badge tone={STATE[trace.state].tone}>{STATE[trace.state].label}</Badge> : undefined}>
      <h3 className="-mt-1 mb-1 text-lg font-extrabold text-ink">{trace?.title ?? correlationId}</h3>
      <p className="mb-3 text-xs text-muted">{trace ? `${trace.kind} · ${trace.events} events` : "Looked up by ID"}</p>
      <PillTabs label="Trace detail" active={tab} onChange={setTab} tabs={[
        { key: "overview", label: "Overview" }, { key: "events", label: "Event replay", count: manifest?.events.length },
        { key: "decisions", label: "Decisions", count: decisions.length }, { key: "manifest", label: "Manifest" }]} />
      <div className="mt-4 space-y-4">
        {m.loading && !manifest && <p className="text-sm text-muted">Reconstructing from recorded events…</p>}
        {m.error && <p className="text-sm text-bad">{m.error}</p>}
        {manifest && (
          <>
            {(restricted || manifest.known_gaps.length > 0) && (
              <div className="rounded-lg border border-bad/30 bg-bad/5 p-3">
                <p className="text-sm font-bold text-bad">Replay / export restrictions apply</p>
                <p className="text-sm text-ink">{manifest.known_gaps.length ? `${manifest.known_gaps.length} expected event(s) missing; the record stays readable but replay assurance is ${manifest.manifest_trustworthiness.toLowerCase()}.`
                  : trace?.state === "restricted" ? "An open security incident is linked to this trace." : "The trace is incomplete or not fully hash-verified."}</p>
              </div>
            )}
            {tab === "overview" && (
              <>
                <DetailRows rows={[
                  ["Correlation", manifest.correlation_id], ["Completeness", humanize(manifest.completeness_status.toLowerCase())],
                  ["Trustworthiness", manifest.manifest_trustworthiness], ["Hash chain", manifest.chain_verification_result],
                  ["Events captured", manifest.events.length], ["Known gaps", manifest.known_gaps.length || "None"],
                  ["Human review", trace?.reviewCase ? `Case ${trace.reviewCase.slice(0, 8)} · ${trace.reviewStatus}` : trace?.humanReview ? "Created" : "None"],
                  ["Incident", trace?.incident ?? "None"], ["Reconstructed", utcDate(manifest.generated_at)],
                ]} />
                <div className="grid grid-cols-3 gap-2">
                  <Button variant="primary" onClick={() => setTab("events")}>▶ Inspect timeline</Button>
                  <Button onClick={() => setTab("manifest")}>View manifest</Button>
                  {trace?.reviewCase ? <Link href="/review-tasks" className="inline-flex min-h-10 items-center justify-center rounded-lg border border-line bg-panel text-sm font-semibold text-info hover:bg-soft">Review case</Link>
                    : <Link href={`/audit-logs`} className="inline-flex min-h-10 items-center justify-center rounded-lg border border-line bg-panel text-sm font-semibold text-info hover:bg-soft">Audit Logs</Link>}
                </div>
              </>
            )}
            {tab === "events" && (
              <ol className="max-h-[32rem] space-y-1.5 overflow-auto border-l border-line pl-4 text-sm">{manifest.events.map((e) => (
                <li key={e.event_id}><b className="text-ink">{humanize(e.event_name)}</b> <span className="text-xs text-muted">· {e.emitting_service} · {e.event_time ? utcDate(e.event_time) : "—"}</span>
                  <Badge tone={e.chain_hash ? "ok" : "neutral"}>{e.chain_hash ? "hashed" : "unverified"}</Badge></li>))}</ol>
            )}
            {tab === "decisions" && (decisions.length ? (
              <ul className="space-y-2 text-sm">{decisions.map((e) => (
                <li key={e.event_id} className="rounded-lg border border-line p-2.5"><b className="text-ink">{humanize(e.event_name)}</b>
                  <span className="block text-xs text-muted">{e.event_time ? utcDate(e.event_time) : ""}</span></li>))}</ul>
            ) : <p className="text-sm text-muted">No human or governance decision was recorded in this trace.</p>)}
            {tab === "manifest" && (
              <div className="space-y-2 text-sm">
                {manifest.known_gaps.map((g, i) => <p key={i} className="rounded-lg border border-accent/30 bg-accent/5 p-2 text-ink"><b>{g.event_class}</b>: expected {g.expected_event_name}, {g.gap_reason} ({g.impact_on_replay})</p>)}
                <p className="break-all font-mono text-[11px] text-muted">manifest_hash: {manifest.manifest_hash}</p>
                <p className="text-xs text-muted">Generated by {manifest.generated_by}. The hash lets anyone confirm this manifest was not altered.</p>
              </div>
            )}
            <Badge tone={TRUST_TONE[manifest.manifest_trustworthiness]}>Trust: {manifest.manifest_trustworthiness}</Badge>
          </>
        )}
      </div>
    </Panel>
  );
}

function Bottom({ data, onSelect }: { data: TraceRegister; onSelect: (id: string) => void }) {
  const i = data.integrity;
  const total = Math.max(1, i.total);
  const exceptions = data.traces.filter((t) => t.state === "restricted" || t.state === "partial" || t.integrity === "exception").slice(0, 3);
  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <Panel title="Evidence integrity by control" meta={`Of the ${i.total} most recent traces`}>
        <div className="space-y-3">
          <ProgressRow label="Hash-chain verification" value={i.hashed} total={total} tone="ok" />
          <ProgressRow label="Required event completeness" value={i.complete} total={total} tone="warn" />
          <ProgressRow label="Human review decided" value={i.reviewed} total={total} tone="info" />
        </div>
      </Panel>
      <Panel title="Priority forensic exceptions">
        {exceptions.length ? (
          <ul className="space-y-2 text-sm">{exceptions.map((t) => (
            <li key={t.correlationId} className="flex gap-2"><Badge tone={STATE[t.state].tone}>{STATE[t.state].label}</Badge>
              <button onClick={() => onSelect(t.correlationId)} className="text-left"><b className="block text-ink hover:underline">{t.title.slice(0, 60)}</b>
                <span className="text-xs text-muted">{t.integrity === "exception" ? "Unhashed events present" : t.state === "restricted" ? "Linked incident open" : "No terminal event recorded"}</span></button></li>))}</ul>
        ) : <p className="text-sm text-muted">No exceptions among recent traces.</p>}
      </Panel>
      <Panel title="Chain of custody & replay doctrine">
        <ul className="space-y-2 text-sm text-ink">
          <li><b>◆ Preserve originals</b><br /><span className="text-xs text-muted">Events are append-only and hash-chained; corrections are separate compensating events.</span></li>
          <li><b>◆ Reconstruct, don&apos;t re-execute</b><br /><span className="text-xs text-muted">Replay reads the captured inputs, tool calls, outputs and policy events.</span></li>
          <li><b>◆ Reproducibility disclosure</b><br /><span className="text-xs text-muted">Exact model recomputation is not presumed possible.</span></li>
        </ul>
      </Panel>
    </div>
  );
}
