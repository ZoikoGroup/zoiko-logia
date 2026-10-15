"use client";

import Link from "next/link";
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Activity, AlertTriangle, ArrowDownToLine, CreditCard, DollarSign, Gauge, Layers, TrendingUp } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { useLiveData } from "@/components/overview/useLiveData";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import { cssVar } from "@/lib/css-var";
import {
  Badge, Breadcrumb, Button, DetailRows, EmptyState, ErrorNote, KpiRow, KpiTile, OpsHero, Panel, PillTabs, ProgressRow,
  humanize, inputClass, useMutation, utcDate,
} from "@/components/operations/ui";
import {
  addBillingAdjustment, closeBillingPeriod, decideBillingAdjustment, decideBillingPlan, downloadBillingReport,
  getBillingOverview, markStatementPaid, proposeBillingPlan,
  type BillingOverview, type BillingPlan, type ChargeLine,
} from "@/lib/api";

type TabKey = "overview" | "ledger" | "allocation" | "invoices" | "contract" | "controls" | "audit";
const STATUS: Record<ChargeLine["status"], { label: string; tone: "ok" | "warn" | "bad" | "info" | "neutral" }> = {
  contracted: { label: "Contracted", tone: "info" }, measured: { label: "Measured", tone: "ok" },
  disputed: { label: "Disputed", tone: "bad" }, waived: { label: "Waived", tone: "neutral" },
  unpriced: { label: "No rate card", tone: "neutral" }, approved_credit: { label: "Approved credit", tone: "ok" },
};

function money(cents: number, currency = "USD", digits = 0): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: digits, minimumFractionDigits: digits }).format(cents / 100);
}
function qty(n: number): string {
  return n >= 100 ? Math.round(n).toLocaleString() : n.toLocaleString(undefined, { maximumFractionDigits: 3 });
}
function monthLabel(p: string): string {
  const [y, m] = p.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleString("en-US", { month: "short", timeZone: "UTC" });
}
const meterCode = (key: string, meters: BillingOverview["meters"]) =>
  key === "commitment" ? "MTR-100" : key === "credit" ? "MTR-900" : `MTR-${101 + meters.findIndex((m) => m.key === key)}`;

export default function BillingUsagePage() {
  const { profile } = useAuth();
  const { data, error, loading, signedOut, reload } = useLiveData("billing-overview", (token, signal) => getBillingOverview(token, signal), 60_000);
  const [tab, setTab] = useState<TabKey>("overview");
  const [selectedKey, setSelectedKey] = useState("");
  const { busy, error: dlError, run } = useMutation();
  const lines = data?.current.lines ?? [];
  const selected = lines.find((l) => l.key === selectedKey) ?? lines.find((l) => l.key !== "commitment") ?? lines[0];
  const currency = data?.current.currency ?? "USD";

  return (
    <main className="flex-1 space-y-4 overflow-y-auto p-4">
      <Breadcrumb section="Administration" page="Billing & Usage" />
      <OpsHero icon={CreditCard} title="Billing & Usage"
        subtitle="Trace every charge. Govern AI consumption. Control tenant spending · Subscription • Metering evidence • Client allocation • Invoice assurance">
        <p><Badge tone="ok">● LIVE METERING · {data ? data.period : ""}</Badge></p>
        <p>Usage measured from the audit ledger</p>
        <p>Priced by the approved rate card</p>
      </OpsHero>
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />
      {data && (
        <>
          {!data.summary.priced && (
            <section className="flex flex-col gap-2 rounded-xl border border-accent/40 border-l-4 border-l-accent bg-accent/5 p-4 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm text-ink"><b className="text-accent-ink">No approved plan yet.</b> Usage below is measured from real activity, but nothing is priced until an Admin proposes a plan and rate card and a second Admin approves it.</p>
              <Button onClick={() => setTab("contract")}>Set up plan</Button>
            </section>
          )}
          <Kpis data={data} />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <PillTabs label="Billing views" active={tab} onChange={setTab} tabs={[
              { key: "overview", label: "Overview" }, { key: "ledger", label: "Usage Ledger" }, { key: "allocation", label: "Cost Allocation" },
              { key: "invoices", label: "Invoices", count: data.statements.length }, { key: "contract", label: "Contract & Entitlements" },
              { key: "controls", label: "Spend Controls" }, { key: "audit", label: "Audit Trail" }]} />
            <Button variant="primary" busy={busy === "report"} onClick={() => run("report", (t) => downloadBillingReport(t, data.period))}><ArrowDownToLine size={14} /> Request Report</Button>
          </div>
          <ErrorNote message={dlError} />

          {tab === "overview" && (
            <>
              <div className="grid gap-4 xl:grid-cols-3">
                <TrendPanel data={data} />
                <CompositionPanel data={data} />
                <PlanPanel data={data} onContract={() => setTab("contract")} />
              </div>
              <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
                <Register data={data} selectedKey={selected?.key} onSelect={setSelectedKey} />
                {selected && <Inspector key={selected.key} line={selected} data={data} onChanged={reload} />}
              </div>
              <div className="grid gap-4 xl:grid-cols-3">
                <AllocationPanel data={data} />
                <InvoicesPanel data={data} compact selfId={profile?.id} onChanged={reload} />
                <BudgetPanel data={data} />
              </div>
            </>
          )}
          {tab === "ledger" && <LedgerPanel data={data} />}
          {tab === "allocation" && <AllocationPanel data={data} full />}
          {tab === "invoices" && <InvoicesPanel data={data} selfId={profile?.id} onChanged={reload} />}
          {tab === "contract" && <ContractPanel data={data} selfId={profile?.id} onChanged={reload} />}
          {tab === "controls" && <ControlsPanel data={data} selfId={profile?.id} onChanged={reload} />}
          {tab === "audit" && <AuditPanel data={data} />}
          <p className="text-right text-xs text-muted">Amounts in {currency} before tax · month-to-date figures are estimates until the month is closed</p>
        </>
      )}
    </main>
  );
}

function Kpis({ data }: { data: BillingOverview }) {
  const s = data.summary;
  const c = data.current.currency;
  return (
    <KpiRow>
      <KpiTile icon={DollarSign} value={s.priced ? money(s.estimatedCents, c) : "—"} label="Estimated charges · MTD" hint="Before applicable taxes" />
      <KpiTile icon={Layers} tone="warn" value={s.priced ? money(s.commitmentCents, c) : "—"} label="Monthly commitment" hint="Contracted plan" />
      <KpiTile icon={TrendingUp} tone="info" value={s.priced ? money(s.variableCents, c) : "—"} label="Variable metered usage" hint="Overage before credits" />
      <KpiTile icon={Activity} tone="warn" value={s.interactions.toLocaleString()} label="Kriton interactions" hint="Questions this month" />
      <KpiTile icon={Gauge} tone={s.budgetUsedPct !== null && s.budgetUsedPct > 90 ? "bad" : "ok"} value={s.budgetUsedPct === null ? "—" : `${s.budgetUsedPct}%`}
        label="Budget utilized" hint={s.softBudgetCents ? `${money(s.softBudgetCents, c)} soft threshold` : "No budget set"} />
      <KpiTile icon={AlertTriangle} tone={s.openDisputes ? "bad" : "ok"} value={s.openDisputes} label="Metering exceptions" hint={s.excludedCents ? `${money(s.excludedCents, c)} excluded from accrual` : "Excluded from accrual"} />
    </KpiRow>
  );
}

function TrendPanel({ data }: { data: BillingOverview }) {
  const rows = data.trend.map((t) => ({ month: monthLabel(t.period), total: t.totalCents / 100, interactions: t.interactions, estimate: t.estimate }));
  const has = data.trend.some((t) => t.priced);
  const color = cssVar("--chart-1", "#0a6f96");
  const muted = cssVar("--muted", "#637083");
  const line = cssVar("--line", "#d8dde5");
  return (
    <Panel title="Cost & Consumption Trend" meta="Last six months">
      {has ? (
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -6 }}>
            <CartesianGrid stroke={line} strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="month" tick={{ fill: muted, fontSize: 11 }} stroke={line} />
            <YAxis tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} tick={{ fill: muted, fontSize: 11 }} stroke={line} width={46} />
            <Tooltip formatter={(v: unknown) => (typeof v === "number" ? money(v * 100, data.current.currency) : String(v))}
              labelFormatter={(l, p) => `${l} · ${p?.[0]?.payload?.interactions?.toLocaleString?.() ?? 0} Kriton interactions${p?.[0]?.payload?.estimate ? " (estimate)" : ""}`} />
            <Bar dataKey="total" name="Charges" fill={color} radius={[4, 4, 0, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      ) : <EmptyState icon={TrendingUp} title="No priced months yet">Charges appear here once a plan is approved.</EmptyState>}
      <ul className="mt-2 grid grid-cols-6 text-center text-[11px] text-muted">{data.trend.map((t) => <li key={t.period}>{t.interactions.toLocaleString()}<br />questions</li>)}</ul>
      <p className="mt-2 text-xs text-muted">The current month is a month-to-date estimate, not a finalized statement.</p>
    </Panel>
  );
}

function CompositionPanel({ data }: { data: BillingOverview }) {
  const lines = data.current.lines.filter((l) => l.amountCents !== 0 || l.key === "commitment");
  const max = Math.max(1, ...lines.map((l) => Math.abs(l.amountCents)));
  return (
    <Panel title="Charge Composition" meta={data.summary.priced ? `Reconciles to ${money(data.current.totalCents, data.current.currency)}` : "No rate card"}>
      {data.summary.priced ? (
        <div className="space-y-3">{lines.map((l) => (
          <ProgressRow key={l.key} label={l.label} value={Math.abs(l.amountCents)} total={max}
            tone={l.amountCents < 0 ? "ok" : l.key === "commitment" ? "info" : l.excluded ? "bad" : "warn"} right={money(l.amountCents, data.current.currency)} />))}
          <p className="text-xs text-muted">Versioned rates; credits never overwrite usage receipts.</p>
        </div>
      ) : <p className="text-sm text-muted">Usage is measured; it is priced once a plan is approved.</p>}
    </Panel>
  );
}

function PlanPanel({ data, onContract }: { data: BillingOverview; onContract: () => void }) {
  const p = data.plan;
  return (
    <Panel title="Subscription & Entitlements" action={p ? <Badge tone="ok">ACTIVE · v{p.version}</Badge> : <Badge tone="neutral">NOT SET</Badge>}>
      {p ? (
        <>
          <div className="mb-3 flex items-center justify-between"><p className="text-lg font-extrabold text-ink">{p.name}</p><Button onClick={onContract}>View contract</Button></div>
          <DetailRows rows={[
            ["Billing currency", p.currency], ["Billing cycle", "Monthly"], ["Base commitment", money(p.commitmentCents, p.currency)],
            ["Included Kriton interactions", (p.included.kriton_interactions ?? 0).toLocaleString()],
            ["Contract version", `v${p.version}`], ["Pricing effective", p.effectiveFrom], ["Approved by", p.decidedBy ?? "—"],
          ]} />
          <p className="mt-2 text-xs text-muted">Plan changes need a second Admin&apos;s approval and take effect from a chosen month.</p>
        </>
      ) : <EmptyState title="No approved plan">Propose a plan and rate card under Contract &amp; Entitlements.</EmptyState>}
    </Panel>
  );
}

function Register({ data, selectedKey, onSelect }: { data: BillingOverview; selectedKey?: string; onSelect: (k: string) => void }) {
  const [query, setQuery] = useState("");
  const [type, setType] = useState("");
  const rows = data.current.lines.filter((l) => (!type || (type === "usage" ? data.meters.some((m) => m.key === l.key) : l.key === type))
    && (!query || `${l.label} ${l.key} ${meterCode(l.key, data.meters)}`.toLowerCase().includes(query.toLowerCase())));
  return (
    <Panel title="Metering & Charge Register" action={<Badge tone="info">{data.current.lines.length} CHARGE LINES</Badge>}>
      <div className="mb-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_12rem_auto]">
        <input className={inputClass} placeholder="Search charge, meter or ID…" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search charges" />
        <select aria-label="Charge type" className={inputClass} value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">All charge types</option><option value="commitment">Commitment</option><option value="usage">Metered usage</option><option value="credit">Credits</option>
        </select>
        <Button onClick={() => { setQuery(""); setType(""); }}>Clear</Button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead className="bg-soft text-xs uppercase text-muted"><tr>{["Charge / meter", "Quantity", "Rate", "Amount", "Reconciliation"].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr></thead>
          <tbody>{rows.map((l) => (
            <tr key={l.key} onClick={() => onSelect(l.key)} aria-selected={selectedKey === l.key} className={`cursor-pointer border-b border-line hover:bg-soft ${selectedKey === l.key ? "bg-info/5" : ""}`}>
              <td className="px-3 py-2.5"><b className="block text-ink">{l.label}</b><span className="text-[11px] text-muted">{meterCode(l.key, data.meters)}</span></td>
              <td className="px-3 py-2.5 text-ink">{qty(l.quantity)}<span className="block text-xs text-muted">{l.unit}{l.included ? ` · ${qty(l.included)} included` : ""}</span></td>
              <td className="px-3 py-2.5 text-ink">{data.summary.priced ? `${money(l.rateCents, data.current.currency, l.rateCents % 100 ? 2 : 0)} / ${l.unit}` : "—"}</td>
              <td className={`px-3 py-2.5 font-bold ${l.excluded ? "text-muted line-through" : "text-ink"}`}>{data.summary.priced ? money(l.amountCents, data.current.currency) : "—"}</td>
              <td className="px-3 py-2.5"><Badge tone={STATUS[l.status].tone}>{STATUS[l.status].label}</Badge></td>
            </tr>))}</tbody>
        </table>
        {!rows.length && <EmptyState title="No charge lines match" />}
      </div>
      <p className="mt-3 flex justify-between text-xs text-muted"><span>{rows.length} of {data.current.lines.length} lines · {data.period}</span><span>Metering evidence retained in the audit ledger</span></p>
    </Panel>
  );
}

type InspectorTab = "breakdown" | "lineage" | "allocation" | "disputes";

function Inspector({ line, data, onChanged }: { line: ChargeLine; data: BillingOverview; onChanged: () => void }) {
  const [tab, setTab] = useState<InspectorTab>("breakdown");
  const [reason, setReason] = useState("");
  const { busy, error, run } = useMutation();
  const meter = data.meters.find((m) => m.key === line.key);
  const disputes = data.adjustments.filter((a) => a.kind === "dispute" && a.meter === line.key && a.period === data.period);
  return (
    <Panel title="Charge Evidence Inspector" action={<Badge tone="warn">VERSIONED METERING</Badge>}>
      <div className="mb-3 flex items-center justify-between"><p className="text-lg font-extrabold text-ink">{line.label}</p><Badge tone={STATUS[line.status].tone}>{STATUS[line.status].label}</Badge></div>
      <PillTabs label="Charge detail" active={tab} onChange={setTab} tabs={[
        { key: "breakdown", label: "Breakdown" }, { key: "lineage", label: "Evidence Lineage" }, { key: "allocation", label: "Allocation" }, { key: "disputes", label: "Disputes", count: disputes.length }]} />
      <div className="mt-4 space-y-4">
        <div className="flex items-center justify-between rounded-lg border border-line p-3">
          <span><span className="block text-sm text-ink">{monthLabel(data.period)} MTD charge</span><span className="text-xs text-muted">Before tax · estimate</span></span>
          <span className="text-2xl font-extrabold text-ink">{data.summary.priced ? money(line.amountCents, data.current.currency) : "—"}</span>
        </div>
        {tab === "breakdown" && (
          <DetailRows rows={[
            ["Billing quantity", `${qty(line.quantity)} ${line.unit}`], ["Included in plan", `${qty(line.included)} ${line.unit}`],
            ["Billable", `${qty(line.billable)} ${line.unit}`], ["Contracted rate", data.summary.priced ? `${money(line.rateCents, data.current.currency, 2)} / ${line.unit}` : "No rate card"],
            ["Billing period", `${data.period} (month to date)`], ["Rate card", data.current.planVersion ? `v${data.current.planVersion} · version locked` : "—"],
          ]} />
        )}
        {tab === "lineage" && (
          <div className="space-y-2 text-sm text-ink">
            {meter ? <p>Measured by counting <code className="rounded bg-soft px-1">{meter.event}</code> events in this workspace&apos;s hash-chained audit ledger{meter.key === "model_input" ? " (sum of input length)" : meter.key === "document_uploads" ? " (sum of uploaded bytes)" : ""}.</p>
              : <p>{line.key === "commitment" ? "Fixed by the approved plan version." : "Sum of approved service credits for this month."}</p>}
            {meter && <Link href="/audit-logs" className="font-semibold text-info">View receipts in Audit Logs →</Link>}
            <p className="rounded-lg border border-accent/40 bg-accent/5 p-3 text-xs"><b className="text-accent-ink">Charge calculation policy.</b> Billable = quantity above the included amount × the version-locked rate. The count of events is the chargeable unit; nothing is estimated.</p>
          </div>
        )}
        {tab === "allocation" && <p className="text-sm text-ink">Allocated across client engagements by their share of Kriton interactions (see Cost Allocation).</p>}
        {tab === "disputes" && (
          <>
            {disputes.length ? <ul className="space-y-2 text-sm">{disputes.map((d) => <li key={d.id} className="rounded-lg border border-line p-2.5"><Badge tone={d.status === "open" ? "bad" : "neutral"}>{humanize(d.status)}</Badge> <span className="text-ink">{d.reason}</span><span className="block text-xs text-muted">{d.createdBy}</span></li>)}</ul>
              : <p className="text-sm text-muted">No disputes for this meter this month.</p>}
          </>
        )}
        <ErrorNote message={error} />
        {meter && !disputes.some((d) => d.status === "open") && (
          <div className="space-y-2 border-t border-line pt-3">
            <input className={inputClass} placeholder="Why does this metered quantity look wrong?" value={reason} onChange={(e) => setReason(e.target.value)} />
            <div className="grid grid-cols-3 gap-2">
              <Button variant="primary" disabled={reason.trim().length < 3} busy={busy === "d"} onClick={() => run("d", (t) => addBillingAdjustment(t, { kind: "dispute", period: data.period, meter: line.key, reason })).then((ok) => { if (ok) { setReason(""); onChanged(); } })}>Request review</Button>
              <Link href="/audit-logs" className="inline-flex min-h-10 items-center justify-center rounded-lg border border-line bg-panel text-sm font-semibold text-info hover:bg-soft">View receipts</Link>
              <Button disabled title="Charges follow the approved rate card; use a credit or a dispute">Adjust charge</Button>
            </div>
          </div>
        )}
      </div>
    </Panel>
  );
}

function AllocationPanel({ data, full = false }: { data: BillingOverview; full?: boolean }) {
  const max = Math.max(1, ...data.allocation.map((a) => a.amountCents || a.interactions));
  return (
    <Panel title="Allocated Charges by Engagement" meta="By share of Kriton interactions">
      {data.allocation.length ? (
        <div className="space-y-3">
          {data.allocation.map((a) => <ProgressRow key={a.engagementId ?? "none"} label={a.name} value={data.summary.priced ? a.amountCents : a.interactions} total={max} tone="info"
            right={data.summary.priced ? money(a.amountCents, data.current.currency) : `${a.interactions} questions`} />)}
          <p className="rounded-lg border border-line bg-soft p-2.5 text-xs text-ink"><b>Total: {data.summary.priced ? money(data.current.totalCents, data.current.currency) : "not priced"}</b> · allocation follows recorded engagement context and grants no cross-client visibility.</p>
          {full && <p className="text-xs text-muted">Questions asked outside a client engagement are shown as unassigned.</p>}
        </div>
      ) : <p className="text-sm text-muted">No Kriton activity this month.</p>}
    </Panel>
  );
}

function InvoicesPanel({ data, compact = false, selfId, onChanged }: { data: BillingOverview; compact?: boolean; selfId?: string; onChanged: () => void }) {
  const [period, setPeriod] = useState("");
  const [open, setOpen] = useState("");
  const { busy, error, run } = useMutation();
  void selfId;
  return (
    <Panel title="Finalized Statement Register" meta="Closed months only">
      {data.statements.length ? (
        <table className="w-full text-left text-sm">
          <thead className="bg-soft text-xs uppercase text-muted"><tr>{["Statement", "Period", "Total", "Status"].map((h) => <th key={h} className="px-2 py-2">{h}</th>)}</tr></thead>
          <tbody>{data.statements.slice(0, compact ? 4 : 50).map((s) => (
            <tr key={s.id} className="border-b border-line">
              <td className="px-2 py-2"><button onClick={() => setOpen(open === s.id ? "" : s.id)} className="font-bold text-info hover:underline">{s.ref}</button></td>
              <td className="px-2 py-2 text-ink">{s.period}</td>
              <td className="px-2 py-2 text-ink">{money(s.totalCents, s.currency)}</td>
              <td className="px-2 py-2"><Badge tone={s.status === "paid" ? "ok" : "warn"}>{s.status === "paid" ? "Paid" : "Issued"}</Badge>
                {!compact && s.status === "issued" && <button className="ml-2 text-xs font-semibold text-info hover:underline" onClick={() => { const ref = window.prompt("Payment reference?") ?? ""; if (ref.trim()) run(s.id, (t) => markStatementPaid(t, s.id, ref)).then((ok) => ok && onChanged()); }}>Mark paid</button>}</td>
            </tr>))}</tbody>
        </table>
      ) : <p className="text-sm text-muted">No month has been closed yet.</p>}
      {!compact && open && (() => { const s = data.statements.find((x) => x.id === open); return s ? (
        <div className="mt-3 rounded-lg border border-line p-3 text-sm"><b className="text-ink">{s.ref} lines</b>
          <ul className="mt-1 space-y-1">{s.lines.filter((l) => !l.excluded).map((l) => <li key={l.key} className="flex justify-between"><span className="text-ink">{l.label}</span><span className="text-ink">{money(l.amountCents, s.currency)}</span></li>)}</ul>
          <p className="mt-1 text-xs text-muted">Plan v{s.planVersion} · issued by {s.issuedBy}{s.paymentReference ? ` · paid (${s.paymentReference})` : ""}</p></div>) : null; })()}
      {data.closablePeriods.length > 0 && (
        <div className="mt-3 grid grid-cols-[1fr_auto] gap-2">
          <select aria-label="Month to close" className={inputClass} value={period} onChange={(e) => setPeriod(e.target.value)}><option value="">Close a finished month…</option>{data.closablePeriods.map((p) => <option key={p}>{p}</option>)}</select>
          <Button disabled={!period} busy={busy === "close"} onClick={() => run("close", (t) => closeBillingPeriod(t, period)).then((ok) => ok && onChanged())}>Close month</Button>
        </div>
      )}
      <ErrorNote message={error} />
      <p className="mt-3 rounded-lg border border-line bg-soft p-2.5 text-xs text-ink">The current month is an estimate and never appears here. Taxes, rounding, credits and disputes are settled when a month is closed.</p>
    </Panel>
  );
}

function BudgetPanel({ data }: { data: BillingOverview }) {
  const s = data.summary;
  const c = data.current.currency;
  return (
    <Panel title="Budget Policy & Exceptions">
      {s.softBudgetCents ? (
        <div className="space-y-3">
          <ProgressRow label="MTD spend / soft limit" value={s.estimatedCents} total={s.softBudgetCents} tone={s.estimatedCents > s.softBudgetCents ? "bad" : "warn"} right={`${money(s.estimatedCents, c)} / ${money(s.softBudgetCents, c)}`} />
          <p className="flex justify-between text-sm"><span className="text-ink">Projected month end</span><b className="text-ink">{s.projectedCents === null ? "—" : money(s.projectedCents, c)}</b></p>
          <p className="flex justify-between text-sm"><span className="text-ink">Hard cap</span><b className="text-ink">{s.hardCapCents ? money(s.hardCapCents, c) : "None"}</b></p>
        </div>
      ) : <p className="text-sm text-muted">No budget set in the plan.</p>}
      <p className={`mt-3 rounded-lg border p-2.5 text-xs ${s.openDisputes ? "border-bad/30 bg-bad/5 text-ink" : "border-line text-muted"}`}>
        {s.openDisputes ? <><b className="text-bad">{s.openDisputes} metering exception{s.openDisputes === 1 ? "" : "s"} under review.</b> {money(s.excludedCents, c)} excluded from the estimate until resolved.</> : "No open metering exceptions."}
        <br />Budgets never restrict mandatory security, preservation or professional controls.
      </p>
    </Panel>
  );
}

function LedgerPanel({ data }: { data: BillingOverview }) {
  const days = Object.entries(data.current.usage.daily);
  return (
    <Panel title="Usage Ledger" meta={`${data.period} · daily quantities from the audit ledger`}>
      {days.length ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="bg-soft text-xs text-muted"><tr><th className="px-3 py-2">Date (UTC)</th>{data.meters.map((m) => <th key={m.key} className="px-3 py-2">{m.label}<span className="block font-normal">{m.unit}</span></th>)}</tr></thead>
            <tbody>{days.map(([d, q]) => <tr key={d} className="border-b border-line"><td className="px-3 py-2 font-semibold text-ink">{d}</td>{data.meters.map((m) => <td key={m.key} className="px-3 py-2 text-ink">{q[m.key] ? qty(q[m.key]) : "—"}</td>)}</tr>)}</tbody>
          </table>
        </div>
      ) : <EmptyState title="No metered activity this month" />}
    </Panel>
  );
}

const centsField = (label: string, value: number, set: (v: number) => void) => (
  <label className="block text-sm"><span className="mb-1 block text-muted">{label}</span>
    <input type="number" min={0} step="0.01" className={inputClass} value={value / 100} onChange={(e) => set(Math.round(Number(e.target.value) * 100))} /></label>
);

function ContractPanel({ data, selfId, onChanged }: { data: BillingOverview; selfId?: string; onChanged: () => void }) {
  const base: BillingPlan | null = data.plan;
  const [v, setV] = useState({
    name: base?.name ?? "ZoikoLogia Enterprise", currency: base?.currency ?? "USD", commitment_cents: base?.commitmentCents ?? 0,
    soft_budget_cents: base?.softBudgetCents ?? 0, hard_cap_cents: base?.hardCapCents ?? 0, effective_from: data.period, note: "",
    included: { ...(base?.included ?? {}) } as Record<string, number>, rates: { ...(base?.rates ?? {}) } as Record<string, number>,
  });
  const [note, setNote] = useState("");
  const { busy, error, run } = useMutation();
  const pending = data.pendingPlan;
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Panel title={pending ? `Proposed change · v${pending.version}` : "Propose a plan change"} meta="A different Admin approves">
        {pending ? (
          <div className="space-y-2 text-sm">
            <DetailRows rows={[["Plan", pending.name], ["Commitment", money(pending.commitmentCents, pending.currency)], ["Effective from", pending.effectiveFrom],
              ["Soft budget", money(pending.softBudgetCents, pending.currency)], ["Proposed by", pending.proposedBy], ["Note", pending.note || "—"]]} />
            <input className={inputClass} placeholder="Decision note (required to reject)" value={note} onChange={(e) => setNote(e.target.value)} />
            <ErrorNote message={error} />
            {pending.proposedById === selfId ? <p className="text-xs text-muted">Another Admin must approve your proposal.</p> : (
              <div className="flex gap-2">
                <Button variant="primary" busy={busy === "a"} onClick={() => run("a", (t) => decideBillingPlan(t, pending.id, true, note)).then((ok) => ok && onChanged())}>Approve</Button>
                <Button variant="danger" busy={busy === "r"} onClick={() => run("r", (t) => decideBillingPlan(t, pending.id, false, note)).then((ok) => ok && onChanged())}>Reject</Button>
              </div>)}
          </div>
        ) : (
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); run("p", (t) => proposeBillingPlan(t, v)).then((ok) => ok && onChanged()); }}>
            <div className="grid gap-2 sm:grid-cols-3">
              <label className="block text-sm sm:col-span-2"><span className="mb-1 block text-muted">Plan name</span><input required className={inputClass} value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} /></label>
              <label className="block text-sm"><span className="mb-1 block text-muted">Effective from</span><input required pattern="\d{4}-\d{2}" className={inputClass} value={v.effective_from} onChange={(e) => setV({ ...v, effective_from: e.target.value })} /></label>
              {centsField("Monthly commitment", v.commitment_cents, (n) => setV({ ...v, commitment_cents: n }))}
              {centsField("Soft budget", v.soft_budget_cents, (n) => setV({ ...v, soft_budget_cents: n }))}
              {centsField("Hard cap", v.hard_cap_cents, (n) => setV({ ...v, hard_cap_cents: n }))}
            </div>
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-muted"><tr><th className="py-1">Meter</th><th className="py-1">Included / month</th><th className="py-1">Overage rate ({v.currency})</th></tr></thead>
              <tbody>{data.meters.map((m) => (
                <tr key={m.key}><td className="py-1 pr-2 text-ink">{m.label}<span className="block text-xs text-muted">per {m.unit}</span></td>
                  <td className="py-1 pr-2"><input type="number" min={0} step="any" aria-label={`${m.label} included`} className={inputClass} value={v.included[m.key] ?? 0} onChange={(e) => setV({ ...v, included: { ...v.included, [m.key]: Number(e.target.value) } })} /></td>
                  <td className="py-1"><input type="number" min={0} step="0.0001" aria-label={`${m.label} rate`} className={inputClass} value={(v.rates[m.key] ?? 0) / 100} onChange={(e) => setV({ ...v, rates: { ...v.rates, [m.key]: Number(e.target.value) * 100 } })} /></td></tr>))}</tbody>
            </table>
            <input className={inputClass} placeholder="Reason for the change" value={v.note} onChange={(e) => setV({ ...v, note: e.target.value })} />
            <ErrorNote message={error} />
            <Button type="submit" variant="primary" busy={busy === "p"}>Propose for approval</Button>
          </form>
        )}
      </Panel>
      <Panel title="Contract versions" meta="Every version is kept; past months keep their rates">
        {data.planHistory.length ? (
          <ul className="divide-y divide-line text-sm">{data.planHistory.map((p) => (
            <li key={p.id} className="flex items-center justify-between gap-2 py-2">
              <span><b className="text-ink">v{p.version} · {p.name}</b><span className="block text-xs text-muted">From {p.effectiveFrom} · {money(p.commitmentCents, p.currency)}/month · proposed by {p.proposedBy}{p.decidedBy ? `, decided by ${p.decidedBy}` : ""}</span></span>
              <Badge tone={p.status === "active" ? "ok" : p.status === "proposed" ? "warn" : "neutral"}>{humanize(p.status)}</Badge>
            </li>))}</ul>
        ) : <p className="text-sm text-muted">No plan has been proposed yet.</p>}
      </Panel>
    </div>
  );
}

function ControlsPanel({ data, selfId, onChanged }: { data: BillingOverview; selfId?: string; onChanged: () => void }) {
  const [amount, setAmount] = useState(0);
  const [reason, setReason] = useState("");
  const { busy, error, run } = useMutation();
  const decide = (id: string, decision: string) => {
    const note = decision === "rejected" ? window.prompt("Reason?") ?? "" : "";
    if (decision === "rejected" && !note.trim()) return;
    run(id, (t) => decideBillingAdjustment(t, id, decision, note)).then((ok) => ok && onChanged());
  };
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <BudgetPanel data={data} />
      <Panel title="Credits & metering disputes" meta="A different Admin decides each one">
        <form className="mb-3 grid grid-cols-[8rem_1fr_auto] gap-2" onSubmit={(e) => { e.preventDefault(); run("c", (t) => addBillingAdjustment(t, { kind: "credit", period: data.period, amount_cents: amount, reason })).then((ok) => { if (ok) { setReason(""); setAmount(0); onChanged(); } }); }}>
          <input type="number" min={0} step="0.01" aria-label="Credit amount" className={inputClass} value={amount / 100} onChange={(e) => setAmount(Math.round(Number(e.target.value) * 100))} />
          <input required minLength={3} className={inputClass} placeholder="Credit reason, e.g. SLA miss" value={reason} onChange={(e) => setReason(e.target.value)} />
          <Button type="submit" busy={busy === "c"}>Request credit</Button>
        </form>
        <ErrorNote message={error} />
        {data.adjustments.length ? (
          <ul className="divide-y divide-line text-sm">{data.adjustments.map((a) => (
            <li key={a.id} className="py-2">
              <div className="flex items-center justify-between gap-2">
                <span><b className="text-ink">{a.kind === "credit" ? `Credit ${money(a.amountCents, data.current.currency)}` : `Dispute · ${data.meters.find((m) => m.key === a.meter)?.label ?? a.meter}`}</b>
                  <span className="block text-xs text-muted">{a.period} · {a.reason} · {a.createdBy}</span></span>
                <Badge tone={["approved", "accepted"].includes(a.status) ? "ok" : a.status === "rejected" ? "neutral" : "warn"}>{humanize(a.status)}</Badge>
              </div>
              {["pending", "open"].includes(a.status) && (a.createdById === selfId ? <p className="text-xs text-muted">Another Admin must decide this.</p> : (
                <div className="mt-1 flex gap-2">
                  <Button busy={busy === a.id} onClick={() => decide(a.id, a.kind === "credit" ? "approved" : "accepted")}>{a.kind === "credit" ? "Approve" : "Accept (waive charge)"}</Button>
                  <Button variant="danger" onClick={() => decide(a.id, "rejected")}>Reject</Button>
                </div>))}
            </li>))}</ul>
        ) : <p className="text-sm text-muted">No credits or disputes.</p>}
      </Panel>
    </div>
  );
}

function AuditPanel({ data }: { data: BillingOverview }) {
  return (
    <Panel title="Billing audit trail" meta="Every plan, credit, dispute and statement decision">
      {data.trail.length ? (
        <ul className="space-y-2 text-sm">{data.trail.map((e) => (
          <li key={e.id}><b className="text-ink">{humanize(e.event.replace("billing_", "").replace(/_/g, " "))}</b> <span className="text-xs text-muted">· {e.actor} · {e.at ? utcDate(e.at) : ""}</span></li>))}</ul>
      ) : <p className="text-sm text-muted">No billing changes recorded yet.</p>}
      <Link href="/audit-logs" className="mt-3 inline-block text-sm font-semibold text-info">Open Audit Logs →</Link>
    </Panel>
  );
}
