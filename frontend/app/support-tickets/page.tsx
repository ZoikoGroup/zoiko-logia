"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Clock3, Hourglass, Inbox, LifeBuoy, Search, ShieldAlert } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { useLiveData } from "@/components/overview/useLiveData";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import {
  Badge, Breadcrumb, Button, DetailRows, EmptyState, ErrorNote, KpiTile, OpsHero, Panel, PillTabs, ProgressRow,
  humanize, inputClass, timeAgo, useMutation, utcDate,
} from "@/components/operations/ui";
import {
  actOnTicket, createSupportTicket, getReviewPeople, getTicketRegister,
  type ReviewPerson, type SupportTicketRow, type TicketRegister,
} from "@/lib/api";

type TabKey = "all" | "mine" | "at_risk" | "waiting" | "escalated" | "resolved" | "analytics";
const PRIORITY_TONE = { P1: "bad", P2: "warn", P3: "info", P4: "neutral" } as const;
const STATUS: Record<SupportTicketRow["status"], { label: string; tone: "bad" | "warn" | "info" | "ok" | "neutral" }> = {
  open: { label: "Open", tone: "bad" }, in_progress: { label: "In progress", tone: "info" },
  investigating: { label: "Investigating", tone: "info" }, waiting_customer: { label: "Waiting customer", tone: "warn" },
  escalated: { label: "Escalated", tone: "warn" }, resolved: { label: "Resolved", tone: "ok" },
};

function slaText(t: SupportTicketRow): { text: string; tone: "bad" | "warn" | "ok" | "neutral" | "info" } {
  const s = t.sla;
  if (s.state === "paused") return { text: "Paused", tone: "neutral" };
  if (s.state === "met") return { text: "Met", tone: "ok" };
  if (s.state === "breached") return { text: t.status === "resolved" ? "Missed" : "Breached", tone: "bad" };
  const m = Math.max(0, Math.round(s.remainingSeconds / 60));
  const text = m >= 60 ? `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m` : `${m}m`;
  return { text, tone: s.state === "at_risk" ? "bad" : "info" };
}

function nextStep(t: SupportTicketRow): string {
  if (!t.ownerId) return "Assign an owner.";
  if (!t.firstResponseAt) return "Send the first response to the requester.";
  if (t.status === "waiting_customer") return "Waiting on the requester; the SLA clock is paused.";
  if (t.status === "escalated") return `Expert decision pending in the Escalation Queue (${t.escalationId}).`;
  if (t.status === "resolved") return "Resolved. Reopen if the requester reports it again.";
  return "Investigate, then resolve with a documented answer.";
}

export default function SupportTicketsPage() {
  const { profile } = useAuth();
  const { data, error, loading, signedOut, reload } = useLiveData(
    "support-tickets", (token, signal) => getTicketRegister(token, signal), 30_000,
  );
  const people = useLiveData("review-people", (token, signal) => getReviewPeople(token, signal), 20_000);
  const [tab, setTab] = useState<TabKey>("all");
  const [selectedId, setSelectedId] = useState("");
  const [creating, setCreating] = useState(false);
  const rows = useMemo(() => data?.tickets ?? [], [data]);
  const selected = rows.find((r) => r.id === selectedId) ?? rows.find((r) => r.status !== "resolved") ?? rows[0];

  return (
    <main className="flex-1 space-y-4 overflow-y-auto p-4">
      <Breadcrumb section="Review, Escalation & Audit" page="Support Tickets" />
      <OpsHero icon={LifeBuoy} title="Support Tickets"
        subtitle="Resolve customer requests with accountability, privacy, and measurable service quality · Customer support · Platform guidance · Controlled escalation">
        <p>Customer-first assistance</p><p>Strict tenant privacy</p><p>Evidence-backed resolutions</p><p>Auditable service operations</p>
      </OpsHero>
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />
      {data && (
        <>
          <Kpis data={data} />
          <section className="flex flex-col gap-2 rounded-xl border border-accent/40 bg-accent/5 p-3 text-sm text-ink sm:flex-row sm:items-center sm:justify-between">
            <span>◇ <b>Privacy boundary enforced:</b> support sees ticket details and what the requester wrote. Tenant records require a separately approved, time-limited break-glass grant.</span>
            <Link href="/break-glass" className="inline-flex min-h-9 shrink-0 items-center rounded-lg border border-line bg-panel px-3 text-sm font-semibold text-info hover:bg-soft">View access policy ↗</Link>
          </section>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <PillTabs label="Ticket views" active={tab} onChange={setTab} tabs={[
              { key: "all", label: "All Tickets" }, { key: "mine", label: "Assigned to Me" },
              { key: "at_risk", label: "SLA at Risk", count: data.summary.atRisk }, { key: "waiting", label: "Waiting on Customer", count: data.summary.waitingCustomer },
              { key: "escalated", label: "Escalated", count: data.summary.escalated }, { key: "resolved", label: "Resolved" }, { key: "analytics", label: "SLA Analytics" }]} />
            <Button variant="primary" onClick={() => setCreating(true)}>+ New Support Ticket</Button>
          </div>
          {creating && <CreateForm data={data} onDone={() => { setCreating(false); reload(); }} />}
          {tab === "analytics" ? <Analytics data={data} /> : (
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_440px]">
              <Register rows={rows} tab={tab} data={data} selfId={profile?.id} selectedId={selected?.id} onSelect={setSelectedId} />
              {selected ? <Detail key={selected.id} t={selected} people={people.data ?? []} onChanged={reload} />
                : <Panel title="Ticket"><EmptyState icon={Inbox} title="No support tickets yet">Requests raised by people using the platform appear here with their SLA clock.</EmptyState></Panel>}
            </div>
          )}
          <Bottom data={data} onSelect={setSelectedId} />
        </>
      )}
    </main>
  );
}

function Kpis({ data }: { data: TicketRegister }) {
  const s = data.summary;
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <KpiTile icon={Inbox} value={s.open} label="Open support tickets" hint={`${s.unassigned} without an owner`} />
      <KpiTile icon={Clock3} tone={s.atRisk ? "warn" : "ok"} value={s.atRisk} label="SLA deadlines at risk" hint="Requires proactive triage" />
      <KpiTile icon={AlertTriangle} tone={s.breaches ? "bad" : "ok"} value={s.breaches} label="SLA breaches" hint="Escalation owner required" hintTone={s.breaches ? "bad" : undefined} />
      <KpiTile icon={Hourglass} tone="info" value={s.waitingCustomer} label="Awaiting customers" hint="Response clock paused by policy" />
      <KpiTile icon={CheckCircle2} tone="ok" value={s.firstResponsePct === null ? "—" : `${s.firstResponsePct}%`} label="First-response SLA met" hint="Last 30 days" />
    </div>
  );
}

function Register({ rows, tab, data, selfId, selectedId, onSelect }: {
  rows: SupportTicketRow[]; tab: TabKey; data: TicketRegister; selfId?: string; selectedId?: string; onSelect: (id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [prio, setPrio] = useState("");
  const [cat, setCat] = useState("");
  const [state, setState] = useState("");
  const shown = rows.filter((t) => (tab !== "mine" || t.ownerId === selfId) && (tab !== "at_risk" || t.sla.state === "at_risk" || t.sla.state === "breached" && t.status !== "resolved")
    && (tab !== "waiting" || t.status === "waiting_customer") && (tab !== "escalated" || t.status === "escalated")
    && (tab !== "resolved" || t.status === "resolved") && (tab !== "all" || true)
    && (!prio || t.priority === prio) && (!cat || t.category === cat) && (!state || t.status === state)
    && (!query || `${t.ref} ${t.subject} ${t.requester} ${t.category}`.toLowerCase().includes(query.toLowerCase())));
  return (
    <Panel title="Ticket register" meta={`${shown.length} shown`}>
      <div className="mb-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_auto]">
        <label className="relative"><Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input className={`${inputClass} pl-9`} placeholder="Search ticket ID, issue, requester or topic…" value={query} onChange={(e) => setQuery(e.target.value)} /></label>
        <Button onClick={() => { setQuery(""); setPrio(""); setCat(""); setState(""); }}>Clear filters</Button>
      </div>
      <div className="mb-3 grid gap-2 sm:grid-cols-3">
        <select aria-label="Priority" className={inputClass} value={prio} onChange={(e) => setPrio(e.target.value)}><option value="">All priorities</option>{data.policy.map((p) => <option key={p.priority} value={p.priority}>{p.priority} · {p.label}</option>)}</select>
        <select aria-label="Category" className={inputClass} value={cat} onChange={(e) => setCat(e.target.value)}><option value="">All categories</option>{data.categories.map((c) => <option key={c} value={c}>{humanize(c)}</option>)}</select>
        <select aria-label="Status" className={inputClass} value={state} onChange={(e) => setState(e.target.value)}><option value="">All statuses</option>{Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-left text-sm">
          <thead className="bg-soft text-xs text-muted"><tr>{["Ticket ID", "Subject", "Category", "Priority", "Status", "SLA", "Owner"].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr></thead>
          <tbody>{shown.map((t) => {
            const s = slaText(t);
            return (
              <tr key={t.id} onClick={() => onSelect(t.id)} aria-selected={selectedId === t.id} className={`cursor-pointer border-b border-line hover:bg-soft ${selectedId === t.id ? "bg-info/5" : ""}`}>
                <td className="px-3 py-2.5 font-semibold text-info">{t.ref}</td>
                <td className="px-3 py-2.5 font-semibold text-ink">{t.subject}</td>
                <td className="px-3 py-2.5 text-ink">{humanize(t.category)}</td>
                <td className="px-3 py-2.5"><Badge tone={PRIORITY_TONE[t.priority]}>{t.priority} · {t.priorityLabel}</Badge></td>
                <td className="px-3 py-2.5"><Badge tone={STATUS[t.status].tone}>{STATUS[t.status].label}</Badge></td>
                <td className="px-3 py-2.5"><Badge tone={s.tone}>{s.text}</Badge></td>
                <td className="px-3 py-2.5 text-ink">{t.owner ?? <span className="text-muted">Unassigned</span>}</td>
              </tr>);
          })}</tbody>
        </table>
        {!shown.length && <EmptyState title={rows.length ? "No tickets in this view" : "No support tickets yet"} />}
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <p className="rounded-lg border border-line p-3 text-xs text-muted"><b className="text-ink">↗ Specialized handoffs</b><br />Accounting judgments → Escalation Queue (independent professional review). Source eligibility → source governance.</p>
        <p className="rounded-lg border border-line p-3 text-xs text-muted"><b className="text-ink">◇ Privacy & security triage</b><br />Suspected unauthorized access → Incident Response. Ticket ownership never grants tenant data access.</p>
      </div>
    </Panel>
  );
}

type DetailTab = "overview" | "conversation" | "access" | "timeline";

function Detail({ t, people, onChanged }: { t: SupportTicketRow; people: ReviewPerson[]; onChanged: () => void }) {
  const [tab, setTab] = useState<DetailTab>("overview");
  const [body, setBody] = useState("");
  const { busy, error, run } = useMutation();
  const s = slaText(t);
  const closed = t.status === "resolved";
  const act = (action: string, extra: { owner_id?: string; status?: string } = {}) =>
    run(action, (tok) => actOnTicket(tok, t.id, { action, body, ...extra })).then((ok) => { if (ok) { setBody(""); onChanged(); } });
  return (
    <Panel title={t.ref} action={<Badge tone={STATUS[t.status].tone}>{STATUS[t.status].label}</Badge>}>
      <h3 className="-mt-1 text-lg font-extrabold text-ink">{t.subject}</h3>
      <div className="mb-3 mt-1 flex flex-wrap gap-1.5">
        <Badge tone={PRIORITY_TONE[t.priority]}>{t.priority} · {t.priorityLabel}</Badge>
        <Badge tone={s.tone}>SLA: {s.text}</Badge>
        <Badge tone="info">{humanize(t.category)}</Badge>
      </div>
      <PillTabs label="Ticket detail" active={tab} onChange={setTab} tabs={[
        { key: "overview", label: "Overview" }, { key: "conversation", label: "Conversation", count: t.messages.filter((m) => m.kind !== "system").length },
        { key: "access", label: "Access & Privacy" }, { key: "timeline", label: "Timeline" }]} />
      <div className="mt-4 space-y-4">
        {tab === "overview" && (
          <>
            <DetailRows rows={[
              ["Requester", t.requester || "—"], ["Category", humanize(t.category)], ["Jurisdiction", t.jurisdiction || "—"],
              ["Assigned owner", t.owner ?? "Unassigned"], ["Created", t.createdAt ? utcDate(t.createdAt) : "—"],
              ["First response", t.firstResponseAt ? utcDate(t.firstResponseAt) : `Due ${utcDate(t.sla.firstResponseDueAt)}`],
              ["Resolution target", `${utcDate(t.sla.dueAt)} (${t.sla.targetHours}h)`],
              ["Linked", [t.escalationId && `Escalation ${t.escalationId}`, t.incidentId && `Incident ${t.incidentId}`].filter(Boolean).join(" · ") || "None"],
            ]} />
            <div><h4 className="mb-1 font-bold text-ink">Issue summary</h4><p className="whitespace-pre-line rounded-lg border border-line bg-soft p-3 text-sm text-ink">{t.description || "No description provided."}</p></div>
            <p className="rounded-lg border border-accent/40 bg-accent/5 p-3 text-xs text-ink"><b className="text-accent-ink">⚠ Tenant records are not available to support.</b> An approved, time-limited break-glass grant is required before any customer content can be inspected.</p>
            <div><h4 className="mb-1 font-bold text-ink">Next required step</h4><p className="rounded-lg border border-line p-3 text-sm text-ink">{nextStep(t)}</p></div>
            {t.resolutionNote && <p className="text-sm text-ink"><b>Resolution:</b> {t.resolutionNote}</p>}
          </>
        )}
        {tab === "conversation" && (t.messages.filter((m) => m.kind !== "system").length ? (
          <ul className="space-y-2">{t.messages.filter((m) => m.kind !== "system").map((m, i) => (
            <li key={i} className={`rounded-lg border p-2.5 text-sm ${m.kind === "note" ? "border-accent/30 bg-accent/5" : m.kind === "customer" ? "border-line bg-soft" : "border-info/30 bg-info/5"}`}>
              <p className="text-xs text-muted">{m.kind === "note" ? "Internal note" : m.kind === "customer" ? "Requester" : "Response"} · {m.actor} · {timeAgo(m.at)}</p>
              <p className="whitespace-pre-line text-ink">{m.body}</p></li>))}</ul>
        ) : <p className="text-sm text-muted">No messages yet.</p>)}
        {tab === "access" && (
          <DetailRows rows={[
            ["Access scope", "Ticket details only"], ["Tenant records", "Not visible to support"],
            ["How to inspect content", "Request a break-glass grant (another Admin approves)"],
            ["Linked question", t.queryId ?? "None"],
          ]} />
        )}
        {tab === "timeline" && (
          <ol className="space-y-2 border-l border-line pl-4 text-sm">{[...t.messages].reverse().map((m, i) => (
            <li key={i}><b className="text-ink">{m.kind === "system" ? m.body : m.kind === "note" ? "Internal note" : m.kind === "customer" ? "Requester update" : "Response sent"}</b>
              <span className="block text-xs text-muted">{m.actor} · {utcDate(m.at)}</span></li>))}</ol>
        )}
        <ErrorNote message={error} />
        <div className="space-y-2 border-t border-line pt-3">
          <h4 className="font-bold text-ink">Governed support actions</h4>
          <textarea className={`${inputClass} min-h-16 py-2`} placeholder={closed ? "Reason to reopen (optional)" : "Response, note, escalation reason or resolution"} value={body} onChange={(e) => setBody(e.target.value)} />
          <div className="grid grid-cols-2 gap-2">
            {!closed && <Button variant="primary" busy={busy === "reply"} onClick={() => act("reply")}>✎ Send response</Button>}
            {!closed && <select aria-label="Assign or reassign" className={inputClass} value="" disabled={busy === "assign"} onChange={(e) => e.target.value && act("assign", { owner_id: e.target.value })}>
              <option value="">Assign / Reassign…</option>{people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>}
            {!closed && <Link href="/break-glass" className="inline-flex min-h-10 items-center justify-center rounded-lg border border-line bg-panel text-sm font-semibold text-info hover:bg-soft">Request support access</Link>}
            {!closed && !t.escalationId && <Button busy={busy === "escalate"} onClick={() => act("escalate")}>↗ Escalate case</Button>}
            {!closed && !t.incidentId && <Button busy={busy === "raise_incident"} onClick={() => act("raise_incident")}>Raise incident</Button>}
            {!closed && <select aria-label="Status" className={inputClass} value="" disabled={busy === "status"} onChange={(e) => e.target.value && act("status", { status: e.target.value })}>
              <option value="">Set status…</option><option value="in_progress">In progress</option><option value="investigating">Investigating</option><option value="waiting_customer">Waiting on customer</option></select>}
            {t.status === "waiting_customer" && <Button busy={busy === "customer_update"} onClick={() => act("customer_update")}>Log requester reply</Button>}
            <Button busy={busy === "note"} onClick={() => act("note")}>✎ Internal note</Button>
            {!closed ? <Button variant="primary" busy={busy === "resolve"} onClick={() => act("resolve")}>✓ Resolve</Button>
              : <Button busy={busy === "reopen"} onClick={() => act("reopen")}>Reopen</Button>}
          </div>
        </div>
      </div>
    </Panel>
  );
}

function Analytics({ data }: { data: TicketRegister }) {
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Panel title="SLA policy" meta="Targets per priority · clock paused while waiting on the requester">
        <table className="w-full text-left text-sm">
          <thead className="bg-soft text-xs text-muted"><tr><th className="px-3 py-2">Priority</th><th className="px-3 py-2">First response</th><th className="px-3 py-2">Resolution</th></tr></thead>
          <tbody>{data.policy.map((p) => <tr key={p.priority} className="border-b border-line"><td className="px-3 py-2 font-semibold text-ink">{p.priority} · {p.label}</td><td className="px-3 py-2 text-ink">{p.firstResponseHours}h</td><td className="px-3 py-2 text-ink">{p.resolutionHours}h</td></tr>)}</tbody>
        </table>
      </Panel>
      <Performance data={data} />
    </div>
  );
}

function Performance({ data }: { data: TicketRegister }) {
  const s = data.summary;
  return (
    <Panel title="Service-level performance" meta="Last 30 days">
      <div className="flex justify-between">
        <div><p className="text-3xl font-extrabold text-ok">{s.firstResponsePct === null ? "—" : `${s.firstResponsePct}%`}</p><p className="text-xs text-muted">First response within SLA</p></div>
        <div className="text-right"><p className="text-3xl font-extrabold text-accent-ink">{s.resolutionPct === null ? "—" : `${s.resolutionPct}%`}</p><p className="text-xs text-muted">Resolution within SLA</p></div>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-soft"><div className="h-full rounded-full bg-ok" style={{ width: `${s.firstResponsePct ?? 0}%` }} /></div>
      <p className="mt-2 text-xs text-muted">{s.firstResponsePct === null ? "No tickets with a first-response result in the last 30 days." : "Measured from each ticket's own clock."}</p>
    </Panel>
  );
}

function Bottom({ data, onSelect }: { data: TicketRegister; onSelect: (id: string) => void }) {
  const s = data.summary;
  const total = Math.max(1, s.open);
  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <Panel title="Ticket health & priority">
        <div className="space-y-3">
          {data.policy.map((p) => <ProgressRow key={p.priority} label={`${p.label} / ${p.priority}`} value={s.byPriority[p.priority] ?? 0} total={total}
            tone={p.priority === "P1" ? "bad" : p.priority === "P2" ? "warn" : "info"} right={s.byPriority[p.priority] ?? 0} />)}
          <p className="flex justify-between text-xs"><span className="text-muted">{s.open} open</span>{s.atRisk > 0 && <b className="text-accent-ink">{s.atRisk} approaching SLA limits</b>}</p>
        </div>
      </Panel>
      <Performance data={data} />
      <Panel title="Recent service activity">
        {data.activity.length ? (
          <ul className="space-y-2.5 text-sm">{data.activity.slice(0, 5).map((a, i) => (
            <li key={i} className="flex justify-between gap-2"><button onClick={() => onSelect(a.ticketId)} className="text-left">
              <b className="block text-ink hover:underline">{a.kind === "system" ? a.body : a.kind === "note" ? "Internal note added" : a.kind === "customer" ? "Requester update" : "Response sent"}</b>
              <span className="text-xs text-muted">{a.ref} · {a.actor}</span></button><span className="shrink-0 text-xs text-muted">{timeAgo(a.at)}</span></li>))}</ul>
        ) : <p className="text-sm text-muted">No activity yet.</p>}
        <p className="mt-3 flex items-center gap-1.5 text-xs text-muted"><ShieldAlert size={12} /> Every action is written to the audit ledger.</p>
      </Panel>
    </div>
  );
}

function CreateForm({ data, onDone }: { data: TicketRegister; onDone: () => void }) {
  const [v, setV] = useState({ subject: "", description: "", category: data.categories[0], priority: "P3", jurisdiction: "" });
  const { busy, error, run } = useMutation();
  return (
    <Panel title="New support ticket" meta="The SLA clock starts when it is created" action={<Button onClick={onDone}>Cancel</Button>}>
      <form className="grid gap-3 md:grid-cols-4" onSubmit={(e) => { e.preventDefault(); run("c", (t) => createSupportTicket(t, v)).then((ok) => ok && onDone()); }}>
        <input required minLength={3} className={`${inputClass} md:col-span-2`} placeholder="Subject" value={v.subject} onChange={(e) => setV({ ...v, subject: e.target.value })} aria-label="Subject" />
        <select aria-label="Category" className={inputClass} value={v.category} onChange={(e) => setV({ ...v, category: e.target.value })}>{data.categories.map((c) => <option key={c} value={c}>{humanize(c)}</option>)}</select>
        <select aria-label="Priority" className={inputClass} value={v.priority} onChange={(e) => setV({ ...v, priority: e.target.value })}>{data.policy.map((p) => <option key={p.priority} value={p.priority}>{p.priority} · {p.label}</option>)}</select>
        <textarea required className={`${inputClass} min-h-20 py-2 md:col-span-3`} placeholder="What happened? Leave out confidential client data." value={v.description} onChange={(e) => setV({ ...v, description: e.target.value })} aria-label="Description" />
        <input className={inputClass} placeholder="Jurisdiction (optional)" value={v.jurisdiction} onChange={(e) => setV({ ...v, jurisdiction: e.target.value })} aria-label="Jurisdiction" />
        <div className="md:col-span-4"><ErrorNote message={error} /></div>
        <div><Button type="submit" variant="primary" busy={busy === "c"}>Create ticket</Button></div>
      </form>
    </Panel>
  );
}
