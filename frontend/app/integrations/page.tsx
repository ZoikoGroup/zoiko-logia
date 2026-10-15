"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  AlertTriangle, BadgeCheck, Ban, Clock3, FileSearch, Layers, ListChecks, Plug, RefreshCw, Search, ShieldAlert, Waypoints,
} from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { useLiveData } from "@/components/overview/useLiveData";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import {
  Badge, Button, DetailRows, EmptyState, ErrorNote, KpiRow, KpiTile, OpsHero, Panel, PillTabs, ProgressRow,
  humanize, inputClass, timeAgo, useMutation, utcDate,
} from "@/components/operations/ui";
import { GateEditor, GateList, History } from "@/components/operations/registry";
import {
  decideIntegration, getAssignees, getIntegrationRegister, registerIntegration, setIntegrationGate, updateIntegration,
  type Assignee, type IntegrationAuthorization, type IntegrationInput, type IntegrationRecord, type IntegrationRegister, type Level,
} from "@/lib/api";

const EDITORS = new Set(["Admin", "Governance Ops Lead", "Risk Admin"]);
const AUTH: Record<IntegrationAuthorization, { label: string; tone: "ok" | "warn" | "bad" | "info" }> = {
  approved_scoped: { label: "Approved scoped", tone: "ok" }, pending: { label: "Pending", tone: "warn" },
  under_review: { label: "Under review", tone: "warn" }, on_hold: { label: "On hold", tone: "bad" },
  suspended: { label: "Suspended", tone: "bad" },
};
const HEALTH: Record<IntegrationRecord["health"], { label: string; tone: string }> = {
  operational: { label: "Healthy", tone: "text-ok" }, degraded: { label: "Degraded", tone: "text-accent-ink" },
  down: { label: "Unavailable", tone: "text-bad" }, not_configured: { label: "Not configured", tone: "text-muted" },
  not_enabled: { label: "Not enabled", tone: "text-muted" }, not_monitored: { label: "Not monitored", tone: "text-muted" },
};
const LEVEL_TONE: Record<Level, "bad" | "warn" | "info" | "ok"> = { critical: "bad", high: "warn", medium: "info", low: "ok" };
type TabKey = "all" | "accounting" | "ai_tools" | "evidence" | "source_feeds" | "infrastructure";
const PAGE_SIZE = 10;

export default function IntegrationsPage() {
  const { profile } = useAuth();
  const canEdit = EDITORS.has(profile?.role ?? "");
  const { data, error, loading, signedOut, reload } = useLiveData(
    "integrations", (token, signal) => getIntegrationRegister(token, signal), 30_000,
  );
  const people = useLiveData("ops-assignees", (token, signal) => getAssignees(token, signal), 20_000);
  const [tab, setTab] = useState<TabKey>("all");
  const [query, setQuery] = useState("");
  const [auth, setAuth] = useState("");
  const [risk, setRisk] = useState("");
  const [flow, setFlow] = useState("");
  const [region, setRegion] = useState("");
  const [page, setPage] = useState(0);
  const [selectedId, setSelectedId] = useState("");
  const [detailTab, setDetailTab] = useState<DetailTab>("overview");
  const [form, setForm] = useState<Partial<IntegrationInput> | null>(null);

  const items = useMemo(() => data?.integrations ?? [], [data]);
  const rows = useMemo(() => items.filter((i) => (tab === "all" || i.category === tab)
    && (!auth || i.authorization === auth) && (!risk || i.riskTier === risk) && (!flow || i.dataFlow === flow)
    && (!region || i.region === region)
    && (!query || `${i.ref} ${i.name} ${i.provider ?? ""} ${i.scopesRequested.join(" ")}`.toLowerCase().includes(query.toLowerCase()))),
  [items, tab, auth, risk, flow, region, query]);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const shown = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const selected = items.find((i) => i.id === selectedId) ?? rows[0];
  const regions = [...new Set(items.map((i) => i.region).filter(Boolean))];
  const reset = () => setPage(0);
  const select = (id: string, t: DetailTab = "overview") => { setSelectedId(id); setDetailTab(t); };

  return (
    <main className="flex-1 space-y-4 overflow-y-auto p-4">
      <OpsHero icon={Layers} title="Integrations"
        subtitle="Govern external connections, permissions, data flows, and Kriton's tool execution boundaries.">
        <p>Approved providers ≠ approved connections</p>
        <p>Healthy connections ≠ authorized AI access</p>
        <p>Every action is scoped, reviewed, and traceable</p>
      </OpsHero>
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />
      {data && (
        <>
          <Kpis data={data} />
          {data.detected.length > 0 && (
            <section className="flex flex-col gap-3 rounded-xl border border-accent/40 border-l-4 border-l-accent bg-accent/5 p-4">
              <p className="text-sm text-ink"><b>{data.detected.length} connection{data.detected.length === 1 ? " is" : "s are"} live in this deployment but not registered:</b> {data.detected.map((d) => d.name).join(", ")}.</p>
              {canEdit && <div className="flex flex-wrap gap-2">{data.detected.map((d) => (
                <Button key={d.healthKey} onClick={() => setForm({ name: d.name, category: d.category, health_key: d.healthKey, data_flow: "outbound" })}>Register {d.name}</Button>
              ))}</div>}
            </section>
          )}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <PillTabs label="Connection categories" active={tab} onChange={(t) => { setTab(t); reset(); }} tabs={[
              { key: "all", label: "All connections" }, { key: "accounting", label: "Accounting systems" },
              { key: "ai_tools", label: "AI tools" }, { key: "evidence", label: "Evidence & documents" },
              { key: "source_feeds", label: "Source feeds" }, { key: "infrastructure", label: "Infrastructure" }]} />
            {canEdit && <Button variant="primary" onClick={() => setForm({ category: tab === "all" ? "accounting" : tab })}>+ Add integration</Button>}
          </div>
          {form && <IntegrationForm initial={form} data={data} people={people.data ?? []}
            onDone={(id) => { setForm(null); if (id) select(id); reload(); }} />}
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_440px]">
            <Panel title="Connection register" meta={`${rows.length} shown / ${items.length} records`}>
              <div className="mb-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_auto]">
                <label className="relative">
                  <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
                  <input className={`${inputClass} pl-9`} placeholder="Search connection, provider, scope or integration ID…" value={query} onChange={(e) => { setQuery(e.target.value); reset(); }} />
                </label>
                <Button onClick={() => { setQuery(""); setAuth(""); setRisk(""); setFlow(""); setRegion(""); reset(); }}>Clear</Button>
              </div>
              <div className="mb-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                <select aria-label="Status" className={inputClass} value={auth} onChange={(e) => { setAuth(e.target.value); reset(); }}>
                  <option value="">All statuses</option>{Object.entries(AUTH).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
                </select>
                <select aria-label="Risk tier" className={inputClass} value={risk} onChange={(e) => { setRisk(e.target.value); reset(); }}>
                  <option value="">All risk tiers</option>{["critical", "high", "medium", "low"].map((l) => <option key={l} value={l}>{humanize(l)}</option>)}
                </select>
                <select aria-label="Data flow" className={inputClass} value={flow} onChange={(e) => { setFlow(e.target.value); reset(); }}>
                  <option value="">All directions</option>{["inbound", "outbound", "bidirectional"].map((f) => <option key={f} value={f}>{humanize(f)}</option>)}
                </select>
                <select aria-label="Region" className={inputClass} value={region} onChange={(e) => { setRegion(e.target.value); reset(); }}>
                  <option value="">All regions</option>{regions.map((r) => <option key={r}>{r}</option>)}
                </select>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[760px] text-left text-sm">
                  <thead className="bg-soft text-xs text-muted">
                    <tr>{["ID", "Connection", "Category", "Authorization", "Health", "Flow", "Risk"].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr>
                  </thead>
                  <tbody>
                    {shown.map((i) => (
                      <tr key={i.id} onClick={() => select(i.id)} aria-selected={selected?.id === i.id}
                        className={`cursor-pointer border-b border-line hover:bg-soft ${selected?.id === i.id ? "bg-info/5" : ""}`}>
                        <td className="px-3 py-2.5 font-semibold text-info">{i.ref}</td>
                        <td className="px-3 py-2.5 font-semibold text-ink">{i.name}</td>
                        <td className="px-3 py-2.5 text-ink">{i.categoryLabel}</td>
                        <td className="px-3 py-2.5"><Badge tone={AUTH[i.authorization].tone}>{AUTH[i.authorization].label}</Badge></td>
                        <td className={`px-3 py-2.5 ${HEALTH[i.health].tone}`}>{HEALTH[i.health].label}</td>
                        <td className="px-3 py-2.5 text-ink">{humanize(i.dataFlow)}</td>
                        <td className="px-3 py-2.5"><Badge tone={LEVEL_TONE[i.riskTier]}>{humanize(i.riskTier)}</Badge></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!shown.length && (
                  <EmptyState icon={Plug} title={items.length ? "No connections match these filters" : "No connections registered yet"}>
                    {items.length ? null : "Register each system Kriton connects to, its scopes and its owner. A connection stays disabled until every release gate passes."}
                  </EmptyState>
                )}
              </div>
              <div className="mt-3 flex items-center justify-between text-xs text-muted">
                <span>Access-controlled, tenant-filtered register</span>
                <span className="flex gap-1">
                  <button aria-label="Previous page" disabled={page === 0} onClick={() => setPage(page - 1)} className="h-7 w-7 rounded border border-line disabled:opacity-40">‹</button>
                  <span className="grid h-7 min-w-7 place-items-center rounded bg-hero px-2 font-bold text-white">{page + 1}</span>
                  <button aria-label="Next page" disabled={page >= pages - 1} onClick={() => setPage(page + 1)} className="h-7 w-7 rounded border border-line disabled:opacity-40">›</button>
                </span>
              </div>
            </Panel>
            {selected
              ? <IntegrationDetail key={selected.id} i={selected} data={data} canEdit={canEdit} people={people.data ?? []}
                  tab={detailTab} setTab={setDetailTab} onChanged={reload} />
              : <Panel title="Connection"><EmptyState title="Select a connection" /></Panel>}
          </div>
          <BottomPanels data={data} onSelect={select} onRefresh={reload} onRegister={canEdit ? () => setForm({ category: "accounting" }) : undefined} />
        </>
      )}
    </main>
  );
}

function Kpis({ data }: { data: IntegrationRegister }) {
  const s = data.summary;
  return (
    <KpiRow>
      <KpiTile icon={Layers} value={s.registered} label="Registered integrations" hint="This workspace's register" />
      <KpiTile icon={BadgeCheck} tone="ok" value={s.approved} label="Approved & active" hint="Restricted to approved scope" />
      <KpiTile icon={Clock3} tone="warn" value={s.pending} label="Pending authorization" hint="Not available to Kriton" />
      <KpiTile icon={AlertTriangle} tone={s.degraded ? "bad" : "ok"} value={s.degraded} label="Degraded" hint="Remediation required" />
      <KpiTile icon={Ban} tone={s.blocked ? "bad" : "ok"} value={s.blocked} label="On hold / suspended" hint="Enforced routing blocks" />
      <KpiTile icon={ShieldAlert} tone={s.scopeExceptions ? "warn" : "ok"} value={s.scopeExceptions} label="Scope exceptions" hint="Requested beyond approved scope" />
    </KpiRow>
  );
}

type DetailTab = "overview" | "permissions" | "health" | "gates" | "activity";

function IntegrationDetail({ i, data, canEdit, people, tab, setTab, onChanged }: {
  i: IntegrationRecord; data: IntegrationRegister; canEdit: boolean; people: Assignee[];
  tab: DetailTab; setTab: (t: DetailTab) => void; onChanged: () => void;
}) {
  const [note, setNote] = useState("");
  const [scopes, setScopes] = useState({ requested: i.scopesRequested.join(", "), approved: i.scopesApproved.join(", ") });
  const { busy, error, run } = useMutation();
  const allPass = i.gatesPassed === i.gatesTotal;
  const decide = (d: IntegrationAuthorization) => run(d, (t) => decideIntegration(t, i.id, d, note)).then((ok) => { if (ok) { setNote(""); onChanged(); } });
  const split = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

  return (
    <Panel title={i.name} meta={i.ref} action={<Badge tone={AUTH[i.authorization].tone}>{AUTH[i.authorization].label}</Badge>}>
      <p className="-mt-2 mb-3 text-xs text-muted">{i.provider ?? "No provider linked"} · {i.categoryLabel}</p>
      <PillTabs label="Connection detail" active={tab} onChange={setTab} tabs={[
        { key: "overview", label: "Overview" }, { key: "permissions", label: "Permissions" }, { key: "health", label: "Health" },
        { key: "gates", label: "Release gates" }, { key: "activity", label: "Activity", count: i.history.length }]} />
      <div className="mt-4 space-y-4">
        {tab === "overview" && (
          <>
            {i.authorization !== "approved_scoped" && (
              <div className="rounded-lg border border-bad/30 bg-bad/5 p-3">
                <p className="text-sm font-bold text-bad">ROUTING RESTRICTION ACTIVE</p>
                <p className="text-sm text-ink">Kriton cannot use this connection until every release gate passes and a second person authorizes it.</p>
              </div>
            )}
            <DetailRows rows={[
              ["Data direction", humanize(i.dataFlow)], ["Region", i.region || "Not recorded"],
              ["Authentication", i.authMethod || "Not recorded"],
              ["Scopes", i.scopesRequested.length ? `Requested: ${i.scopesRequested.join(", ")}` : "None recorded"],
              ["Accountable owner", i.owner ?? "Unassigned"],
              ["Sync / activity", i.healthCheckedAt ? `Checked ${timeAgo(i.healthCheckedAt)}` : "Not active"],
              ["Health", HEALTH[i.health].label],
            ]} />
            <GateList gates={i.gates} title={`Mandatory release gates · ${i.gatesPassed}/${i.gatesTotal} passed`} />
          </>
        )}
        {tab === "permissions" && (
          <div className="space-y-3 text-sm">
            <label className="block"><span className="mb-1 block text-muted">Scopes requested (comma separated)</span>
              <input className={inputClass} disabled={!canEdit} value={scopes.requested} onChange={(e) => setScopes({ ...scopes, requested: e.target.value })} placeholder="read:ledger, write:journal" /></label>
            <label className="block"><span className="mb-1 block text-muted">Scopes approved</span>
              <input className={inputClass} disabled={!canEdit} value={scopes.approved} onChange={(e) => setScopes({ ...scopes, approved: e.target.value })} placeholder="read:ledger" /></label>
            {i.scopeException && <p className="text-bad">{i.gates.find((g) => g.key === "least_privilege")?.note}</p>}
            {canEdit && <Button busy={busy === "scopes"} onClick={() => run("scopes", (t) => updateIntegration(t, i.id, {
              scopes_requested: split(scopes.requested), scopes_approved: split(scopes.approved) })).then((ok) => ok && onChanged())}>Save scopes</Button>}
            <p className="text-xs text-muted">Changing scopes on an authorized connection sends it back for review.</p>
          </div>
        )}
        {tab === "health" && (
          <DetailRows rows={[
            ["Health", HEALTH[i.health].label], ["Detail", i.healthDetail],
            ["Live check", i.healthKey ?? "None linked"], ["Last checked", i.healthCheckedAt ? utcDate(i.healthCheckedAt) : "—"],
          ]} />
        )}
        {tab === "gates" && <GateEditor gates={i.gates} canEdit={canEdit} busy={busy}
          onSave={(key, status, n) => run(`gate-${key}`, (t) => setIntegrationGate(t, i.id, key, status, n)).then((ok) => ok && onChanged())} />}
        {tab === "activity" && <History entries={i.history} />}
        {tab === "overview" && canEdit && (
          <IntegrationForm initial={{ owner_user_id: i.ownerId }} recordId={i.id} data={data} people={people} ownerOnly onDone={() => onChanged()} />
        )}
        <ErrorNote message={error} />
        <div className="space-y-2 border-t border-line pt-3">
          {canEdit && <input className={inputClass} placeholder="Decision note (required to hold or suspend)" value={note} onChange={(e) => setNote(e.target.value)} />}
          <div className="grid grid-cols-3 gap-2">
            <Button onClick={() => setTab("health")}>Inspect connection</Button>
            <Button onClick={() => setTab("gates")}>Review change</Button>
            <Button variant="primary" disabled={!canEdit || !allPass || i.authorization === "approved_scoped"} busy={busy === "approved_scoped"}
              onClick={() => decide("approved_scoped")} title={allPass ? "Must be someone other than the person who registered it" : "Every release gate must pass first"}>Enable connector</Button>
          </div>
          {canEdit && i.authorization !== "on_hold" && i.authorization !== "suspended" && (
            <div className="flex gap-2">
              <Button variant="danger" busy={busy === "on_hold"} onClick={() => decide("on_hold")}>Put on hold</Button>
              <Button variant="danger" busy={busy === "suspended"} onClick={() => decide("suspended")}>Suspend</Button>
            </div>
          )}
          {canEdit && (i.authorization === "on_hold" || i.authorization === "suspended") && (
            <Button busy={busy === "under_review"} onClick={() => decide("under_review")}>Return to review</Button>
          )}
        </div>
      </div>
    </Panel>
  );
}

function IntegrationForm({ initial, recordId, data, people, ownerOnly = false, onDone }: {
  initial: Partial<IntegrationInput>; recordId?: string; data: IntegrationRegister; people: Assignee[];
  ownerOnly?: boolean; onDone: (id?: string) => void;
}) {
  const [v, setV] = useState<Partial<IntegrationInput>>(initial);
  const { busy, error, run } = useMutation();
  const set = (k: keyof IntegrationInput) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value || null });
  const field = (label: string, node: React.ReactNode) => <label className="block text-sm"><span className="mb-1 block text-muted">{label}</span>{node}</label>;
  const owner = field("Accountable owner", <select className={inputClass} value={v.owner_user_id ?? ""} onChange={set("owner_user_id")}>
    <option value="">Unassigned</option>{people.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.role}</option>)}</select>);
  if (ownerOnly) {
    return (
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-end gap-2">
        {owner}
        <Button busy={busy === "save"} disabled={(v.owner_user_id ?? null) === (initial.owner_user_id ?? null)}
          onClick={() => run("save", (t) => updateIntegration(t, recordId!, { owner_user_id: v.owner_user_id ?? null })).then((ok) => ok && onDone())}>Save owner</Button>
        <div className="col-span-2"><ErrorNote message={error} /></div>
      </div>
    );
  }
  const split = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
  return (
    <Panel title="Register a connection" meta="Starts pending, disabled until every release gate passes">
      <form className="grid gap-3 md:grid-cols-3" onSubmit={(e) => {
        e.preventDefault();
        run("save", async (t) => { const saved = await registerIntegration(t, v as IntegrationInput); onDone(saved.id); });
      }}>
        {field("Connection name", <input required minLength={2} className={inputClass} value={v.name ?? ""} onChange={set("name")} />)}
        {field("Category", <select className={inputClass} value={v.category ?? "accounting"} onChange={set("category")}>
          {Object.entries(data.categories).map(([k, label]) => <option key={k} value={k}>{label}</option>)}</select>)}
        {field("Provider (from Provider Register)", <select className={inputClass} value={v.provider_id ?? ""} onChange={set("provider_id")}>
          <option value="">None linked</option>{data.providers.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}</select>)}
        {field("Data flow", <select className={inputClass} value={v.data_flow ?? "inbound"} onChange={set("data_flow")}>
          {["inbound", "outbound", "bidirectional"].map((f) => <option key={f} value={f}>{humanize(f)}</option>)}</select>)}
        {field("Risk tier", <select className={inputClass} value={v.risk_tier ?? "medium"} onChange={set("risk_tier")}>
          {["critical", "high", "medium", "low"].map((l) => <option key={l} value={l}>{humanize(l)}</option>)}</select>)}
        {field("Region", <input className={inputClass} value={v.region ?? ""} onChange={set("region")} placeholder="e.g. UK / EU" />)}
        {field("Authentication", <input className={inputClass} value={v.auth_method ?? ""} onChange={set("auth_method")} placeholder="e.g. Service principal, OAuth" />)}
        {field("Scopes requested", <input className={inputClass} placeholder="read:ledger, write:journal"
          onChange={(e) => setV({ ...v, scopes_requested: split(e.target.value) })} />)}
        {owner}
        <div className="md:col-span-3"><ErrorNote message={error} /></div>
        <div className="flex gap-2 md:col-span-3">
          <Button type="submit" variant="primary" busy={busy === "save"}>Register connection</Button>
          <Button onClick={() => onDone()}>Cancel</Button>
        </div>
      </form>
    </Panel>
  );
}

function BottomPanels({ data, onSelect, onRefresh, onRegister }: {
  data: IntegrationRegister; onSelect: (id: string, tab?: DetailTab) => void; onRefresh: () => void; onRegister?: () => void;
}) {
  const s = data.summary;
  const total = Math.max(1, s.registered);
  const controls: [keyof IntegrationRegister["controls"], string][] = [
    ["least_privilege", "Least privilege"], ["secret_vault", "Secrets & authentication"],
    ["replay_idempotency", "Replay protection"], ["residency_privacy", "Residency & privacy"],
  ];
  const actionTone = { HOLD: "text-accent-ink", REVIEW: "text-info", BLOCK: "text-bad" };
  return (
    <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
      <Panel title="Connection authorization">
        <div className="space-y-3">
          <ProgressRow label="Approved & active" value={s.approved} total={total} tone="ok" right={`${s.approved} / ${s.registered}`} />
          <ProgressRow label="In review / on hold" value={s.pending + s.blocked} total={total} tone="warn" right={`${s.pending + s.blocked} / ${s.registered}`} />
          <ProgressRow label="Degraded" value={s.degraded} total={total} tone="bad" right={`${s.degraded} / ${s.registered}`} />
        </div>
      </Panel>
      <Panel title="Control effectiveness">
        <div className="space-y-3">
          {controls.map(([key, label]) => (
            <ProgressRow key={key} label={label} value={data.controls[key].passed} total={Math.max(1, data.controls[key].total)} tone="info"
              right={data.controls[key].total ? `${data.controls[key].passed} / ${data.controls[key].total}` : "—"} />
          ))}
          <p className="text-xs text-muted">Share of connections whose gate passes.</p>
        </div>
      </Panel>
      <Panel title="Connection exception queue">
        {data.exceptions.length ? (
          <ul className="space-y-2 text-sm">
            {data.exceptions.slice(0, 5).map((e) => (
              <li key={e.id} className="flex items-start justify-between gap-2">
                <button onClick={() => onSelect(e.id, "gates")} className="text-left">
                  <span className="block font-semibold text-ink hover:underline">{e.title}</span>
                  <span className="text-xs text-muted">{e.ref}</span>
                </button>
                <span className={`text-xs font-bold ${actionTone[e.action]}`}>{e.action}</span>
              </li>
            ))}
          </ul>
        ) : <p className="text-sm text-muted">No exceptions.</p>}
      </Panel>
      <Panel title="Quick actions">
        <div className="grid grid-cols-2 gap-2">
          <Button onClick={onRefresh}><RefreshCw size={14} /> Run health check</Button>
          <Button onClick={() => data.integrations[0] && onSelect(data.integrations[0].id, "permissions")}><ListChecks size={14} /> Review scopes</Button>
          <Link href="/audit-logs" className="inline-flex min-h-10 items-center justify-center gap-1.5 rounded-lg border border-line bg-panel text-sm font-semibold text-info hover:bg-soft"><FileSearch size={14} /> Audit evidence</Link>
          <Link href="/provider-register" className="inline-flex min-h-10 items-center justify-center gap-1.5 rounded-lg border border-line bg-panel text-sm font-semibold text-info hover:bg-soft"><Waypoints size={14} /> Providers</Link>
          {onRegister && <div className="col-span-2"><Button variant="primary" onClick={onRegister}>+ Register connection</Button></div>}
        </div>
      </Panel>
    </div>
  );
}
