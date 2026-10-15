"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { AlertTriangle, Clock3, ListChecks, Search, ShieldCheck, TriangleAlert, UserCheck } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { useLiveData } from "@/components/overview/useLiveData";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import {
  Badge, Breadcrumb, Button, DetailRows, EmptyState, ErrorNote, KpiTile, OpsHero, Panel, PillTabs, ProgressRow,
  inputClass, useMutation, utcDate,
} from "@/components/operations/ui";
import { createSafetyOverride } from "@/lib/safety-api";
import {
  actOnEscalationCase, getEscalationQueue, getReviewPeople, raiseEscalation,
  type EscalationQueue, type EscalationRow, type ReviewPerson,
} from "@/lib/api";

type TabKey = "all" | "mine" | "critical" | "overdue" | "expert" | "holds";
const SEV_TONE = { Critical: "bad", High: "warn", Medium: "info", Low: "ok" } as const;
const STATUS: Record<EscalationRow["status"], { label: string; tone: "warn" | "info" | "bad" | "ok" | "neutral" }> = {
  open: { label: "Open", tone: "info" }, expert_review: { label: "Expert review", tone: "warn" },
  escalated: { label: "Escalated", tone: "bad" }, resolved: { label: "Closed", tone: "ok" }, refused: { label: "Refused", tone: "neutral" },
};
const SLA: Record<EscalationRow["sla"], { label: string; tone: "bad" | "warn" | "ok" | "neutral" }> = {
  overdue: { label: "Overdue", tone: "bad" }, due_today: { label: "Due today", tone: "warn" },
  due_tomorrow: { label: "Due tomorrow", tone: "ok" }, within: { label: "Within SLA", tone: "ok" },
  closed: { label: "Closed", tone: "neutral" }, none: { label: "No SLA", tone: "neutral" },
};
const isOpen = (e: EscalationRow) => e.status !== "resolved" && e.status !== "refused";

export default function EscalationQueuePage() {
  const { profile } = useAuth();
  const { data, error, loading, signedOut, reload } = useLiveData(
    "escalation-queue", (token, signal) => getEscalationQueue(token, signal), 30_000,
  );
  const people = useLiveData("review-people", (token, signal) => getReviewPeople(token, signal), 20_000);
  const [tab, setTab] = useState<TabKey>("all");
  const [selectedId, setSelectedId] = useState("");
  const [creating, setCreating] = useState(false);
  const rows = useMemo(() => data?.escalations ?? [], [data]);
  const selected = rows.find((r) => r.id === selectedId) ?? rows.find(isOpen) ?? rows[0];

  return (
    <main className="flex-1 space-y-4 overflow-y-auto p-4">
      <Breadcrumb section="Review, Escalation & Audit" page="Escalation Queue" />
      <OpsHero icon={TriangleAlert} eyebrow="Review, Escalation & Audit" title="Escalation Queue"
        subtitle="Resolve exceptions through accountable expertise, evidence, SLA controls, and independent decisions.">
        <p className="text-base font-bold text-white">Human judgment. Evidence preserved.</p>
        <p>Kriton cannot independently approve closure.</p>
      </OpsHero>
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />
      {data && (
        <>
          <Kpis data={data} />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <PillTabs label="Escalation views" active={tab} onChange={setTab} tabs={[
              { key: "all", label: "All escalations" }, { key: "mine", label: "Assigned to me" },
              { key: "critical", label: "Critical", count: data.summary.critical }, { key: "overdue", label: "SLA overdue", count: data.summary.overdue },
              { key: "expert", label: "Expert review", count: data.summary.expertReview }, { key: "holds", label: "Governance holds", count: data.overrides.length }]} />
            <Button variant="primary" onClick={() => setCreating(true)}>+ New escalation</Button>
          </div>
          {creating && <CreateForm onDone={() => { setCreating(false); reload(); }} />}
          {tab === "holds" ? <HoldsPanel data={data} onChanged={reload} /> : (
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
              <Register rows={rows} tab={tab} selfId={profile?.id} selectedId={selected?.id} onSelect={setSelectedId} />
              {selected ? <Detail key={selected.id} e={selected} people={people.data ?? []} selfId={profile?.id} onChanged={reload} />
                : <Panel title="Selected escalation"><EmptyState icon={ShieldCheck} title="No escalations">High-risk questions and manual escalations appear here with their SLA.</EmptyState></Panel>}
            </div>
          )}
          <Bottom data={data} onSelect={setSelectedId} />
        </>
      )}
    </main>
  );
}

function Kpis({ data }: { data: EscalationQueue }) {
  const s = data.summary;
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <KpiTile icon={ListChecks} value={s.open} label="Open escalations" hint={`${s.unassigned} without an assigned expert`} />
      <KpiTile icon={AlertTriangle} tone={s.critical ? "bad" : "ok"} value={s.critical} label="Critical severity" hint="Priority investigation required" />
      <KpiTile icon={Clock3} tone={s.overdue ? "bad" : "ok"} value={s.overdue} label="Overdue response" hint="Service target breached" />
      <KpiTile icon={UserCheck} tone="warn" value={s.expertReview} label="Expert review" hint="Independent decision awaited" />
      <KpiTile icon={ShieldCheck} tone="info" value={s.closureRestricted} label="Closure restricted" hint={`${s.linkedToReview} decided through Review Tasks`} />
    </div>
  );
}

function Register({ rows, tab, selfId, selectedId, onSelect }: { rows: EscalationRow[]; tab: TabKey; selfId?: string; selectedId?: string; onSelect: (id: string) => void }) {
  const [query, setQuery] = useState("");
  const [sev, setSev] = useState("");
  const [state, setState] = useState("");
  const [jur, setJur] = useState("");
  const [owner, setOwner] = useState("");
  const [showClosed, setShowClosed] = useState(false);
  const shown = rows.filter((e) => (showClosed || isOpen(e) || tab !== "all")
    && (tab !== "mine" || e.assigneeId === selfId) && (tab !== "critical" || (e.severity === "Critical" && isOpen(e)))
    && (tab !== "overdue" || e.sla === "overdue") && (tab !== "expert" || e.status === "expert_review")
    && (!sev || e.severity === sev) && (!state || e.status === state) && (!jur || e.jurisdiction === jur) && (!owner || e.assignee === owner)
    && (!query || `${e.id} ${e.topic} ${e.trigger} ${e.jurisdiction} ${e.assignee ?? ""}`.toLowerCase().includes(query.toLowerCase())));
  const jurisdictions = [...new Set(rows.map((r) => r.jurisdiction))];
  const owners = [...new Set(rows.map((r) => r.assignee).filter(Boolean))] as string[];
  return (
    <Panel title="Escalation register" meta={`${shown.length} shown`}>
      <div className="mb-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_auto_auto]">
        <label className="relative"><Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input className={`${inputClass} pl-9`} placeholder="Search escalation ID, topic, jurisdiction or owner…" value={query} onChange={(e) => setQuery(e.target.value)} /></label>
        <Button onClick={() => { setQuery(""); setSev(""); setState(""); setJur(""); setOwner(""); }}>Clear</Button>
        <label className="flex items-center gap-2 text-sm text-ink"><input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} /> Include closed</label>
      </div>
      <div className="mb-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <select aria-label="Severity" className={inputClass} value={sev} onChange={(e) => setSev(e.target.value)}><option value="">All severities</option>{["Critical", "High", "Medium", "Low"].map((s) => <option key={s}>{s}</option>)}</select>
        <select aria-label="Workflow state" className={inputClass} value={state} onChange={(e) => setState(e.target.value)}><option value="">All workflow states</option>{Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select>
        <select aria-label="Jurisdiction" className={inputClass} value={jur} onChange={(e) => setJur(e.target.value)}><option value="">All jurisdictions</option>{jurisdictions.map((j) => <option key={j}>{j}</option>)}</select>
        <select aria-label="Owner" className={inputClass} value={owner} onChange={(e) => setOwner(e.target.value)}><option value="">All assigned owners</option>{owners.map((o) => <option key={o}>{o}</option>)}</select>
      </div>
      <p className="mb-3 rounded-lg border border-accent/30 bg-accent/5 px-3 py-2 text-xs text-ink">⚖ Escalations are not support tickets. Closure requires an evidence-linked decision; a question with a review case is decided once, in Review Tasks.</p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[780px] text-left text-sm">
          <thead className="bg-soft text-xs text-muted"><tr>{["Escalation", "Exception / trigger", "Severity", "Scope", "Status", "Owner", "SLA", ""].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr></thead>
          <tbody>{shown.map((e) => (
            <tr key={e.id} onClick={() => onSelect(e.id)} aria-selected={selectedId === e.id} className={`cursor-pointer border-b border-line hover:bg-soft ${selectedId === e.id ? "bg-info/5" : ""}`}>
              <td className="px-3 py-2.5 font-semibold text-info">{e.id}</td>
              <td className="px-3 py-2.5"><b className="block max-w-xs truncate text-ink">{e.topic}</b><span className="text-xs text-muted">{e.trigger}</span></td>
              <td className="px-3 py-2.5"><Badge tone={SEV_TONE[e.severity]}>{e.severity}</Badge></td>
              <td className="px-3 py-2.5 text-ink">{e.jurisdiction}</td>
              <td className="px-3 py-2.5"><Badge tone={STATUS[e.status].tone}>{STATUS[e.status].label}</Badge></td>
              <td className="px-3 py-2.5 text-ink">{e.assignee ?? <span className="text-muted">Unassigned</span>}</td>
              <td className="px-3 py-2.5"><Badge tone={SLA[e.sla].tone}>{SLA[e.sla].label}</Badge></td>
              <td className="px-3 py-2.5 text-muted">⋯</td>
            </tr>))}</tbody>
        </table>
        {!shown.length && <EmptyState title={rows.length ? "No escalations in this view" : "No escalations yet"} />}
      </div>
      <p className="mt-3 text-xs text-muted">Policy-enforced routing · SLA targets: Critical 2h · High 4h · Medium 24h · Low 72h</p>
    </Panel>
  );
}

type DetailTab = "overview" | "evidence" | "decision" | "history";

function Detail({ e, people, selfId, onChanged }: { e: EscalationRow; people: ReviewPerson[]; selfId?: string; onChanged: () => void }) {
  const [tab, setTab] = useState<DetailTab>("overview");
  const [note, setNote] = useState("");
  const { busy, error, run } = useMutation();
  const open = isOpen(e);
  const act = (action: string, extra: { assignee_id?: string } = {}) =>
    run(action, (t) => actOnEscalationCase(t, e.id, { action, note, ...extra })).then((ok) => { if (ok) { setNote(""); onChanged(); } });
  const reviewOpen = e.reviewCase && ["open", "triaged", "needs_evidence"].includes(e.reviewCase.status);
  return (
    <Panel title={`Selected escalation · ${e.id}`} action={<Badge tone={SEV_TONE[e.severity]}>{e.severity}{e.status === "expert_review" ? " · Expert review" : ""}</Badge>}>
      <h3 className="-mt-1 text-lg font-extrabold text-ink">{e.topic}</h3>
      <p className="mb-3 text-xs text-muted">{e.trigger} · {e.jurisdiction}</p>
      <PillTabs label="Escalation detail" active={tab} onChange={setTab} tabs={[
        { key: "overview", label: "Overview" }, { key: "evidence", label: "Evidence & sources" },
        { key: "decision", label: "Resolution decision" }, { key: "history", label: "Audit history", count: e.history.length }]} />
      <div className="mt-4 space-y-4">
        {open && e.closureRestricted && (
          <div className="rounded-lg border border-bad/30 bg-bad/5 p-3">
            <p className="text-sm font-bold text-bad">⛔ Closure restricted · independent decision required</p>
            <p className="text-sm text-ink">{e.closureReason}.</p>
          </div>
        )}
        {tab === "overview" && (
          <>
            <DetailRows rows={[
              ["Risk level", e.severity], ["Current status", STATUS[e.status].label], ["Requester", e.requester ?? "—"],
              ["Jurisdiction", e.jurisdiction], ["Assigned owner", e.assignee ?? "Unassigned"],
              ["Required reviewer role", e.reviewerRole ?? "—"],
              ["Linked review case", e.reviewCase ? `${e.reviewCase.id.slice(0, 8)} · ${e.reviewCase.status}` : "None"],
              ["Response target", e.slaDeadline ? `${utcDate(e.slaDeadline)} · ${SLA[e.sla].label}` : "—"],
            ]} />
            <div><h4 className="mb-1 font-bold text-ink">Professional risk summary</h4><p className="whitespace-pre-line text-sm text-ink">{e.detail || "No further detail recorded."}</p></div>
            {open && <div><h4 className="mb-2 font-bold text-ink">Required next step</h4>
              <div className="flex flex-wrap gap-1.5">{e.nextSteps.map((s) => <span key={s} className="rounded-md border border-line px-2 py-1 text-xs font-semibold text-info">{s}</span>)}</div></div>}
          </>
        )}
        {tab === "evidence" && (
          <div className="space-y-2 text-sm text-ink">
            <p><b>Question:</b> {e.question}</p>
            <p><b>Routing reason:</b> {e.routeReason || "—"}</p>
            {e.queryId && !e.queryId.startsWith("manual:") && <Link href={`/audit-replay?correlation_id=${encodeURIComponent(e.queryId)}`} className="font-semibold text-info">Replay the full evidence trail →</Link>}
          </div>
        )}
        {tab === "decision" && (
          <DetailRows rows={[
            ["Decision", e.decision ?? "Not decided"], ["Decided by", e.decidedBy ?? "—"], ["Closed", e.resolvedAt ? utcDate(e.resolvedAt) : "—"],
            ["Where decided", reviewOpen ? "Review Tasks (pending)" : e.reviewCase ? "Review Tasks" : "Here"],
          ]} />
        )}
        {tab === "history" && (e.history.length ? (
          <ol className="space-y-2 border-l border-line pl-4 text-sm">{[...e.history].reverse().map((h, i) => (
            <li key={i}><b className="text-ink">{h.action.replace(/_/g, " ")}</b> <span className="text-xs text-muted">· {h.actor} · {utcDate(h.at)}</span>{h.note && <p className="text-ink">{h.note}</p>}</li>))}</ol>
        ) : <p className="text-sm text-muted">No actions recorded yet.</p>)}
        <ErrorNote message={error} />
        {open && (
          <div className="space-y-2 border-t border-line pt-3">
            <textarea className={`${inputClass} min-h-16 py-2`} placeholder="Note or decision reason" value={note} onChange={(ev) => setNote(ev.target.value)} />
            <div className="grid grid-cols-2 gap-2">
              {reviewOpen ? <Link href="/review-tasks" className="inline-flex min-h-10 items-center justify-center rounded-lg border border-accent bg-accent text-sm font-semibold text-white">Decide in Review Tasks</Link>
                : <Button variant="primary" disabled={e.requesterId === selfId} title={e.requesterId === selfId ? "Someone else must decide your escalation" : ""} busy={busy === "approve"} onClick={() => act("approve")}>Approve closure</Button>}
              <select aria-label="Assign expert" className={inputClass} value="" disabled={busy === "assign"} onChange={(ev) => ev.target.value && act("assign", { assignee_id: ev.target.value })}>
                <option value="">Assign expert…</option>{people.filter((p) => p.expert).map((p) => <option key={p.id} value={p.id}>{p.name} · {p.role}</option>)}
              </select>
              {e.status === "open" && <Button busy={busy === "start_review"} onClick={() => act("start_review")}>Start review</Button>}
              <Button busy={busy === "note"} onClick={() => act("note")}>Add note</Button>
              <Button busy={busy === "request_info"} onClick={() => act("request_info")}>Request info</Button>
              {e.status !== "escalated" && <Button busy={busy === "escalate"} onClick={() => act("escalate")}>Escalate</Button>}
              {!reviewOpen && <Button variant="danger" busy={busy === "refuse"} onClick={() => act("refuse")}>Refuse</Button>}
            </div>
          </div>
        )}
      </div>
    </Panel>
  );
}

function HoldsPanel({ data, onChanged }: { data: EscalationQueue; onChanged: () => void }) {
  const [form, setForm] = useState({ scope: "", reason: "", original_route: "HUMAN_REVIEW", new_route: "REFUSAL", duration_hours: 24 });
  const { busy, error, run } = useMutation();
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Panel title="Active governance holds" meta="Time-bounded safety overrides · max 72 hours">
        {data.overrides.length ? (
          <ul className="space-y-2 text-sm">{data.overrides.map((o) => (
            <li key={o.id} className="rounded-lg border border-line p-3"><b className="text-ink">{o.scope}</b> <span className="text-xs text-muted">{o.originalRoute} → {o.newRoute}</span>
              <p className="text-ink">{o.reason}</p><p className="text-xs text-muted">{o.actor} ({o.role}) · expires {o.expiresAt ? utcDate(o.expiresAt) : "—"}</p></li>))}</ul>
        ) : <p className="text-sm text-muted">No active holds.</p>}
      </Panel>
      <Panel title="Apply a governance hold" meta="Recorded with your identity and role">
        <form className="space-y-2" onSubmit={(ev) => { ev.preventDefault(); run("hold", () => createSafetyOverride(form)).then((ok) => ok && onChanged()); }}>
          <input required className={inputClass} placeholder="Scope pattern, e.g. topic:lease-classification" value={form.scope} onChange={(ev) => setForm({ ...form, scope: ev.target.value })} />
          <input required className={inputClass} placeholder="Reason" value={form.reason} onChange={(ev) => setForm({ ...form, reason: ev.target.value })} />
          <div className="grid grid-cols-3 gap-2">
            <select aria-label="From route" className={inputClass} value={form.original_route} onChange={(ev) => setForm({ ...form, original_route: ev.target.value })}>{["LLM", "HUMAN_REVIEW", "REFUSAL"].map((r) => <option key={r}>{r}</option>)}</select>
            <select aria-label="To route" className={inputClass} value={form.new_route} onChange={(ev) => setForm({ ...form, new_route: ev.target.value })}>{["HUMAN_REVIEW", "REFUSAL"].map((r) => <option key={r}>{r}</option>)}</select>
            <input aria-label="Hours" type="number" min={1} max={72} className={inputClass} value={form.duration_hours} onChange={(ev) => setForm({ ...form, duration_hours: Number(ev.target.value) })} />
          </div>
          <ErrorNote message={error} />
          <Button type="submit" variant="primary" busy={busy === "hold"}>Apply hold</Button>
        </form>
      </Panel>
    </div>
  );
}

function Bottom({ data, onSelect }: { data: EscalationQueue; onSelect: (id: string) => void }) {
  const s = data.summary;
  const total = Math.max(1, s.open);
  const events = data.escalations.flatMap((e) => e.history.map((h) => ({ ...h, id: e.id }))).sort((a, b) => b.at.localeCompare(a.at)).slice(0, 4);
  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <Panel title="Severity & ownership" meta={`${s.open} open records`}>
        <div className="space-y-3">
          {(["Critical", "High", "Medium", "Low"] as const).map((k) => <ProgressRow key={k} label={k} value={s.bySeverity[k] ?? 0} total={total} tone={k === "Critical" ? "bad" : k === "High" ? "warn" : k === "Medium" ? "info" : "ok"} right={s.bySeverity[k] ?? 0} />)}
          <p className="text-xs text-muted">{s.unassigned} open escalation(s) have no assigned expert.</p>
        </div>
      </Panel>
      <Panel title="Escalation control checks" meta="Live control state">
        <ul className="space-y-3 text-sm">
          <li className="flex gap-2"><span className="text-ok">✓</span><span><b className="text-ink">Risk triage</b><br /><span className="text-xs text-muted">Every escalation carries a classified risk level and SLA</span></span></li>
          <li className="flex gap-2"><span className={s.overdue ? "text-bad" : "text-ok"}>{s.overdue ? "!" : "✓"}</span><span><b className="text-ink">Response SLA</b><br /><span className="text-xs text-muted">{s.overdue ? `${s.overdue} overdue; owners must act` : "No breaches"}</span></span></li>
          <li className="flex gap-2"><span className="text-accent-ink">◷</span><span><b className="text-ink">Professional review holds</b><br /><span className="text-xs text-muted">{s.closureRestricted} awaiting an independent decision</span></span></li>
        </ul>
      </Panel>
      <Panel title="Recent escalation events" meta="Audited actions">
        {events.length ? (
          <ul className="space-y-2 text-sm">{events.map((h, i) => (
            <li key={i}><button onClick={() => onSelect(h.id)} className="text-left"><b className="text-ink hover:underline">{h.action.replace(/_/g, " ")}</b>
              <span className="block text-xs text-muted">{h.id} · {h.actor} · {utcDate(h.at)}</span></button></li>))}</ul>
        ) : <p className="text-sm text-muted">No actions yet.</p>}
      </Panel>
    </div>
  );
}

function CreateForm({ onDone }: { onDone: () => void }) {
  const [v, setV] = useState({ topic: "", detail: "", risk_level: "HIGH", jurisdiction: "GLOBAL" });
  const { busy, error, run } = useMutation();
  return (
    <Panel title="New escalation" meta="For an exception that needs an accountable expert decision" action={<Button onClick={onDone}>Cancel</Button>}>
      <form className="grid gap-3 md:grid-cols-3" onSubmit={(ev) => { ev.preventDefault(); run("c", (t) => raiseEscalation(t, v)).then((ok) => ok && onDone()); }}>
        <input required minLength={3} className={`${inputClass} md:col-span-2`} placeholder="Exception, e.g. Conflicting lease classification" value={v.topic} onChange={(ev) => setV({ ...v, topic: ev.target.value })} />
        <div className="grid grid-cols-2 gap-2">
          <select aria-label="Severity" className={inputClass} value={v.risk_level} onChange={(ev) => setV({ ...v, risk_level: ev.target.value })}>
            {[["RESTRICTED", "Critical"], ["HIGH", "High"], ["MEDIUM", "Medium"], ["LOW", "Low"]].map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
          <input className={inputClass} placeholder="Jurisdiction" value={v.jurisdiction} onChange={(ev) => setV({ ...v, jurisdiction: ev.target.value })} />
        </div>
        <textarea className={`${inputClass} min-h-20 py-2 md:col-span-3`} placeholder="What needs a decision, and the evidence so far" value={v.detail} onChange={(ev) => setV({ ...v, detail: ev.target.value })} />
        <div className="md:col-span-3"><ErrorNote message={error} /></div>
        <div><Button type="submit" variant="primary" busy={busy === "c"}>Raise escalation</Button></div>
      </form>
    </Panel>
  );
}
