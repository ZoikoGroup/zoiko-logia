"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Ban, ClipboardList, Clock3, Hourglass, Radio, Search, ShieldAlert, Siren } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { useLiveData } from "@/components/overview/useLiveData";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import {
  Avatar, Badge, Breadcrumb, Button, DetailRows, EmptyState, ErrorNote, KpiTile, OpsHero, Panel, PillTabs, ProgressRow,
  inputClass, useMutation, utcDate,
} from "@/components/operations/ui";
import { ChecksList } from "@/components/operations/registry";
import {
  actOnBreakGlass, getAdminActivity, listBreakGlass, listBreakGlassPermissions, requestBreakGlass,
  type ActivityEvent, type BreakGlassGrant,
} from "@/lib/api";

const DURATIONS = [15, 30, 60, 120, 240];
type TabKey = "all" | "pending" | "active" | "reviews" | "denied" | "completed";
const STATE: Record<BreakGlassGrant["status"], { label: string; tone: "ok" | "warn" | "bad" | "info" | "neutral" }> = {
  requested: { label: "Pending approval", tone: "warn" }, active: { label: "Active monitored", tone: "ok" },
  expired: { label: "Completed", tone: "info" }, revoked: { label: "Revoked", tone: "info" }, rejected: { label: "Denied", tone: "bad" },
};
const WRITE = (p: string) => /\.(manage|resolve|correct)$/.test(p);

function risk(g: BreakGlassGrant): "critical" | "high" | "medium" | "low" {
  if (g.permissions.includes("audit.correct")) return "critical";
  if (g.permissions.some(WRITE)) return "high";
  return g.permissions.length > 2 ? "medium" : "low";
}
const RISK_TONE = { critical: "bad", high: "warn", medium: "info", low: "ok" } as const;

function inTab(g: BreakGlassGrant, tab: TabKey): boolean {
  switch (tab) {
    case "all": return true;
    case "pending": return g.status === "requested";
    case "active": return g.status === "active";
    case "reviews": return g.needs_review;
    case "denied": return g.status === "rejected";
    case "completed": return (g.status === "expired" || g.status === "revoked") && !g.needs_review;
  }
}

export default function BreakGlassPage() {
  const { profile } = useAuth();
  const isAdmin = profile?.role === "Admin";
  const { data, error, loading, signedOut, reload } = useLiveData(
    "break-glass", async (token) => {
      const [grants, permissions] = await Promise.all([listBreakGlass(token), listBreakGlassPermissions(token)]);
      return { grants, permissions };
    }, 30_000,
  );
  const [tab, setTab] = useState<TabKey>("all");
  const [selectedId, setSelectedId] = useState("");
  const [requesting, setRequesting] = useState(false);
  // One clock per load: remaining times are as of the last refresh.
  const [now] = useState(() => Date.now());
  const grants = useMemo(() => data?.grants ?? [], [data]);
  const ref = (id: string) => `BG-${String(grants.length - grants.findIndex((g) => g.id === id)).padStart(3, "0")}`;
  const selected = grants.find((g) => g.id === selectedId) ?? grants.find((g) => g.status === "requested") ?? grants[0];
  const monthAgo = now - 30 * 86_400_000;
  const recent = grants.filter((g) => new Date(g.requested_at).getTime() >= monthAgo);

  return (
    <main className="flex-1 space-y-4 overflow-y-auto p-4">
      <Breadcrumb section="Administration" page="Break-glass Access" detail="Emergency access control" />
      <OpsHero icon={Siren} title="Break-glass Access"
        subtitle="Exceptional access, without standing privilege. Govern every request, approval, session, and revocation. Tenant data stays protected by independent approval and purpose-bound access.">
        <p className="text-base font-bold text-white">Emergency privilege. Exceptional control.</p>
        <p>Dual custody · Time bound · Audited</p>
        <p>Auto-expiring · Independently reviewed</p>
      </OpsHero>
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />
      {data && (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <KpiTile icon={ClipboardList} value={recent.length} label="Requests (30 days)" hint={isAdmin ? "This workspace" : "Your own requests"} />
            <KpiTile icon={Hourglass} tone={grants.some((g) => g.status === "requested") ? "warn" : "ok"} value={grants.filter((g) => g.status === "requested").length}
              label="Pending independent approval" hint="No privilege issued yet" />
            <KpiTile icon={Radio} tone="ok" value={grants.filter((g) => g.status === "active").length} label="Active monitored sessions" hint="Expire automatically" />
            <KpiTile icon={ShieldAlert} tone={grants.some((g) => g.needs_review) ? "bad" : "ok"} value={grants.filter((g) => g.needs_review).length}
              label="Post-access reviews due" hint="Ended, not yet reviewed" />
            <KpiTile icon={Ban} value={grants.filter((g) => g.status === "rejected").length} label="Denied requests" hint="Rejected by an Admin" />
          </div>
          <section className="flex flex-col gap-2 rounded-xl border border-accent/40 border-l-4 border-l-accent bg-accent/5 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-bold text-accent-ink">NO STANDING TENANT-DATA ACCESS</p>
              <p className="text-sm text-ink">Emergency access needs a stated reason, a different Admin&apos;s approval, an enforced expiry, and an independent review after it ends.</p>
            </div>
          </section>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <PillTabs label="Request views" active={tab} onChange={setTab} tabs={[
              { key: "all", label: "All requests", count: grants.length },
              { key: "pending", label: "Pending approvals", count: grants.filter((g) => inTab(g, "pending")).length },
              { key: "active", label: "Active sessions", count: grants.filter((g) => inTab(g, "active")).length },
              { key: "reviews", label: "Post-access reviews", count: grants.filter((g) => inTab(g, "reviews")).length },
              { key: "denied", label: "Denied", count: grants.filter((g) => inTab(g, "denied")).length },
              { key: "completed", label: "Completed", count: grants.filter((g) => inTab(g, "completed")).length }]} />
            <Button variant="primary" onClick={() => setRequesting(true)}>+ Request emergency access</Button>
          </div>
          {requesting && <RequestForm permissions={data.permissions} onDone={() => { setRequesting(false); reload(); }} />}
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_440px]">
            <Register grants={grants.filter((g) => inTab(g, tab))} all={grants} refOf={ref} selectedId={selected?.id} onSelect={setSelectedId} />
            {selected ? <Detail key={selected.id} g={selected} refOf={ref} isAdmin={isAdmin} selfId={profile?.id} now={now} onChanged={reload} />
              : <Panel title="Emergency request"><EmptyState icon={Siren} title="No emergency access requested">Nobody holds elevated access.</EmptyState></Panel>}
          </div>
          <Bottom grants={grants} refOf={ref} now={now} onTab={setTab} onRequest={() => setRequesting(true)} />
        </>
      )}
    </main>
  );
}

function Register({ grants, all, refOf, selectedId, onSelect }: {
  grants: BreakGlassGrant[]; all: BreakGlassGrant[]; refOf: (id: string) => string; selectedId?: string; onSelect: (id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [state, setState] = useState("");
  const [riskF, setRiskF] = useState("");
  const rows = grants.filter((g) => (!state || g.status === state) && (!riskF || risk(g) === riskF)
    && (!query || `${refOf(g.id)} ${g.user_name} ${g.reason} ${g.permissions.join(" ")}`.toLowerCase().includes(query.toLowerCase())));
  return (
    <Panel title="Emergency access request register" meta="Search and select a request">
      <div className="mb-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_10rem_9rem_auto]">
        <label className="relative">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input className={`${inputClass} pl-9`} placeholder="Search request ID, owner or purpose…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <select aria-label="Status" className={inputClass} value={state} onChange={(e) => setState(e.target.value)}><option value="">All statuses</option>{Object.entries(STATE).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select>
        <select aria-label="Risk" className={inputClass} value={riskF} onChange={(e) => setRiskF(e.target.value)}><option value="">All risks</option>{["critical", "high", "medium", "low"].map((r) => <option key={r} value={r}>{r[0].toUpperCase() + r.slice(1)}</option>)}</select>
        <Button onClick={() => { setQuery(""); setState(""); setRiskF(""); }}>Reset</Button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-left text-sm">
          <thead className="bg-soft text-xs text-muted">
            <tr>{["Request / owner", "Reason", "Requested permissions", "Privilege", "Risk", "State", "TTL"].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((g) => {
              const r = risk(g);
              const writes = g.permissions.filter(WRITE).length;
              return (
                <tr key={g.id} onClick={() => onSelect(g.id)} aria-selected={selectedId === g.id}
                  className={`cursor-pointer border-b border-line hover:bg-soft ${selectedId === g.id ? "bg-info/5" : ""}`}>
                  <td className="px-3 py-2.5"><b className="block text-info">{refOf(g.id)}</b><span className="mt-1 flex items-center gap-1.5"><Avatar name={g.user_name} /><span className="font-semibold text-ink">{g.user_name}</span></span></td>
                  <td className="px-3 py-2.5 text-ink">{g.reason}</td>
                  <td className="px-3 py-2.5 text-xs text-ink">{g.permissions.join(", ")}</td>
                  <td className="px-3 py-2.5 text-ink">{writes ? `Write · ${writes} permission${writes === 1 ? "" : "s"}` : "Read-only"}</td>
                  <td className="px-3 py-2.5"><Badge tone={RISK_TONE[r]}>{r[0].toUpperCase() + r.slice(1)}</Badge></td>
                  <td className="px-3 py-2.5"><Badge tone={g.needs_review ? "bad" : STATE[g.status].tone}>{g.needs_review ? "Post-review due" : STATE[g.status].label}</Badge></td>
                  <td className="px-3 py-2.5 text-ink">{g.duration_minutes} min</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!rows.length && <EmptyState title="No requests in this view" />}
      </div>
      <p className="mt-3 flex justify-between text-xs text-muted"><span>{rows.length} of {all.length} requests</span><span>UTC · exact permissions required</span></p>
    </Panel>
  );
}

type DetailTab = "overview" | "gates" | "session" | "evidence";

function Detail({ g, refOf, isAdmin, selfId, now, onChanged }: {
  g: BreakGlassGrant; refOf: (id: string) => string; isAdmin: boolean; selfId?: string; now: number; onChanged: () => void;
}) {
  const [tab, setTab] = useState<DetailTab>("overview");
  const [notes, setNotes] = useState("");
  const [events, setEvents] = useState<ActivityEvent[] | null>(null);
  const { busy, error, run } = useMutation();
  const own = g.user_id === selfId;
  const act = (a: "approve" | "reject" | "revoke" | "review") => run(a, (t) => actOnBreakGlass(t, g.id, a, notes)).then((ok) => { if (ok) { setNotes(""); onChanged(); } });
  const remaining = g.expires_at ? Math.max(0, Math.round((new Date(g.expires_at).getTime() - now) / 60000)) : null;
  const gates = [
    { label: "Reason recorded", status: g.reason.trim() ? "pass" : "fail", note: g.reason } as const,
    { label: "Within the tenant time limit", status: "pass", note: `${g.duration_minutes} minutes requested` } as const,
    { label: "Independent approver", status: g.approved_by ? (g.approved_by !== g.user_id ? "pass" : "fail") : g.status === "rejected" ? "fail" : "open",
      note: g.approved_by ? "Approved by a different Admin" : g.status === "rejected" ? "Rejected" : "Awaiting a different Admin" } as const,
    { label: "Automatic expiry enforced", status: g.expires_at || g.status === "requested" || g.status === "rejected" ? "pass" : "open",
      note: g.expires_at ? `Expires ${utcDate(g.expires_at)}` : "Set when approved" } as const,
    { label: "Post-access review", status: g.reviewed_at ? "pass" : g.needs_review ? "fail" : "open",
      note: g.reviewed_at ? `Reviewed ${utcDate(g.reviewed_at)}` : g.needs_review ? "Overdue: ended without review" : "After the session ends" } as const,
  ];
  return (
    <Panel title={refOf(g.id)} action={<Badge tone={g.needs_review ? "bad" : STATE[g.status].tone}>{g.needs_review ? "Post-review due" : STATE[g.status].label}</Badge>}>
      <h3 className="-mt-1 mb-3 text-lg font-extrabold text-ink">{g.reason}</h3>
      {g.status === "requested" && <div className="mb-3 rounded-lg border border-accent/40 bg-accent/5 p-3"><p className="text-sm font-bold text-accent-ink">GRANT BLOCKED · INDEPENDENT APPROVAL PENDING</p><p className="text-sm text-ink">No privilege has been issued.</p></div>}
      {g.status === "active" && <div className="mb-3 rounded-lg border border-ok/30 bg-ok/5 p-3"><p className="text-sm font-bold text-ok">ACTIVE · {remaining} MIN REMAINING</p><p className="text-sm text-ink">Ends automatically at {g.expires_at ? utcDate(g.expires_at) : ""}.</p></div>}
      <PillTabs label="Request detail" active={tab} onChange={(t) => { setTab(t); if (t === "evidence" && events === null && isAdmin) run("evidence", async (tok) => setEvents(await getAdminActivity(tok, g.id))); }}
        tabs={[{ key: "overview", label: "Overview" }, { key: "gates", label: "Approval gates" }, { key: "session", label: "Session controls" }, { key: "evidence", label: "Evidence trail" }]} />
      <div className="mt-4 space-y-4">
        {tab === "overview" && <DetailRows rows={[
          ["Requester", g.user_name], ["Purpose", g.reason], ["Permissions", g.permissions.join(", ")],
          ["Effective privilege", g.permissions.some(WRITE) ? "Write" : "Read-only"], ["Risk classification", risk(g)],
          ["Maximum TTL", `${g.duration_minutes} min`], ["Requested", utcDate(g.requested_at)],
          ["Access start", g.activated_at ? utcDate(g.activated_at) : "Not started"],
          ["Access expires", g.expires_at ? utcDate(g.expires_at) : "Not issued"],
          ["Approval", g.approved_by ? "Approved by a different Admin" : g.status === "rejected" ? "Rejected" : "Pending"],
        ]} />}
        {tab === "gates" && <ChecksList title={`Authorization readiness · ${gates.filter((x) => x.status === "pass").length} of ${gates.length} satisfied`} checks={gates} />}
        {tab === "session" && <DetailRows rows={[
          ["Status", STATE[g.status].label], ["Started", g.activated_at ? utcDate(g.activated_at) : "—"],
          ["Ends", g.ended_at ? utcDate(g.ended_at) : g.expires_at ? `${utcDate(g.expires_at)} (automatic)` : "—"],
          ["Review", g.reviewed_at ? `${utcDate(g.reviewed_at)} · ${g.review_notes ?? ""}` : "Not yet"],
        ]} />}
        {tab === "evidence" && (!isAdmin ? <p className="text-sm text-muted">The evidence trail is visible to Admins.</p> : events === null ? <p className="text-sm text-muted">Loading…</p> : events.length ? (
          <ul className="space-y-2 text-sm">{events.map((e) => <li key={e.id}><b className="text-ink">{e.event.replace(/_/g, " ")}</b> <span className="text-xs text-muted">· {e.actor} · {utcDate(e.at)}</span></li>)}</ul>
        ) : <p className="text-sm text-muted">No events recorded.</p>)}
        <ErrorNote message={error} />
        {isAdmin && (g.status === "requested" || g.needs_review) && (
          <textarea className={`${inputClass} min-h-16 py-2`} placeholder={g.needs_review ? "Review findings (required)" : "Note (optional)"} value={notes} onChange={(e) => setNotes(e.target.value)} />
        )}
        <div className="flex flex-wrap gap-2 border-t border-line pt-3">
          {isAdmin && g.status === "requested" && <Button variant="primary" disabled={own} title={own ? "A different Admin must approve" : ""} busy={busy === "approve"} onClick={() => act("approve")}>Approve grant</Button>}
          {isAdmin && g.status === "requested" && <Button busy={busy === "reject"} onClick={() => act("reject")}>Reject</Button>}
          {g.status === "active" && (isAdmin || own) && <Button variant="danger" busy={busy === "revoke"} onClick={() => act("revoke")}>Emergency revoke</Button>}
          {isAdmin && g.needs_review && <Button variant="primary" disabled={own || !notes.trim()} title={own ? "Someone else must review your access" : ""} busy={busy === "review"} onClick={() => act("review")}>Record post-access review</Button>}
          <Button onClick={() => setTab("gates")}>Review approvals</Button>
        </div>
      </div>
    </Panel>
  );
}

function Bottom({ grants, refOf, now, onTab, onRequest }: { grants: BreakGlassGrant[]; refOf: (id: string) => string; now: number; onTab: (t: TabKey) => void; onRequest: () => void }) {
  const total = Math.max(1, grants.length);
  const active = grants.filter((g) => g.status === "active");
  const dist: [string, number, "warn" | "ok" | "info" | "bad"][] = [
    ["Pending approval", grants.filter((g) => g.status === "requested").length, "warn"],
    ["Active monitored", active.length, "ok"],
    ["Completed", grants.filter((g) => (g.status === "expired" || g.status === "revoked") && !g.needs_review).length, "info"],
    ["Denied", grants.filter((g) => g.status === "rejected").length, "bad"],
    ["Post-review due", grants.filter((g) => g.needs_review).length, "bad"],
  ];
  return (
    <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
      <Panel title="Request status distribution">
        <div className="space-y-3">{dist.map(([l, v, t]) => <ProgressRow key={l} label={l} value={v} total={total} tone={t} right={v} />)}</div>
        <p className="mt-3 text-xs text-muted">Every grant, denial, expiry and review is a separate audited decision.</p>
      </Panel>
      <Panel title="Session oversight">
        {active.length ? (
          <ul className="space-y-2 text-sm">{active.map((g) => (
            <li key={g.id} className="flex items-center justify-between gap-2">
              <span><b className="text-ink">{refOf(g.id)} · {g.user_name}</b><span className="block text-xs text-muted">{g.permissions.join(", ")}</span></span>
              <Badge tone="info">{g.expires_at ? `${Math.max(0, Math.round((new Date(g.expires_at).getTime() - now) / 60000))} min left` : ""}</Badge>
            </li>))}</ul>
        ) : <p className="text-sm text-muted">No active emergency sessions.</p>}
        <p className="mt-3 rounded-lg border border-line bg-soft p-2.5 text-xs text-ink"><b>Automatic revocation:</b> every grant ends at its expiry with no action needed.</p>
      </Panel>
      <Panel title="Nonnegotiable control policy">
        <ul className="space-y-2 text-sm text-ink">
          {["Requester and approver must be different Admins", "Tenant isolation is enforced server-side throughout",
            "Exact permissions and a maximum time limit per request", "Grants expire automatically and can be revoked at once",
            "Independent post-access review after every grant"].map((t) => <li key={t} className="flex gap-2"><span className="text-ok">✓</span>{t}</li>)}
        </ul>
      </Panel>
      <Panel title="Governed actions">
        <div className="grid grid-cols-2 gap-2">
          <Button onClick={onRequest}>+ New request</Button>
          <Button onClick={() => onTab("pending")}>Approval queue</Button>
          <Button onClick={() => onTab("active")}><Clock3 size={14} /> Sessions</Button>
          <Button onClick={() => onTab("reviews")}>Post-access reviews</Button>
          <Link href="/audit-logs" className="col-span-2 inline-flex min-h-10 items-center justify-center rounded-lg border border-line bg-panel text-sm font-semibold text-info hover:bg-soft">Audit evidence</Link>
        </div>
      </Panel>
    </div>
  );
}

function RequestForm({ permissions, onDone }: { permissions: string[]; onDone: () => void }) {
  const [selected, setSelected] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [duration, setDuration] = useState(30);
  const { busy, error, run } = useMutation();
  return (
    <Panel title="Request emergency access" meta="Another Admin must approve before it takes effect" action={<Button onClick={onDone}>Cancel</Button>}>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); run("req", (t) => requestBreakGlass(t, { permissions: selected, reason, duration_minutes: duration })).then((ok) => ok && onDone()); }}>
        <fieldset className="flex flex-wrap gap-2">
          <legend className="mb-1 text-sm text-muted">Exact permissions needed</legend>
          {permissions.map((p) => (
            <label key={p} className={`flex cursor-pointer items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-sm ${selected.includes(p) ? "border-accent bg-accent/10 text-accent-ink" : "border-line text-ink"}`}>
              <input type="checkbox" className="sr-only" checked={selected.includes(p)} onChange={(e) => setSelected(e.target.checked ? [...selected, p] : selected.filter((x) => x !== p))} />{p}
            </label>
          ))}
        </fieldset>
        <div className="grid gap-2 md:grid-cols-[1fr_auto]">
          <input required className={inputClass} placeholder="Reason and incident reference" value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Reason" />
          <select aria-label="Duration" className={inputClass} value={duration} onChange={(e) => setDuration(Number(e.target.value))}>{DURATIONS.map((d) => <option key={d} value={d}>{d} minutes</option>)}</select>
        </div>
        <ErrorNote message={error} />
        <Button type="submit" variant="primary" disabled={!selected.length} busy={busy === "req"}>Submit request</Button>
      </form>
    </Panel>
  );
}
