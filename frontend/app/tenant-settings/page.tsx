"use client";

import { useMemo, useState } from "react";
import {
  Ban, CheckCircle2, ClipboardCheck, Clock3, Search, Settings, ShieldCheck, SlidersHorizontal,
} from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { useLiveData } from "@/components/overview/useLiveData";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import {
  Badge, Breadcrumb, Button, DetailRows, EmptyState, ErrorNote, KpiRow, KpiTile, OpsHero, Panel, PillTabs, humanize,
  inputClass, useMutation, utcDate,
} from "@/components/operations/ui";
import {
  decideSettingChange, getTenantSettingsConsole, requestSettingChange,
  type ControlAuthority, type ControlState, type SettingRequest, type TenantControl, type TenantSettingsConsole,
} from "@/lib/api";

const DOMAINS = ["Identity & SSO", "Privacy & Residency", "Kriton & AI", "Professional Approvals", "Integrations", "Notifications"];
type TabKey = "all" | "requests" | "history" | (typeof DOMAINS)[number];
const AUTHORITY: Record<ControlAuthority, { label: string; tone: "neutral" | "info" | "warn" }> = {
  global_locked: { label: "Global locked", tone: "neutral" }, deployment: { label: "Deployment", tone: "info" },
  tenant_scoped: { label: "Tenant-scoped", tone: "warn" },
};
const STATE: Record<ControlState, { label: string; tone: "ok" | "warn" | "bad" | "neutral" | "info" }> = {
  enforced: { label: "Enforced", tone: "ok" }, staged: { label: "Change staged", tone: "info" },
  review_due: { label: "Review due", tone: "warn" }, blocked: { label: "Blocked", tone: "bad" },
  not_configured: { label: "Not configured", tone: "neutral" },
};
const REQUEST: Record<SettingRequest["status"], "warn" | "ok" | "bad" | "neutral"> = { pending: "warn", applied: "ok", rejected: "bad", withdrawn: "neutral" };
const RISK = { critical: "text-bad", high: "text-accent-ink", medium: "text-info", low: "text-ok" };

export default function TenantSettingsPage() {
  const { profile } = useAuth();
  const { data, error, loading, signedOut, reload } = useLiveData(
    "tenant-settings", (token, signal) => getTenantSettingsConsole(token, signal), 30_000,
  );
  const [tab, setTab] = useState<TabKey>("all");
  const [selectedId, setSelectedId] = useState("");
  const controls = useMemo(() => data?.controls ?? [], [data]);
  const selected = controls.find((c) => c.id === selectedId) ?? controls.find((c) => c.state === "staged" || c.state === "review_due") ?? controls[0];

  return (
    <main className="flex-1 space-y-4 overflow-y-auto p-4">
      <Breadcrumb section="Administration" page="Tenant Settings" detail="Effective policy and staged changes" />
      <OpsHero icon={Settings} title="Tenant Settings"
        subtitle="Configure permitted tenant preferences. Govern identity, privacy, Kriton, and professional workflows · Inherited safeguards • Controlled changes • Evidence-backed approvals • Complete accountability">
        <p>● Global safeguards enforced in code</p>
        <p>◆ Tenant settings may only be stricter</p>
        <p>– Proposed changes are not effective until approved</p>
      </OpsHero>
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />
      {data && (
        <>
          <section className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-panel px-4 py-3 text-sm text-ink">
            <span className="flex flex-wrap gap-x-5 gap-y-1">
              <span><b>Tenant:</b> {data.tenant.name}</span><span><b>Tenant ID:</b> <span className="font-mono text-xs">{data.tenant.id.slice(0, 8)}</span></span>
              <span><b>Data region:</b> {data.tenant.region}</span><span><b>Effective policy:</b> {data.tenant.policyVersion}</span>
              <span><b>Last evaluated:</b> {utcDate(data.tenant.evaluatedAt)}</span>
            </span>
            <span className="text-xs font-bold text-ok">◎ TENANT SCOPE ONLY</span>
          </section>
          <Kpis data={data} />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <PillTabs label="Settings views" active={tab} onChange={setTab} tabs={[
              { key: "all", label: "All Settings" }, ...DOMAINS.map((d) => ({ key: d as TabKey, label: d })),
              { key: "requests", label: "Change Requests", count: data.summary.stagedRequests }, { key: "history", label: "Audit History" }]} />
            <Button variant="primary" onClick={() => { const c = controls.find((x) => x.authority === "tenant_scoped"); if (c) { setSelectedId(c.id); setTab("all"); } }}>+ Request Change</Button>
          </div>
          {tab === "requests" ? <RequestsPanel data={data} selfId={profile?.id} onChanged={reload} />
            : tab === "history" ? <ActivityPanel data={data} full /> : (
              <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_440px]">
                <Register controls={controls.filter((c) => tab === "all" || c.domain === tab)} selectedId={selected?.id} onSelect={setSelectedId} />
                {selected && <Detail key={selected.id} c={selected} data={data} selfId={profile?.id} onChanged={reload} />}
              </div>
            )}
          <div className="grid gap-4 xl:grid-cols-3">
            <Panel title="Staged Change Requests" meta="Nothing changes effective policy without a second Admin">
              {data.requests.filter((r) => r.status === "pending").length ? (
                <ul className="divide-y divide-line text-sm">{data.requests.filter((r) => r.status === "pending").map((r) => (
                  <li key={r.id} className="flex items-center justify-between gap-2 py-2">
                    <span><b className="block text-ink">{r.ref} · {r.setting}</b><span className="text-xs text-muted">{r.from} → {r.to} · {r.requestedBy}</span></span>
                    <Badge tone="warn">Pending</Badge>
                  </li>))}</ul>
              ) : <p className="text-sm text-muted">No changes waiting for approval.</p>}
            </Panel>
            <Panel title="Effective Control Hierarchy" meta="Tenant settings cannot override higher-priority safeguards">
              <ol className="space-y-3">{data.hierarchy.map((h) => (
                <li key={h.level} className="flex gap-3">
                  <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg border border-line text-sm font-bold text-ink">{h.level}</span>
                  <span><b className="block text-sm text-ink">{h.title}</b><span className="text-xs text-muted">{h.detail}</span></span>
                </li>))}</ol>
            </Panel>
            <ActivityPanel data={data} />
          </div>
        </>
      )}
    </main>
  );
}

function Kpis({ data }: { data: TenantSettingsConsole }) {
  const s = data.summary;
  return (
    <KpiRow>
      <KpiTile icon={ShieldCheck} value={s.effectiveControls} label="Effective Controls" hint={`Of ${s.totalControls} in the register`} />
      <KpiTile icon={Clock3} tone={s.stagedRequests ? "warn" : "ok"} value={s.stagedRequests} label="Staged Change Requests" hint="Not yet in effect" />
      <KpiTile icon={Ban} tone={s.prohibitedOverrides ? "bad" : "ok"} value={s.prohibitedOverrides} label="Prohibited Overrides" hint="Attempts to loosen, refused" />
      <KpiTile icon={ClipboardCheck} tone={s.reviewsDue ? "warn" : "ok"} value={s.reviewsDue} label="Access Reviews Due" hint="People awaiting recertification" />
      <KpiTile icon={SlidersHorizontal} tone="info" value={s.tightened} label="Tightened Settings" hint="Stricter than the deployment" />
      <KpiTile icon={CheckCircle2} tone={s.activeExceptions ? "warn" : "ok"} value={s.activeExceptions} label="Active Exceptions" hint="Break-glass grants in force" />
    </KpiRow>
  );
}

function Register({ controls, selectedId, onSelect }: { controls: TenantControl[]; selectedId?: string; onSelect: (id: string) => void }) {
  const [query, setQuery] = useState("");
  const [state, setState] = useState("");
  const [authority, setAuthority] = useState("");
  const rows = controls.filter((c) => (!state || c.state === state) && (!authority || c.authority === authority)
    && (!query || `${c.id} ${c.name} ${c.domain} ${c.value} ${c.description}`.toLowerCase().includes(query.toLowerCase())));
  return (
    <Panel title="Effective Settings & Control Register" meta="Effective policy is read-only; changes need a separately approved request">
      <div className="mb-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_auto]">
        <label className="relative">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input className={`${inputClass} pl-9`} placeholder="Search by control name, ID, value or purpose…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <Button onClick={() => { setQuery(""); setState(""); setAuthority(""); }}>Clear</Button>
      </div>
      <div className="mb-3 grid gap-2 sm:grid-cols-2">
        <select aria-label="Status" className={inputClass} value={state} onChange={(e) => setState(e.target.value)}><option value="">All statuses</option>{Object.entries(STATE).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select>
        <select aria-label="Authority" className={inputClass} value={authority} onChange={(e) => setAuthority(e.target.value)}><option value="">All authorities</option>{Object.entries(AUTHORITY).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-left text-sm">
          <thead className="bg-soft text-xs text-muted">
            <tr>{["Control / ID", "Domain", "Policy authority", "Effective state", "Value", "Risk", "Last changed"].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id} onClick={() => onSelect(c.id)} aria-selected={selectedId === c.id}
                className={`cursor-pointer border-b border-line hover:bg-soft ${selectedId === c.id ? "bg-info/5" : ""}`}>
                <td className="px-3 py-2.5"><b className="block text-ink">{c.name}</b><span className="text-[11px] text-muted">{c.id}</span></td>
                <td className="px-3 py-2.5 text-ink">{c.domain}</td>
                <td className="px-3 py-2.5"><Badge tone={AUTHORITY[c.authority].tone}>{AUTHORITY[c.authority].label}</Badge></td>
                <td className="px-3 py-2.5"><Badge tone={STATE[c.state].tone}>{STATE[c.state].label}</Badge></td>
                <td className="px-3 py-2.5 text-ink">{c.value}</td>
                <td className={`px-3 py-2.5 text-xs font-bold ${RISK[c.risk]}`}>{humanize(c.risk)}</td>
                <td className="px-3 py-2.5 text-ink">{c.changedAt ? utcDate(c.changedAt).split(" · ")[0] : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length && <EmptyState title="No controls match these filters" />}
      </div>
      <p className="mt-3 text-xs text-muted">{rows.length} of {controls.length} controls · scope: this tenant only</p>
    </Panel>
  );
}

type DetailTab = "overview" | "rules" | "hierarchy" | "history";

function Detail({ c, data, selfId, onChanged }: { c: TenantControl; data: TenantSettingsConsole; selfId?: string; onChanged: () => void }) {
  const [tab, setTab] = useState<DetailTab>("overview");
  const [value, setValue] = useState<string>(c.kind === "bool" ? "true" : String(c.rawEffective ?? ""));
  const [reason, setReason] = useState("");
  const { busy, error, run } = useMutation();
  const pending = data.requests.find((r) => r.key === c.key && r.status === "pending");
  const editable = c.authority === "tenant_scoped" && !pending;
  return (
    <Panel title={c.name} meta={`${c.id} · ${c.domain}`} action={<Badge tone={STATE[c.state].tone}>{STATE[c.state].label}</Badge>}>
      <p className="-mt-2 mb-3 text-xs text-muted">{c.description}</p>
      <PillTabs label="Control detail" active={tab} onChange={setTab} tabs={[
        { key: "overview", label: "Overview" }, { key: "rules", label: "Change rules" },
        { key: "hierarchy", label: "Policy hierarchy" }, { key: "history", label: "Change history", count: c.history.length }]} />
      <div className="mt-4 space-y-4">
        {c.authority === "global_locked" && (
          <div className="rounded-lg border border-line bg-soft p-3"><p className="text-sm font-bold text-ink">GLOBAL SAFEGUARD · NOT OVERRIDABLE</p><p className="text-sm text-ink">{c.rule}</p></div>
        )}
        {c.state === "review_due" && (
          <div className="rounded-lg border border-accent/40 bg-accent/5 p-3"><p className="text-sm font-bold text-accent-ink">REVIEW DUE</p>
            <p className="text-sm text-ink">{c.key ? "This safeguard is not switched on for this tenant. Request the stricter setting below." : "Not restricted by the deployment. Ask the deployment operator to set it."}</p></div>
        )}
        {tab === "overview" && (
          <DetailRows rows={[
            ["Effective value", c.value], ["Deployment value", c.deploymentValue], ["Tenant value", c.tenantValue ?? "Not set (inherits)"],
            ["Policy authority", AUTHORITY[c.authority].label], ["Change authority", c.changeAuthority],
            ["Pending change", pending ? `${pending.ref}: ${pending.from} → ${pending.to}` : "None"],
            ["Last changed", c.changedAt ? utcDate(c.changedAt) : "Never"],
          ]} />
        )}
        {tab === "rules" && (
          <ul className="space-y-2 text-sm text-ink">
            <li className="flex gap-2"><span className="text-ok">✓</span>{c.rule}</li>
            <li className="flex gap-2"><span className="text-ok">✓</span>A loosening request is refused and counted as a prohibited override.</li>
            <li className="flex gap-2"><span className="text-ok">✓</span>The requester cannot approve their own change.</li>
            <li className="flex gap-2"><span className="text-ok">✓</span>On approval the value is re-checked against the current deployment before it takes effect.</li>
          </ul>
        )}
        {tab === "hierarchy" && (
          <ol className="space-y-2 text-sm">{data.hierarchy.map((h) => (
            <li key={h.level} className={`rounded-lg border p-2.5 ${(c.authority === "global_locked" && h.level === 1) || (c.authority === "deployment" && h.level === 2) || (c.authority === "tenant_scoped" && h.level === 3) ? "border-accent bg-accent/5" : "border-line"}`}>
              <b className="text-ink">{h.level}. {h.title}</b><span className="block text-xs text-muted">{h.detail}</span></li>))}</ol>
        )}
        {tab === "history" && (c.history.length ? <RequestList requests={c.history} /> : <p className="text-sm text-muted">No change requests for this control.</p>)}
        {editable && (
          <form className="space-y-2 border-t border-line pt-3" onSubmit={(e) => {
            e.preventDefault();
            const proposed = c.kind === "bool" ? value === "true" : Number(value);
            run("req", (t) => requestSettingChange(t, c.key!, proposed, reason)).then((ok) => { if (ok) { setReason(""); onChanged(); } });
          }}>
            <p className="text-sm font-bold text-ink">Request a stricter value</p>
            <div className="grid gap-2 sm:grid-cols-[10rem_1fr]">
              {c.kind === "bool" ? (
                <select aria-label="Proposed value" className={inputClass} value={value} onChange={(e) => setValue(e.target.value)}>
                  <option value="true">Required</option><option value="false">Not required</option>
                </select>
              ) : (
                <input aria-label="Proposed value" type="number" min={1} className={inputClass} value={value} onChange={(e) => setValue(e.target.value)} />
              )}
              <input required minLength={3} className={inputClass} placeholder="Reason (recorded with the request)" value={reason} onChange={(e) => setReason(e.target.value)} />
            </div>
            <ErrorNote message={error} />
            <Button type="submit" variant="primary" busy={busy === "req"}>Stage change for approval</Button>
          </form>
        )}
        {pending && <PendingDecision r={pending} selfId={selfId} onChanged={onChanged} />}
        {c.authority !== "tenant_scoped" && <Button disabled>Apply change · {c.authority === "global_locked" ? "Locked" : "Deployment setting"}</Button>}
      </div>
    </Panel>
  );
}

function PendingDecision({ r, selfId, onChanged }: { r: SettingRequest; selfId?: string; onChanged: () => void }) {
  const [note, setNote] = useState("");
  const { busy, error, run } = useMutation();
  const own = r.requestedById === selfId;
  const decide = (approve: boolean) => run(approve ? "a" : "r", (t) => decideSettingChange(t, r.id, approve, note)).then((ok) => ok && onChanged());
  return (
    <div className="space-y-2 rounded-lg border border-info/30 bg-info/5 p-3">
      <p className="text-sm font-bold text-ink">{r.ref} awaiting approval: {r.from} → {r.to}</p>
      <p className="text-xs text-muted">Requested by {r.requestedBy} · {r.reason}</p>
      <input className={inputClass} placeholder={own ? "Note (optional)" : "Decision note (required to reject)"} value={note} onChange={(e) => setNote(e.target.value)} />
      <ErrorNote message={error} />
      <div className="flex gap-2">
        {!own && <Button variant="primary" busy={busy === "a"} onClick={() => decide(true)}>Approve &amp; apply</Button>}
        <Button busy={busy === "r"} onClick={() => decide(false)}>{own ? "Withdraw request" : "Reject"}</Button>
      </div>
      {own && <p className="text-xs text-muted">Another Admin must approve your request.</p>}
    </div>
  );
}

function RequestList({ requests }: { requests: SettingRequest[] }) {
  return (
    <ul className="divide-y divide-line text-sm">{requests.map((r) => (
      <li key={r.id} className="flex items-start justify-between gap-2 py-2">
        <span><b className="block text-ink">{r.ref} · {r.setting}: {r.from} → {r.to}</b>
          <span className="text-xs text-muted">{r.requestedBy} · {r.requestedAt ? utcDate(r.requestedAt) : ""}{r.decidedBy ? ` · decided by ${r.decidedBy}` : ""}{r.decisionNote ? ` · ${r.decisionNote}` : ""}</span></span>
        <Badge tone={REQUEST[r.status]}>{humanize(r.status)}</Badge>
      </li>))}</ul>
  );
}

function RequestsPanel({ data, selfId, onChanged }: { data: TenantSettingsConsole; selfId?: string; onChanged: () => void }) {
  const pending = data.requests.filter((r) => r.status === "pending");
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Panel title="Awaiting approval" meta="A different Admin approves">
        {pending.length ? <div className="space-y-3">{pending.map((r) => <PendingDecision key={r.id} r={r} selfId={selfId} onChanged={onChanged} />)}</div>
          : <p className="text-sm text-muted">No changes waiting.</p>}
      </Panel>
      <Panel title="All change requests">{data.requests.length ? <RequestList requests={data.requests} /> : <p className="text-sm text-muted">No change has been requested yet.</p>}</Panel>
    </div>
  );
}

function ActivityPanel({ data, full = false }: { data: TenantSettingsConsole; full?: boolean }) {
  const events = full ? data.activity : data.activity.slice(0, 4);
  return (
    <Panel title="Recent Settings Activity" meta="Attributed, versioned, audited">
      {events.length ? (
        <ul className="space-y-2.5 text-sm">{events.map((e) => (
          <li key={e.id} className="flex gap-2"><span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-info" />
            <span><b className="text-ink">{e.event.replace("tenant_setting_", "").replace(/_/g, " ")}</b> · {e.subjectId.replace(/_/g, " ")}
              <span className="block text-xs text-muted">{utcDate(e.at)} · {e.actor}{e.detail.ref ? ` · ${String(e.detail.ref)}` : ""}</span></span></li>))}</ul>
      ) : <p className="text-sm text-muted">No settings activity yet.</p>}
    </Panel>
  );
}
