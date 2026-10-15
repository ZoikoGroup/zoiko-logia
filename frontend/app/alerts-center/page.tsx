"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { AlertOctagon, BellRing, Columns3, Diamond, Hexagon, Search, Send, UserX } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { useLiveData } from "@/components/overview/useLiveData";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import { SeverityDonut } from "@/components/operations/charts";
import {
  Badge, Button, DetailRows, EmptyState, ErrorNote, KpiRow, KpiTile, OpsHero, Panel, PillTabs, ProgressRow, inputClass,
  timeAgo, useMutation, utcDate, utcTime,
} from "@/components/operations/ui";
import {
  actOnAlert, getAssignees, getOperationsAlerts, raiseAlert,
  type AlertAction, type AlertSeverity, type AlertState, type Assignee, type AlertsView, type OperationsAlert,
} from "@/lib/api";

type TabKey = "all" | "critical" | "unacknowledged" | "source" | "safety" | "operations" | "closed";
const TABS: { key: TabKey; label: string }[] = [
  { key: "all", label: "All Alerts" }, { key: "critical", label: "Critical" },
  { key: "unacknowledged", label: "Unacknowledged" }, { key: "source", label: "Source Governance" },
  { key: "safety", label: "AI Safety" }, { key: "operations", label: "Operations" }, { key: "closed", label: "Resolved & suppressed" },
];
const ACTIVE: AlertState[] = ["unacknowledged", "acknowledged", "investigating", "contained"];
const SEVERITY_TONE: Record<AlertSeverity, "bad" | "warn" | "info" | "ok"> = { Critical: "bad", High: "warn", Medium: "info", Low: "ok" };
const STATE_LABEL: Record<AlertState, { label: string; tone: "bad" | "warn" | "info" | "ok" | "neutral" }> = {
  unacknowledged: { label: "Unacknowledged", tone: "bad" }, acknowledged: { label: "Acknowledged", tone: "warn" },
  investigating: { label: "Investigating", tone: "info" }, contained: { label: "Contained", tone: "ok" },
  resolved: { label: "Resolved", tone: "neutral" }, suppressed: { label: "Suppressed", tone: "neutral" },
};
const ORIGIN = { governance: "Governance control", health: "Service health check", manual: "Raised by hand" };
const ACTION_LABEL: Record<string, string> = {
  detected: "Detected", raised: "Raised", acknowledge: "Acknowledged", investigate: "Investigation started",
  assign: "Owner assigned", escalate: "Escalated", contain: "Contained", resolve: "Resolved", suppress: "Suppressed",
  reopen: "Reopened", cleared: "Condition cleared", recurred: "Condition recurred",
};

function inTab(a: OperationsAlert, tab: TabKey): boolean {
  const active = ACTIVE.includes(a.state);
  switch (tab) {
    case "all": return active;
    case "critical": return active && a.severity === "Critical";
    case "unacknowledged": return a.state === "unacknowledged";
    case "source": return active && a.category === "Source governance";
    case "safety": return active && a.category === "AI safety";
    case "operations": return active && a.category === "Platform operations";
    case "closed": return !active;
  }
}

export default function AlertsCenterPage() {
  const { profile } = useAuth();
  const role = profile?.role ?? "";
  const canAct = Boolean(role) && role !== "System Auditor";
  const { data, error, loading, signedOut, reload } = useLiveData(
    "alerts-center", (token, signal, fresh) => getOperationsAlerts(token, signal, fresh), 45_000,
  );
  const people = useLiveData("ops-assignees", (token, signal) => getAssignees(token, signal), 20_000);
  const [tab, setTab] = useState<TabKey>("all");
  const [query, setQuery] = useState("");
  const [severity, setSeverity] = useState("");
  const [state, setState] = useState("");
  const [category, setCategory] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [raising, setRaising] = useState(false);

  const alerts = useMemo(() => data?.alerts ?? [], [data]);
  const rows = useMemo(() => alerts.filter((a) => inTab(a, tab)
    && (!severity || a.severity === severity) && (!state || a.state === state) && (!category || a.category === category)
    && (!query || `${a.ref} ${a.title} ${a.category} ${a.owner ?? ""}`.toLowerCase().includes(query.toLowerCase()))),
  [alerts, tab, severity, state, category, query]);
  const selected = alerts.find((a) => a.id === selectedId) ?? rows[0];
  const categories = [...new Set(alerts.map((a) => a.category))];

  return (
    <main className="flex-1 space-y-4 overflow-y-auto p-4">
      <OpsHero icon={Diamond} eyebrow="Operations / Alerts Center" title="Alerts Center"
        subtitle="Correlate, prioritize, and route risks across Kriton, accounting, sources, and platform services.">
        <p className="text-base font-bold text-white">Detect. Route. Contain.</p>
        <p className="text-white/80">Actionable alerts with accountable ownership, enforceable safeguards, and complete traceability.</p>
      </OpsHero>
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />
      {data && (
        <>
          <Kpis data={data} />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <PillTabs label="Alert views" tabs={TABS} active={tab} onChange={(t) => { setTab(t); setSelectedId(""); }} />
            {canAct && <Button variant="primary" onClick={() => setRaising(true)}>+ Raise alert</Button>}
          </div>
          {raising && <RaiseForm onDone={() => { setRaising(false); reload(); }} />}
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_440px]">
            <Panel title="Alert register" meta="Scope: this workspace · correlated conditions, not duplicate events">
              <div className="mb-3 grid gap-2 lg:grid-cols-[minmax(0,1.4fr)_repeat(3,minmax(0,1fr))_auto]">
                <label className="relative">
                  <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
                  <input className={`${inputClass} pl-9`} placeholder="Search by alert, owner or category…" value={query} onChange={(e) => setQuery(e.target.value)} />
                </label>
                <select aria-label="Severity" className={inputClass} value={severity} onChange={(e) => setSeverity(e.target.value)}>
                  <option value="">All severities</option>{["Critical", "High", "Medium", "Low"].map((s) => <option key={s}>{s}</option>)}
                </select>
                <select aria-label="Status" className={inputClass} value={state} onChange={(e) => setState(e.target.value)}>
                  <option value="">All statuses</option>{Object.entries(STATE_LABEL).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
                </select>
                <select aria-label="Category" className={inputClass} value={category} onChange={(e) => setCategory(e.target.value)}>
                  <option value="">All categories</option>{categories.map((c) => <option key={c}>{c}</option>)}
                </select>
                <Button onClick={() => { setQuery(""); setSeverity(""); setState(""); setCategory(""); }}>Clear</Button>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[760px] text-left text-sm">
                  <thead className="bg-soft text-xs uppercase text-muted">
                    <tr>{["Alert ID", "Alert / condition", "Category", "Severity", "State", "Owner", "Detected"].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr>
                  </thead>
                  <tbody>
                    {rows.map((a) => (
                      <tr key={a.id} onClick={() => setSelectedId(a.id)} aria-selected={selected?.id === a.id}
                        className={`cursor-pointer border-b border-line hover:bg-soft ${selected?.id === a.id ? "border-l-4 border-l-accent bg-accent/5" : ""}`}>
                        <td className="px-3 py-2.5 font-semibold text-info">{a.ref}</td>
                        <td className="px-3 py-2.5 font-semibold text-ink">{a.title}</td>
                        <td className="px-3 py-2.5 text-ink">{a.category}</td>
                        <td className="px-3 py-2.5"><Badge tone={SEVERITY_TONE[a.severity]}>{a.severity}</Badge></td>
                        <td className="px-3 py-2.5"><Badge tone={STATE_LABEL[a.state].tone}>{STATE_LABEL[a.state].label}</Badge></td>
                        <td className="px-3 py-2.5 text-ink">{a.owner ?? <span className="text-muted">Unassigned</span>}</td>
                        <td className="px-3 py-2.5 text-ink" title={utcDate(a.detectedAt)}>{utcTime(a.detectedAt)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!rows.length && (
                  <EmptyState icon={BellRing} title={alerts.some((a) => ACTIVE.includes(a.state)) || tab === "closed" ? "No alerts match this view" : "No active alerts in this workspace."}>
                    Alerts are raised automatically from governance exceptions and services that are down, and can be raised by hand.
                  </EmptyState>
                )}
              </div>
              <p className="mt-3 flex justify-between text-xs text-muted">
                <span>Showing {rows.length} of {alerts.length} alerts (last 30 days)</span>
                <span>Updated {utcTime(data.generatedAt)}</span>
              </p>
            </Panel>
            {selected
              ? <AlertDetail alert={selected} canAct={canAct} isAdmin={role === "Admin"} people={people.data ?? []} onChanged={reload} />
              : <Panel title="Alert investigation"><EmptyState title="Select an alert to investigate" /></Panel>}
          </div>
          <div className="grid gap-4 xl:grid-cols-3">
            <Panel title="Active Alerts by Severity"><SeverityDonut counts={data.summary.bySeverity} /></Panel>
            <Panel title="Alert Categories · Active Scope">
              {data.summary.byCategory.length ? (
                <div className="space-y-3">
                  {data.summary.byCategory.map((c) => (
                    <ProgressRow key={c.category} label={c.category} value={c.count} total={data.summary.active} tone="info" right={c.count} />
                  ))}
                  <p className="text-xs text-muted">Each alert has exactly one category.</p>
                </div>
              ) : <p className="text-sm text-muted">No active alerts.</p>}
            </Panel>
            <DeliveryPanel data={data} />
          </div>
        </>
      )}
    </main>
  );
}

function Kpis({ data }: { data: AlertsView }) {
  const s = data.summary;
  return (
    <KpiRow>
      <KpiTile icon={Columns3} value={s.active} label="Active Alerts" hint="All severities · this workspace" />
      <KpiTile icon={AlertOctagon} tone={s.critical ? "bad" : "ok"} value={s.critical} label="Critical Alerts"
        hint={s.critical ? "Need immediate attention" : "None open"} hintTone={s.critical ? "bad" : undefined} />
      <KpiTile icon={BellRing} tone={s.unacknowledged ? "warn" : "ok"} value={s.unacknowledged} label="Unacknowledged" hint="Awaiting accountable owner" />
      <KpiTile icon={UserX} tone={s.unowned ? "warn" : "ok"} value={s.unowned} label="Without owner" hint="Active alerts nobody owns" />
      <KpiTile icon={Send} tone="neutral" value={data.delivery.channelConfigured ? "On" : "In-app"} label="Delivery channel"
        hint={data.delivery.channelConfigured ? data.delivery.channel : "No email or pager channel connected"} />
      <KpiTile icon={Hexagon} tone={s.safetyBlocks ? "warn" : "ok"} value={s.safetyBlocks} label="Active Safety Blocks" hint="Emergency blocks in force" />
    </KpiRow>
  );
}

type DetailTab = "overview" | "evidence" | "routing" | "timeline";

function nextAction(a: OperationsAlert): string {
  switch (a.state) {
    case "unacknowledged": return "Acknowledge the alert and confirm an accountable owner.";
    case "acknowledged": return "Start the investigation and identify the cause.";
    case "investigating": return a.origin === "manual" ? "Contain the issue, then have a second person approve the resolution."
      : "Contain the issue; the alert resolves itself once the condition clears.";
    case "contained": return a.origin === "manual" ? "A second person approves the resolution." : "Fix the cause; the alert resolves when the condition clears.";
    case "suppressed": return "Suppressed by an Admin. Reopen it if the condition still needs attention.";
    case "resolved": return "No action needed. It reopens automatically if the condition recurs.";
  }
}

function AlertDetail({ alert: a, canAct, isAdmin, people, onChanged }: {
  alert: OperationsAlert; canAct: boolean; isAdmin: boolean; people: Assignee[]; onChanged: () => void;
}) {
  const [tab, setTab] = useState<DetailTab>("overview");
  const [note, setNote] = useState("");
  const { busy, error, run } = useMutation();
  const active = ACTIVE.includes(a.state);
  const act = (action: AlertAction, extra: { owner_user_id?: string } = {}) =>
    run(action, (t) => actOnAlert(t, a.id, { action, note, ...extra })).then((ok) => { if (ok) { setNote(""); onChanged(); } });

  return (
    <Panel title="Alert investigation" action={<Badge tone={SEVERITY_TONE[a.severity]}>{a.severity}</Badge>}>
      <p className="-mt-2 text-xs font-bold text-info">{a.ref}</p>
      <h3 className="mb-3 text-lg font-extrabold text-ink">{a.title}</h3>
      <PillTabs label="Alert detail" active={tab} onChange={setTab} tabs={[
        { key: "overview", label: "Overview" }, { key: "evidence", label: "Evidence" },
        { key: "routing", label: "Routing & Delivery" }, { key: "timeline", label: "Timeline", count: a.history.length },
      ]} />
      <div className="mt-4 space-y-4">
        {tab === "overview" && (
          <>
            <DetailRows rows={[
              ["State", STATE_LABEL[a.state].label],
              ["Acknowledged", a.acknowledgedAt ? `Yes · ${a.acknowledgedBy ?? ""} · ${timeAgo(a.acknowledgedAt)}` : "No / not confirmed"],
              ["Category", a.category], ["Detected", utcDate(a.detectedAt)], ["Source", ORIGIN[a.origin]],
              ["Assigned owner", a.owner ?? "Unassigned"], ["Last seen", `${utcDate(a.lastSeenAt)}`],
              ...(a.resolvedAt ? [["Resolved", `${utcDate(a.resolvedAt)} · ${a.resolvedBy ?? ""}`] as [string, string]] : []),
            ]} />
            <div>
              <h4 className="mb-1 font-bold text-ink">Detected condition</h4>
              <p className="text-sm text-ink">{a.detail || a.title}</p>
            </div>
            {a.origin !== "manual" && (
              <p className="rounded-lg border border-ok/30 bg-ok/5 p-3 text-sm text-ink">
                <b className="text-ok">Automated control status</b><br />
                This alert follows its live condition: it resolves when the condition clears and reopens if it recurs.
              </p>
            )}
            <div><h4 className="mb-1 font-bold text-ink">Next required action</h4><p className="text-sm text-ink">{nextAction(a)}</p></div>
          </>
        )}
        {tab === "evidence" && (
          <div className="space-y-3 text-sm text-ink">
            <p>{a.detail || "No further detail was recorded with this alert."}</p>
            {a.href && <Link href={a.href} className="font-semibold text-info">Open the source page →</Link>}
            <p className="text-xs text-muted">Every action on this alert is also written to the audit ledger.</p>
          </div>
        )}
        {tab === "routing" && (
          <DetailRows rows={[
            ["Owner", a.owner ?? "Unassigned"], ["Delivered to", "In-app (this console)"],
            ["Notification channel", "None connected (email, Slack, pager)"],
            ["Escalation", a.history.some((h) => h.action === "escalate") ? `Escalated to ${a.severity}` : "Not escalated"],
          ]} />
        )}
        {tab === "timeline" && (
          <ol className="space-y-3 border-l border-line pl-4 text-sm">
            {[...a.history].reverse().map((h, i) => (
              <li key={`${h.at}-${i}`}>
                <p className="font-semibold text-ink">{ACTION_LABEL[h.action] ?? h.action} <span className="font-normal text-muted">· {h.actor}</span></p>
                <p className="text-xs text-muted">{utcDate(h.at)}</p>
                {h.note && <p className="text-ink">{h.note}</p>}
              </li>
            ))}
          </ol>
        )}
      </div>
      {canAct && (
        <div className="mt-4 space-y-2 border-t border-line pt-4">
          <textarea className={`${inputClass} min-h-16 py-2`} placeholder="Note (required to contain, resolve or suppress)" value={note} onChange={(e) => setNote(e.target.value)} />
          <ErrorNote message={error} />
          <div className="grid grid-cols-2 gap-2">
            {a.state === "unacknowledged" && <Button busy={busy === "acknowledge"} onClick={() => act("acknowledge")}>Acknowledge</Button>}
            {(a.state === "acknowledged" || a.state === "unacknowledged") && <Button busy={busy === "investigate"} onClick={() => act("investigate")}>Investigate</Button>}
            {(a.state === "acknowledged" || a.state === "investigating") && <Button busy={busy === "contain"} onClick={() => act("contain")}>Mark contained</Button>}
            <select aria-label="Assign owner" className={inputClass} value="" disabled={busy === "assign"}
              onChange={(e) => e.target.value && act("assign", { owner_user_id: e.target.value })}>
              <option value="">Assign owner…</option>
              {people.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.role}</option>)}
            </select>
            <Link href="/audit-replay" className="inline-flex min-h-10 items-center justify-center rounded-lg border border-line bg-panel text-sm font-semibold text-info hover:bg-soft">Audit Replay</Link>
            {active && a.severity !== "Critical" && <Button busy={busy === "escalate"} onClick={() => act("escalate")}>Escalate</Button>}
            {active && <Button variant="danger" disabled={!isAdmin} busy={busy === "suppress"} onClick={() => act("suppress")}
              title={isAdmin ? "Requires a reason" : "Only an Admin can suppress an alert"}>Suppress — restricted</Button>}
            {active && a.origin === "manual" && <Button variant="primary" busy={busy === "resolve"} onClick={() => act("resolve")}
              title="Must be someone other than the person who raised it">Approve resolution</Button>}
            {!active && <Button busy={busy === "reopen"} onClick={() => act("reopen")}>Reopen</Button>}
          </div>
        </div>
      )}
    </Panel>
  );
}

function DeliveryPanel({ data }: { data: AlertsView }) {
  const active = data.alerts.filter((a) => ACTIVE.includes(a.state));
  const owned = active.filter((a) => a.owner).length;
  const acked = active.filter((a) => a.state !== "unacknowledged").length;
  const suppressed = data.alerts.filter((a) => a.state === "suppressed").length;
  return (
    <Panel title="Alert Delivery Assurance">
      <ul className="divide-y divide-line text-sm">
        <li className="flex justify-between py-2"><span className="text-ink">Delivery channel</span><span className="font-bold text-ink">{data.delivery.channel}</span></li>
        <li className="flex justify-between py-2"><span className="text-ink">Owners confirmed</span><span className={`font-bold ${owned === active.length ? "text-ok" : "text-accent-ink"}`}>{owned} / {active.length}</span></li>
        <li className="flex justify-between py-2"><span className="text-ink">Acknowledged</span><span className={`font-bold ${acked === active.length ? "text-ok" : "text-accent-ink"}`}>{acked} / {active.length}</span></li>
        <li className="flex justify-between py-2"><span className="text-ink">External notification</span><span className="font-bold text-accent-ink">Not connected</span></li>
        <li className="flex justify-between py-2"><span className="text-ink">Suppression review</span><span className="font-bold text-ink">{suppressed} suppressed</span></li>
      </ul>
      <p className="mt-2 text-xs text-muted">Alerts stay enforceable here even with no external channel connected.</p>
    </Panel>
  );
}

function RaiseForm({ onDone }: { onDone: () => void }) {
  const [title, setTitle] = useState("");
  const [severity, setSeverity] = useState<AlertSeverity>("High");
  const [category, setCategory] = useState("Platform operations");
  const [detail, setDetail] = useState("");
  const { busy, error, run } = useMutation();
  return (
    <Panel title="Raise an alert" meta="A second person must approve its resolution" action={<Button onClick={onDone}>Cancel</Button>}>
      <form className="grid gap-3 md:grid-cols-3" onSubmit={(e) => {
        e.preventDefault();
        run("raise", (t) => raiseAlert(t, { title, severity, category, detail })).then((ok) => ok && onDone());
      }}>
        <input required minLength={3} className={inputClass} placeholder="What is wrong?" value={title} onChange={(e) => setTitle(e.target.value)} />
        <select aria-label="Severity" className={inputClass} value={severity} onChange={(e) => setSeverity(e.target.value as AlertSeverity)}>
          {["Critical", "High", "Medium", "Low"].map((s) => <option key={s}>{s}</option>)}
        </select>
        <select aria-label="Category" className={inputClass} value={category} onChange={(e) => setCategory(e.target.value)}>
          {["Platform operations", "AI safety", "Source governance", "AI governance", "Security & incidents", "Compliance", "Evidence"].map((c) => <option key={c}>{c}</option>)}
        </select>
        <textarea className={`${inputClass} min-h-20 py-2 md:col-span-3`} placeholder="Detail (optional)" value={detail} onChange={(e) => setDetail(e.target.value)} />
        <div className="md:col-span-3"><ErrorNote message={error} /></div>
        <div><Button type="submit" variant="primary" busy={busy === "raise"}>Raise alert</Button></div>
      </form>
    </Panel>
  );
}
