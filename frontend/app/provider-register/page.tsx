"use client";

import { useMemo, useState } from "react";
import { Building2, CalendarClock, CheckCircle2, CircleAlert, Clock3, LayoutGrid, Search } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { useLiveData } from "@/components/overview/useLiveData";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import {
  Badge, Button, DetailRows, EmptyState, ErrorNote, KpiTile, OpsHero, Panel, PillTabs, ProgressRow,
  humanize, inputClass, useMutation, utcDate,
} from "@/components/operations/ui";
import { GateEditor, GateList, History } from "@/components/operations/registry";
import {
  decideProvider, getAssignees, getProviderRegister, registerProvider, setProviderGate, updateProvider,
  type Assignee, type Level, type ProviderDecision, type ProviderInput, type ProviderRecord,
  type ProviderRegister,
} from "@/lib/api";

const EDITORS = new Set(["Admin", "Governance Ops Lead", "Risk Admin"]);
const DECISION: Record<ProviderDecision, { label: string; tone: "ok" | "warn" | "bad" | "info" }> = {
  approved_scoped: { label: "Approved scoped", tone: "ok" }, conditional: { label: "Conditional", tone: "warn" },
  under_review: { label: "Under review", tone: "info" }, on_hold: { label: "On hold", tone: "bad" },
  suspended: { label: "Suspended", tone: "bad" },
};
const LEVEL_TONE: Record<Level, "bad" | "warn" | "info" | "ok"> = { critical: "bad", high: "warn", medium: "info", low: "ok" };
type TabKey = "all" | "ai_model" | "cloud_security" | "content" | "other";
const PAGE_SIZE = 10;

export default function ProviderRegisterPage() {
  const { profile } = useAuth();
  const canEdit = EDITORS.has(profile?.role ?? "");
  const { data, error, loading, signedOut, reload } = useLiveData(
    "provider-register", (token, signal) => getProviderRegister(token, signal), 30_000,
  );
  const people = useLiveData("ops-assignees", (token, signal) => getAssignees(token, signal), 20_000);
  const [tab, setTab] = useState<TabKey>("all");
  const [query, setQuery] = useState("");
  const [decision, setDecision] = useState("");
  const [criticality, setCriticality] = useState("");
  const [region, setRegion] = useState("");
  const [page, setPage] = useState(0);
  const [selectedId, setSelectedId] = useState("");
  const [form, setForm] = useState<Partial<ProviderInput> | null>(null);

  const providers = useMemo(() => data?.providers ?? [], [data]);
  const rows = useMemo(() => providers.filter((p) => (tab === "all" || p.category === tab)
    && (!decision || p.decision === decision) && (!criticality || p.criticality === criticality) && (!region || p.region === region)
    && (!query || `${p.ref} ${p.name} ${p.service} ${p.owner ?? ""}`.toLowerCase().includes(query.toLowerCase()))),
  [providers, tab, decision, criticality, region, query]);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const shown = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const selected = providers.find((p) => p.id === selectedId) ?? rows[0];
  const regions = [...new Set(providers.map((p) => p.region).filter(Boolean))];
  const reset = () => setPage(0);

  return (
    <main className="flex-1 space-y-4 overflow-y-auto p-4">
      <OpsHero icon={LayoutGrid} title="Provider Register"
        subtitle="External AI, cloud, knowledge and service-provider governance · Contractual rights • Data boundaries • Subprocessors • Resilience • Authorized use">
        <p>Approved for a defined purpose.</p><p>Controlled across jurisdictions.</p><p>Continuously reassessed.</p>
      </OpsHero>
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />
      {data && (
        <>
          <p className="flex flex-wrap justify-between gap-2 text-xs text-muted">
            <span><b className="text-ok">LIVE REGISTER</b> — records entered by your governance team; providers in use are detected from this deployment&apos;s configuration.</span>
            <span>Updated {utcDate(data.generatedAt)}</span>
          </p>
          <Kpis data={data} />
          {data.detected.length > 0 && (
            <section className="flex flex-col gap-3 rounded-xl border border-accent/40 border-l-4 border-l-accent bg-accent/5 p-4">
              <p className="text-sm text-ink"><b>{data.detected.length} provider{data.detected.length === 1 ? " is" : "s are"} in use but not registered.</b> This deployment is configured to call {data.detected.map((d) => d.name).join(", ")}, with no due-diligence record.</p>
              {canEdit && (
                <div className="flex flex-wrap gap-2">
                  {data.detected.map((d) => (
                    <Button key={d.configKey} onClick={() => setForm({ name: d.name, category: d.category, service: d.service, config_key: d.configKey, criticality: d.category === "ai_model" ? "critical" : "medium" })}>
                      Register {d.name}
                    </Button>
                  ))}
                </div>
              )}
            </section>
          )}
          {form && <ProviderForm initial={form} people={people.data ?? []} onDone={(id) => { setForm(null); if (id) setSelectedId(id); reload(); }} />}
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
            <Panel title="Provider register" meta={`${rows.length} shown / ${providers.length} records`}
              action={canEdit ? <Button variant="primary" onClick={() => setForm({ category: tab === "all" ? "ai_model" : tab })}>+ Register provider</Button> : undefined}>
              <PillTabs label="Provider categories" active={tab} onChange={(t) => { setTab(t); reset(); }} tabs={[
                { key: "all", label: "All providers" }, { key: "ai_model", label: "AI & model" },
                { key: "cloud_security", label: "Cloud & security" }, { key: "content", label: "Content licensors" },
                { key: "other", label: "Other services" }]} />
              <div className="my-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_auto]">
                <label className="relative">
                  <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
                  <input className={`${inputClass} pl-9`} placeholder="Search provider, service, ID or owner…" value={query} onChange={(e) => { setQuery(e.target.value); reset(); }} />
                </label>
                <Button onClick={() => { setQuery(""); setDecision(""); setCriticality(""); setRegion(""); reset(); }}>Clear</Button>
              </div>
              <div className="mb-3 grid gap-2 sm:grid-cols-3">
                <select aria-label="Decision" className={inputClass} value={decision} onChange={(e) => { setDecision(e.target.value); reset(); }}>
                  <option value="">All decisions</option>{Object.entries(DECISION).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
                </select>
                <select aria-label="Criticality" className={inputClass} value={criticality} onChange={(e) => { setCriticality(e.target.value); reset(); }}>
                  <option value="">All criticality tiers</option>{(["critical", "high", "medium", "low"] as Level[]).map((l) => <option key={l} value={l}>{humanize(l)}</option>)}
                </select>
                <select aria-label="Region" className={inputClass} value={region} onChange={(e) => { setRegion(e.target.value); reset(); }}>
                  <option value="">All data regions</option>{regions.map((r) => <option key={r}>{r}</option>)}
                </select>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[760px] text-left text-sm">
                  <thead className="bg-soft text-xs uppercase text-muted">
                    <tr>{["Provider ID", "Provider / service", "Category", "Decision", "Criticality", "Region", "Owner"].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr>
                  </thead>
                  <tbody>
                    {shown.map((p) => (
                      <tr key={p.id} onClick={() => setSelectedId(p.id)} aria-selected={selected?.id === p.id}
                        className={`cursor-pointer border-b border-line hover:bg-soft ${selected?.id === p.id ? "bg-info/5" : ""}`}>
                        <td className="px-3 py-2.5 font-semibold text-info">{p.ref}</td>
                        <td className="px-3 py-2.5"><span className="font-semibold text-ink">{p.name}</span>{p.inUse && <span className="ml-2 text-[10px] font-bold uppercase text-ok">in use</span>}</td>
                        <td className="px-3 py-2.5 text-ink">{p.service || p.categoryLabel}</td>
                        <td className="px-3 py-2.5"><Badge tone={DECISION[p.decision].tone}>{DECISION[p.decision].label}</Badge></td>
                        <td className="px-3 py-2.5"><Badge tone={LEVEL_TONE[p.criticality]}>{humanize(p.criticality)}</Badge></td>
                        <td className="px-3 py-2.5 text-ink">{p.region || "—"}</td>
                        <td className="px-3 py-2.5 text-ink">{p.owner ?? <span className="text-muted">Unassigned</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!shown.length && (
                  <EmptyState icon={Building2} title={providers.length ? "No providers match these filters" : "No providers registered yet"}>
                    {providers.length ? null : "Register each external provider this workspace relies on, then record its assurance gates."}
                  </EmptyState>
                )}
              </div>
              <div className="mt-3 flex items-center justify-between text-xs text-muted">
                <span>{rows.length} shown from {providers.length} records</span>
                <span className="flex gap-1">
                  <button aria-label="Previous page" disabled={page === 0} onClick={() => setPage(page - 1)} className="h-7 w-7 rounded border border-line disabled:opacity-40">‹</button>
                  <span className="grid h-7 min-w-7 place-items-center rounded bg-hero px-2 font-bold text-white">{page + 1}</span>
                  <button aria-label="Next page" disabled={page >= pages - 1} onClick={() => setPage(page + 1)} className="h-7 w-7 rounded border border-line disabled:opacity-40">›</button>
                </span>
              </div>
            </Panel>
            {selected
              ? <ProviderDetail key={selected.id} p={selected} canEdit={canEdit} people={people.data ?? []} onChanged={reload} />
              : <Panel title="Provider assurance"><EmptyState title="Select a provider" /></Panel>}
          </div>
          <BottomPanels data={data} selected={selected} onSelect={setSelectedId} />
        </>
      )}
    </main>
  );
}

function Kpis({ data }: { data: ProviderRegister }) {
  const s = data.summary;
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <KpiTile icon={LayoutGrid} value={s.registered} label="Registered providers" hint="Across every service category" />
      <KpiTile icon={CheckCircle2} tone="ok" value={s.approved} label="Approved for scoped use" hint="Permitted purpose & region only" />
      <KpiTile icon={Clock3} tone="warn" value={s.inReview} label="Conditional / under review" hint={`${s.conditional} conditional · ${s.underReview} in assessment`} />
      <KpiTile icon={CircleAlert} tone={s.blocked ? "bad" : "ok"} value={s.blocked} label="Suspended or on hold" hint="Production use blocked" />
      <KpiTile icon={CalendarClock} tone={s.reviewActions ? "warn" : "ok"} value={s.reviewActions} label="Renewal / review actions" hint="Reviews due within 90 days" />
    </div>
  );
}

type DetailTab = "overview" | "controls" | "details" | "history";

function ProviderDetail({ p, canEdit, people, onChanged }: { p: ProviderRecord; canEdit: boolean; people: Assignee[]; onChanged: () => void }) {
  const [tab, setTab] = useState<DetailTab>("overview");
  const [note, setNote] = useState("");
  const { busy, error, run } = useMutation();
  const allPass = p.gatesPassed === p.gatesTotal;
  const blocked = p.decision === "on_hold" || p.decision === "suspended";
  const decide = (d: ProviderDecision) => run(d, (t) => decideProvider(t, p.id, d, note)).then((ok) => { if (ok) { setNote(""); onChanged(); } });

  return (
    <Panel title="Provider assurance" meta="Selected record" action={p.inUse ? <Badge tone="ok">● In use</Badge> : <Badge tone="neutral">Not configured</Badge>}>
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="grid h-11 w-11 place-items-center rounded-lg bg-hero text-accent"><LayoutGrid size={20} /></span>
          <div><p className="text-lg font-extrabold text-ink">{p.name}</p><p className="text-xs text-muted">{p.ref} · {p.service || p.categoryLabel}</p></div>
        </div>
        <Badge tone={DECISION[p.decision].tone}>{DECISION[p.decision].label}</Badge>
      </div>
      <PillTabs label="Provider detail" active={tab} onChange={setTab} tabs={[
        { key: "overview", label: "Overview" }, { key: "controls", label: "Controls" },
        { key: "details", label: "Details" }, { key: "history", label: "History", count: p.history.length }]} />
      <div className="mt-4 space-y-4">
        {tab === "overview" && (
          <>
            {p.decision !== "approved_scoped" && (
              <div className={`rounded-lg border-l-4 p-3 ${blocked ? "border-l-bad bg-bad/5" : "border-l-accent bg-accent/5"}`}>
                <p className={`text-sm font-bold ${blocked ? "text-bad" : "text-accent-ink"}`}>{blocked ? "PRODUCTION USE BLOCKED" : "NOT YET APPROVED"}</p>
                <p className="text-sm text-ink">{blocked ? "Production data transfer blocked" : `${p.gatesTotal - p.gatesPassed} assurance gate(s) still open`}</p>
              </div>
            )}
            <DetailRows rows={[
              ["Risk tier", humanize(p.criticality)], ["Approved / requested use", p.approvedUse || "Not recorded"],
              ["Data classification", p.dataClassification || "Not recorded"], ["Processing region", p.region || "Not recorded"],
              ["Responsible owner", p.owner ?? "Unassigned"], ["Decision recorded", p.decidedAt ? `${utcDate(p.decidedAt)} · ${p.decidedBy}` : "—"],
              ["Next review", p.nextReviewAt ? utcDate(p.nextReviewAt).split(" · ")[0] : "Not scheduled"],
              ["Contract state", humanize(p.contractState)],
            ]} />
            <GateList gates={p.gates} title={`Mandatory assurance gates · ${p.gatesPassed}/${p.gatesTotal} passed`} />
          </>
        )}
        {tab === "controls" && <GateEditor gates={p.gates} canEdit={canEdit} onSave={(key, status, n) =>
          run(`gate-${key}`, (t) => setProviderGate(t, p.id, key, status, n)).then((ok) => ok && onChanged())} busy={busy} />}
        {tab === "details" && <ProviderForm initial={toInput(p)} recordId={p.id} people={people} readOnly={!canEdit} onDone={() => onChanged()} />}
        {tab === "history" && <History entries={p.history} />}
        <ErrorNote message={error} />
        {canEdit && tab !== "details" && (
          <div className="space-y-2 border-t border-line pt-3">
            <input className={inputClass} placeholder="Decision note (required to hold, suspend or approve conditionally)" value={note} onChange={(e) => setNote(e.target.value)} />
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => setTab("controls")}>Open due diligence</Button>
              <Button busy={busy === "conditional"} onClick={() => decide("conditional")}>Approve conditionally</Button>
              <Button variant="danger" busy={busy === "on_hold"} onClick={() => decide("on_hold")}>Put on hold</Button>
              <Button variant="primary" disabled={!allPass} busy={busy === "approved_scoped"} onClick={() => decide("approved_scoped")}
                title={allPass ? "Must be someone other than the person who registered it" : "Every gate must pass first"}>Approve use</Button>
            </div>
          </div>
        )}
      </div>
    </Panel>
  );
}

function toInput(p: ProviderRecord): Partial<ProviderInput> {
  return {
    name: p.name, category: p.category, service: p.service, criticality: p.criticality, region: p.region,
    approved_use: p.approvedUse, data_classification: p.dataClassification, contract_state: p.contractState,
    owner_user_id: p.ownerId, next_review_at: p.nextReviewAt,
  };
}

function ProviderForm({ initial, recordId, people, readOnly = false, onDone }: {
  initial: Partial<ProviderInput>; recordId?: string; people: Assignee[]; readOnly?: boolean; onDone: (id?: string) => void;
}) {
  const [v, setV] = useState<Partial<ProviderInput>>(initial);
  const { busy, error, run } = useMutation();
  const set = (k: keyof ProviderInput) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value || null });
  const field = (label: string, node: React.ReactNode) => <label className="block text-sm"><span className="mb-1 block text-muted">{label}</span>{node}</label>;
  const body = (
    <form className="grid gap-3 md:grid-cols-2" onSubmit={(e) => {
      e.preventDefault();
      const payload = { ...v, next_review_at: v.next_review_at ? new Date(v.next_review_at).toISOString() : null } as ProviderInput;
      run("save", async (t) => {
        const saved = recordId ? await updateProvider(t, recordId, payload) : await registerProvider(t, payload);
        onDone(saved.id);
      });
    }}>
      {field("Provider name", <input required minLength={2} disabled={readOnly} className={inputClass} value={v.name ?? ""} onChange={set("name")} />)}
      {field("Category", <select disabled={readOnly} className={inputClass} value={v.category ?? "ai_model"} onChange={set("category")}>
        <option value="ai_model">AI & model</option><option value="cloud_security">Cloud & security</option>
        <option value="content">Content licensors</option><option value="other">Other services</option></select>)}
      {field("Service provided", <input disabled={readOnly} className={inputClass} value={v.service ?? ""} onChange={set("service")} placeholder="e.g. AI inference" />)}
      {field("Criticality", <select disabled={readOnly} className={inputClass} value={v.criticality ?? "medium"} onChange={set("criticality")}>
        {["critical", "high", "medium", "low"].map((l) => <option key={l} value={l}>{humanize(l)}</option>)}</select>)}
      {field("Processing region", <input disabled={readOnly} className={inputClass} value={v.region ?? ""} onChange={set("region")} placeholder="e.g. UK / EU" />)}
      {field("Approved / requested use", <input disabled={readOnly} className={inputClass} value={v.approved_use ?? ""} onChange={set("approved_use")} />)}
      {field("Data classification", <input disabled={readOnly} className={inputClass} value={v.data_classification ?? ""} onChange={set("data_classification")} placeholder="e.g. Confidential" />)}
      {field("Contract state", <select disabled={readOnly} className={inputClass} value={v.contract_state ?? "none"} onChange={set("contract_state")}>
        {["none", "draft", "under_negotiation", "executed", "expired"].map((c) => <option key={c} value={c}>{humanize(c)}</option>)}</select>)}
      {field("Responsible owner", <select disabled={readOnly} className={inputClass} value={v.owner_user_id ?? ""} onChange={set("owner_user_id")}>
        <option value="">Unassigned</option>{people.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.role}</option>)}</select>)}
      {field("Next review", <input type="date" disabled={readOnly} className={inputClass} value={(v.next_review_at ?? "").slice(0, 10)} onChange={set("next_review_at")} />)}
      <div className="md:col-span-2"><ErrorNote message={error} /></div>
      {!readOnly && <div className="flex gap-2 md:col-span-2">
        <Button type="submit" variant="primary" busy={busy === "save"}>{recordId ? "Save changes" : "Register provider"}</Button>
        {!recordId && <Button onClick={() => onDone()}>Cancel</Button>}
      </div>}
    </form>
  );
  return recordId ? body : <Panel title="Register a provider" meta="Starts under review with every gate open">{body}</Panel>;
}

function BottomPanels({ data, selected, onSelect }: { data: ProviderRegister; selected?: ProviderRecord; onSelect: (id: string) => void }) {
  const open = selected ? selected.gates.filter((g) => g.status !== "pass").length : 0;
  const priority = data.providers.filter((p) => p.decision !== "approved_scoped")
    .sort((a, b) => ["critical", "high", "medium", "low"].indexOf(a.criticality) - ["critical", "high", "medium", "low"].indexOf(b.criticality)).slice(0, 5);
  const r = data.resilience;
  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <Panel title="Assurance requirements · selected provider">
        {selected ? (
          <div className="space-y-3">
            <ProgressRow label="Passed mandatory checks" value={selected.gatesPassed} total={selected.gatesTotal} tone="ok" />
            <ProgressRow label="Open verification checks" value={open} total={selected.gatesTotal} tone="warn" />
            <ProgressRow label="Production data transfer" value={selected.decision === "approved_scoped" ? 1 : 1} total={1}
              tone={selected.decision === "approved_scoped" ? "ok" : "bad"} right={selected.decision === "approved_scoped" ? "Allowed" : "Blocked"} />
            <p className="text-xs text-muted">Mandatory controls govern eligible scope, provider routing and downstream service use.</p>
          </div>
        ) : <p className="text-sm text-muted">Select a provider.</p>}
      </Panel>
      <Panel title="Priority provider reviews">
        {priority.length ? (
          <ul className="divide-y divide-line text-sm">
            {priority.map((p) => {
              const gate = p.gates.find((g) => g.status === "fail") ?? p.gates.find((g) => g.status === "open");
              return (
                <li key={p.id} className="flex items-center justify-between gap-2 py-2">
                  <button onClick={() => onSelect(p.id)} className="text-left font-semibold text-ink hover:underline">{p.name}</button>
                  <span className="flex items-center gap-2 text-xs"><span className="text-muted">{gate?.label ?? "Decision"}</span>
                    <b className={DECISION[p.decision].tone === "bad" ? "text-bad" : "text-accent-ink"}>{DECISION[p.decision].label.toUpperCase()}</b></span>
                </li>
              );
            })}
          </ul>
        ) : <p className="text-sm text-muted">Every registered provider is approved.</p>}
        <p className="mt-2 text-xs text-muted">Actions route to named owners; approval requires a second person.</p>
      </Panel>
      <Panel title="Concentration & resilience">
        <div className="space-y-3">
          <ProgressRow label="Critical dependencies" value={r.critical} total={Math.max(1, data.summary.registered)} tone="info" right={r.critical} />
          <ProgressRow label="Fallback documented" value={r.fallbackDocumented} total={Math.max(1, r.critical)} tone="ok" right={`${r.fallbackDocumented} / ${r.critical}`} />
          <ProgressRow label="Untested exits" value={r.untestedExits} total={Math.max(1, r.critical)} tone="warn" right={r.untestedExits} />
          <p className="text-xs text-muted">From each critical provider&apos;s exit-and-fallback gate.</p>
        </div>
      </Panel>
    </div>
  );
}
