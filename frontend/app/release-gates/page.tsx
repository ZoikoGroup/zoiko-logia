"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { AlertCircle, CheckCircle2, Clock3, Flag, Rocket, Search, UserCheck } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { useLiveData } from "@/components/overview/useLiveData";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import {
  Badge, Breadcrumb, Button, DetailRows, EmptyState, ErrorNote, GATE_STYLE, KpiTile, OpsHero, Panel, PillTabs,
  ProgressRow, humanize, inputClass, useMutation, utcDate,
} from "@/components/operations/ui";
import { History } from "@/components/operations/registry";
import {
  actOnRelease, createRelease, getAssignees, getReleaseRegister, setReleaseGate,
  type Assignee, type GateStatus, type ReleaseCandidate, type ReleaseRegister, type ReleaseStatus,
} from "@/lib/api";

const EDITORS = new Set(["Admin", "Governance Ops Lead", "Risk Admin"]);
const STATUS: Record<ReleaseStatus, { label: string; tone: "ok" | "warn" | "bad" | "info" | "neutral" }> = {
  validating: { label: "Validating", tone: "info" }, on_hold: { label: "On hold", tone: "bad" },
  approval_queue: { label: "Approval queue", tone: "warn" }, approved: { label: "Approved", tone: "ok" },
  deployed: { label: "Deployed", tone: "ok" }, rolled_back: { label: "Rolled back", tone: "neutral" },
};
type TabKey = "all" | "on_hold" | "validating" | "approval_queue" | "deployed";

export default function ReleaseGatesPage() {
  const { profile } = useAuth();
  const canEdit = EDITORS.has(profile?.role ?? "");
  const { data, error, loading, signedOut, reload } = useLiveData(
    "release-register", (token, signal) => getReleaseRegister(token, signal), 45_000,
  );
  const people = useLiveData("ops-assignees", (token, signal) => getAssignees(token, signal), 20_000);
  const [tab, setTab] = useState<TabKey>("all");
  const [selectedId, setSelectedId] = useState("");
  const [creating, setCreating] = useState(false);
  const releases = useMemo(() => data?.releases ?? [], [data]);
  const selected = releases.find((r) => r.id === selectedId) ?? releases.find((r) => r.status === "on_hold") ?? releases[0];

  return (
    <main className="flex-1 space-y-4 overflow-y-auto p-4">
      <Breadcrumb section="Administration" page="Release Gates" detail="Production authorization" />
      <OpsHero icon={Flag} title="Release Gates"
        subtitle="Govern and authorize platform, accounting, knowledge, and Kriton AI releases · Mandatory evidence · Independent approval · Progressive delivery · Recorded rollback">
        <p className="text-xs font-bold uppercase tracking-wider text-white">Release authority</p>
        <p>Never trade critical controls for a passing score.</p>
        <p>Failed mandatory gate = HOLD.</p>
      </OpsHero>
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />
      {data && (
        <>
          <Kpis data={data} />
          <section className="flex flex-col gap-2 rounded-xl border border-accent/40 border-l-4 border-l-accent bg-accent/5 p-4 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-ink"><b className="text-accent-ink">FAIL-CLOSED RELEASE RULE</b> No production promotion with a failed or unevidenced gate: source rights, tenant isolation, accounting accuracy, AI evaluation, operational readiness or rollback. Live gates are re-measured at every decision.</p>
            <Link href="/evaluation-gates" className="inline-flex min-h-10 shrink-0 items-center rounded-lg border border-line bg-panel px-3 text-sm font-semibold text-info hover:bg-soft">View evaluation gates ↗</Link>
          </section>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <PillTabs label="Release views" active={tab} onChange={setTab} tabs={[
              { key: "all", label: "All releases", count: releases.length }, { key: "on_hold", label: "On hold", count: data.summary.onHold },
              { key: "validating", label: "Validating", count: data.summary.validating },
              { key: "approval_queue", label: "Approval queue", count: data.summary.awaitingApproval + data.summary.approved },
              { key: "deployed", label: "Deployed", count: data.summary.deployed }]} />
            {canEdit && <Button variant="primary" onClick={() => setCreating(true)}>+ Create release candidate</Button>}
          </div>
          {creating && <CreateForm data={data} people={people.data ?? []} onDone={() => { setCreating(false); reload(); }} />}
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_480px]">
            <Register rows={releases} tab={tab} data={data} selectedId={selected?.id} onSelect={setSelectedId} />
            {selected ? <Detail key={selected.id} r={selected} canEdit={canEdit} selfId={profile?.id} onChanged={reload} />
              : <Panel title="Release candidate"><EmptyState icon={Flag} title="No release candidates yet">Create one for each change on its way to production; its gates are measured or evidenced before promotion.</EmptyState></Panel>}
          </div>
          <Bottom data={data} selected={selected} />
        </>
      )}
    </main>
  );
}

function Kpis({ data }: { data: ReleaseRegister }) {
  const s = data.summary;
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <KpiTile icon={Flag} value={s.records} label="Release records" hint="This workspace's change portfolio" />
      <KpiTile icon={AlertCircle} tone={s.onHold ? "bad" : "ok"} value={s.onHold} label="On hold" hint="Mandatory blockers remain" />
      <KpiTile icon={Clock3} tone="warn" value={s.validating} label="In validation" hint="Evidence or tests pending" />
      <KpiTile icon={UserCheck} tone="warn" value={s.awaitingApproval} label="Awaiting approval" hint="Independent sign-off needed" />
      <KpiTile icon={CheckCircle2} tone="ok" value={s.deployed} label="Deployed" hint={s.rolledBack ? `${s.rolledBack} rolled back` : "Promoted with every gate passed"} />
    </div>
  );
}

function Register({ rows, tab, data, selectedId, onSelect }: { rows: ReleaseCandidate[]; tab: TabKey; data: ReleaseRegister; selectedId?: string; onSelect: (id: string) => void }) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [component, setComponent] = useState("");
  const shown = rows.filter((r) => (tab === "all" || r.status === tab || (tab === "approval_queue" && r.status === "approved"))
    && (!status || r.status === status) && (!component || r.component === component)
    && (!query || `${r.ref} ${r.changeRef} ${r.name} ${r.component} ${r.owner ?? ""}`.toLowerCase().includes(query.toLowerCase())));
  return (
    <Panel title="Release candidates & deployment register" meta="Authorized scope">
      <div className="mb-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_10rem_11rem]">
        <label className="relative">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input className={`${inputClass} pl-9`} placeholder="Search release, change ID, component, owner…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <select aria-label="Status" className={inputClass} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All statuses</option>{Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select>
        <select aria-label="Component" className={inputClass} value={component} onChange={(e) => setComponent(e.target.value)}><option value="">All components</option>{data.components.map((c) => <option key={c}>{c}</option>)}</select>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead className="bg-soft text-xs text-muted">
            <tr>{["Release ID", "Package / version", "Component", "Stage", "Gate evidence", "Decision", ""].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.id} className={`border-b border-line ${selectedId === r.id ? "border-l-4 border-l-accent bg-info/5" : ""}`}>
                <td className="px-3 py-2.5"><b className="block text-ink">{r.ref}</b><span className="text-[11px] text-muted">{r.changeRef || "No change record"}</span></td>
                <td className="px-3 py-2.5"><b className="block text-ink">{r.name}</b><span className="text-xs text-muted">v{r.version}{r.owner ? ` · ${r.owner}` : ""}</span></td>
                <td className="px-3 py-2.5 text-ink">{r.component}</td>
                <td className="px-3 py-2.5 text-ink">{r.stage}</td>
                <td className="px-3 py-2.5">
                  <b className="block text-ink">{r.passed}/10 passed{r.failed ? ` · ${r.failed} failed` : ""}</b>
                  <span className="mt-1 block h-1.5 w-20 overflow-hidden rounded-full bg-soft"><span className={`block h-full rounded-full ${r.failed ? "bg-bad" : "bg-ok"}`} style={{ width: `${r.passed * 10}%` }} /></span>
                </td>
                <td className="px-3 py-2.5"><Badge tone={STATUS[r.status].tone}>{STATUS[r.status].label}</Badge></td>
                <td className="px-3 py-2.5"><button aria-label={`Open ${r.ref}`} onClick={() => onSelect(r.id)} className="grid h-8 w-8 place-items-center rounded-lg border border-line text-info hover:bg-soft">→</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        {!shown.length && <EmptyState title={rows.length ? "No releases in this view" : "No release candidates yet"} />}
      </div>
      <p className="mt-3 flex justify-between text-xs text-muted"><span>{shown.length} of {rows.length} records</span><span>Change log · audited release record</span></p>
    </Panel>
  );
}

type DetailTab = "gates" | "manifest" | "rollout" | "history";

function Detail({ r, canEdit, selfId, onChanged }: { r: ReleaseCandidate; canEdit: boolean; selfId?: string; onChanged: () => void }) {
  const [tab, setTab] = useState<DetailTab>("gates");
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<{ status: GateStatus; note: string }>({ status: "pass", note: "" });
  const [note, setNote] = useState("");
  const { busy, error, run } = useMutation();
  const closed = r.status === "deployed" || r.status === "rolled_back";
  const act = (a: "approve" | "deploy" | "rollback") => run(a, (t) => actOnRelease(t, r.id, a, note)).then((ok) => { if (ok) { setNote(""); onChanged(); } });
  return (
    <Panel title={r.name} meta={r.ref} action={<Badge tone={STATUS[r.status].tone}>{STATUS[r.status].label}</Badge>}>
      <p className="-mt-2 mb-3 text-sm text-muted">Version {r.version} · {r.component}</p>
      <PillTabs label="Release detail" active={tab} onChange={setTab} tabs={[
        { key: "gates", label: "Gates" }, { key: "manifest", label: "Manifest" }, { key: "rollout", label: "Rollout" }, { key: "history", label: "History", count: r.history.length }]} />
      <div className="mt-4 space-y-4">
        {!closed && r.status !== "approved" && (
          <div className="rounded-lg border border-bad/30 bg-bad/5 p-3">
            <p className="text-sm font-bold text-bad">PRODUCTION PROMOTION RESTRICTED</p>
            <p className="text-sm text-ink">{r.passed} passed · {r.failed} failed · {r.pending} pending. A failed gate or a missing independent approval keeps production blocked.</p>
          </div>
        )}
        {tab === "gates" && (
          <>
            <div className="flex justify-between text-sm"><b className="text-ink">Mandatory gate matrix</b><b className="text-ink">{r.passed}/10 passed · {r.failed} failed · {r.pending} pending</b></div>
            <ul className="divide-y divide-line">
              {r.gates.map((g) => {
                const s = GATE_STYLE[g.status];
                return (
                  <li key={g.key} className="py-2">
                    <div className="flex items-start justify-between gap-3">
                      <span className="flex items-start gap-2"><s.icon size={16} className={`mt-0.5 shrink-0 ${s.tone}`} />
                        <span><b className="block text-sm text-ink">{String(g.number).padStart(2, "0")}. {g.label}{g.derived && <span className="ml-1 text-[10px] font-normal text-muted">measured</span>}</b>
                          <span className="block text-xs text-muted">{g.note || g.description}{g.byName ? ` · ${g.byName}` : ""}</span></span></span>
                      <span className="flex items-center gap-2">
                        <span className={`text-xs font-bold uppercase ${s.tone}`}>{g.status === "open" ? "Pending" : s.label}</span>
                        {canEdit && !closed && !g.derived && <button className="text-xs font-semibold text-info hover:underline" onClick={() => { setEditing(g.key); setDraft({ status: g.status === "open" ? "pass" : g.status, note: g.note }); }}>Record</button>}
                      </span>
                    </div>
                    {editing === g.key && (
                      <div className="mt-2 grid gap-2 sm:grid-cols-[7rem_1fr_auto]">
                        <select aria-label={`${g.label} status`} className={inputClass} value={draft.status} onChange={(e) => setDraft({ ...draft, status: e.target.value as GateStatus })}>
                          <option value="pass">Pass</option><option value="fail">Fail</option><option value="open">Pending</option>
                        </select>
                        <input className={inputClass} placeholder="Evidence link or reason (required)" value={draft.note} onChange={(e) => setDraft({ ...draft, note: e.target.value })} />
                        <Button variant="primary" busy={busy === g.key} onClick={() => run(g.key, (t) => setReleaseGate(t, r.id, g.key, draft.status, draft.note)).then((ok) => { if (ok) { setEditing(null); onChanged(); } })}>Save</Button>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </>
        )}
        {tab === "manifest" && <DetailRows rows={[
          ["Change record", r.changeRef || "—"], ["Target environment", r.stage], ["Accountable owner", r.owner ?? "Unassigned"],
          ["Risk class", humanize(r.risk)], ["Artifact version", `v${r.version}`], ["Scope", r.description || "—"],
          ["Created", `${r.createdBy} · ${r.createdAt ? utcDate(r.createdAt) : ""}`],
          ["Approved", r.approvedBy ? `${r.approvedBy} · ${utcDate(r.approvedAt)}` : "Not yet"],
          ["Deployed", r.deployedAt ? utcDate(r.deployedAt) : "—"], ["Rolled back", r.rolledBackAt ? utcDate(r.rolledBackAt) : "—"],
        ]} />}
        {tab === "rollout" && <Rollout r={r} />}
        {tab === "history" && <History entries={r.history} />}
        <ErrorNote message={error} />
        {canEdit && (
          <div className="space-y-2 border-t border-line pt-3">
            {r.status === "deployed" && <input className={inputClass} placeholder="Rollback reason (required)" value={note} onChange={(e) => setNote(e.target.value)} />}
            <div className="grid grid-cols-2 gap-2">
              {r.status === "approval_queue" && <Button variant="primary" disabled={r.createdById === selfId} title={r.createdById === selfId ? "Someone other than the author must approve" : ""} busy={busy === "approve"} onClick={() => act("approve")}>Approve release</Button>}
              {r.status === "approved" && <Button variant="primary" busy={busy === "deploy"} onClick={() => act("deploy")}><Rocket size={14} /> Promote to production</Button>}
              {r.status === "deployed" && <Button variant="danger" disabled={!note.trim()} busy={busy === "rollback"} onClick={() => act("rollback")}>Roll back</Button>}
              {(r.status === "on_hold" || r.status === "validating") && <Button variant="primary" onClick={() => setTab("gates")}>Request remediation</Button>}
              <Button onClick={() => setTab("rollout")}>View rollout plan</Button>
              {r.status !== "approved" && r.status !== "deployed" && <Button disabled>Production approval blocked</Button>}
            </div>
          </div>
        )}
      </div>
    </Panel>
  );
}

function Rollout({ r }: { r: ReleaseCandidate }) {
  return (
    <ol className="space-y-3">
      {r.rollout.map((s, i) => {
        const tone = s.status === "pass" ? "text-ok border-ok" : s.status === "fail" ? "text-bad border-bad" : s.status === "watching" ? "text-info border-info" : "text-muted border-line";
        return (
          <li key={s.step} className="flex gap-3">
            <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-full border-2 text-xs font-bold ${tone}`}>{i + 1}</span>
            <span><b className="block text-sm text-ink">{s.step}</b><span className="text-xs text-muted">{s.detail} · {humanize(s.status === "open" ? "pending" : s.status)}</span></span>
          </li>
        );
      })}
    </ol>
  );
}

function Bottom({ data, selected }: { data: ReleaseRegister; selected?: ReleaseCandidate }) {
  const s = data.summary;
  const total = Math.max(1, s.records);
  const READINESS = { passed: { icon: "✓", tone: "text-ok" }, blocked: { icon: "!", tone: "text-bad" }, partial: { icon: "!", tone: "text-accent-ink" }, not_assessed: { icon: "–", tone: "text-muted" } };
  return (
    <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
      <Panel title="Release portfolio · disposition">
        <div className="space-y-3">
          <ProgressRow label="On hold" value={s.onHold} total={total} tone="bad" right={s.onHold} />
          <ProgressRow label="Validating" value={s.validating} total={total} tone="warn" right={s.validating} />
          <ProgressRow label="Approval queue" value={s.awaitingApproval + s.approved} total={total} tone="info" right={s.awaitingApproval + s.approved} />
          <ProgressRow label="Deployed" value={s.deployed} total={total} tone="ok" right={s.deployed} />
        </div>
      </Panel>
      <Panel title="Mandatory assurance families" meta="Measured live">
        <ul className="divide-y divide-line text-sm">
          {data.readiness.map((g) => (
            <li key={g.gate} className="flex gap-2 py-2">
              <span className={`font-bold ${READINESS[g.state].tone}`}>{READINESS[g.state].icon}</span>
              <span><b className="block text-ink">{g.gate}</b><span className="text-xs text-muted">{g.reason}</span></span>
            </li>
          ))}
        </ul>
      </Panel>
      <Panel title="Selected release · rollout discipline">{selected ? <Rollout r={selected} /> : <p className="text-sm text-muted">Select a release.</p>}</Panel>
      <Panel title="Governed actions">
        <div className="grid grid-cols-2 gap-2">
          {[["/evaluation-gates", "Evaluation gates"], ["/model-prompt-registry", "Model registry"], ["/risk-policy", "Risk policy"],
            ["/audit-replay", "Audit replay"], ["/status-health", "Operational health"], ["/audit-logs", "Evidence export"]].map(([href, label]) => (
            <Link key={href} href={href} className="inline-flex min-h-10 items-center justify-center rounded-lg border border-line bg-panel text-sm font-semibold text-info hover:bg-soft">{label}</Link>
          ))}
        </div>
        <p className="mt-3 rounded-lg border border-line bg-soft p-2.5 text-xs text-ink">Every gate change and decision is checked by the backend and recorded in the audit ledger.</p>
      </Panel>
    </div>
  );
}

function CreateForm({ data, people, onDone }: { data: ReleaseRegister; people: Assignee[]; onDone: () => void }) {
  const [v, setV] = useState({ name: "", version: "", component: data.components[0] ?? "Platform", change_ref: "", description: "", risk: "medium" as const, owner_user_id: "" });
  const { busy, error, run } = useMutation();
  const set = (k: keyof typeof v) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value });
  return (
    <Panel title="Create release candidate" meta="Starts in validation; measured gates are evaluated immediately" action={<Button onClick={onDone}>Cancel</Button>}>
      <form className="grid gap-3 md:grid-cols-4" onSubmit={(e) => { e.preventDefault(); run("c", (t) => createRelease(t, { ...v, owner_user_id: v.owner_user_id || null })).then((ok) => ok && onDone()); }}>
        <input required minLength={2} className={inputClass} placeholder="Package, e.g. Kriton Agent Orchestrator" value={v.name} onChange={set("name")} aria-label="Package" />
        <input required className={inputClass} placeholder="Version, e.g. 2.6.0" value={v.version} onChange={set("version")} aria-label="Version" />
        <select aria-label="Component" className={inputClass} value={v.component} onChange={set("component")}>{data.components.map((c) => <option key={c}>{c}</option>)}</select>
        <input className={inputClass} placeholder="Change record, e.g. PR #46" value={v.change_ref} onChange={set("change_ref")} aria-label="Change record" />
        <input className={`${inputClass} md:col-span-2`} placeholder="Scope and impact" value={v.description} onChange={set("description")} aria-label="Scope" />
        <select aria-label="Risk class" className={inputClass} value={v.risk} onChange={set("risk")}>{["critical", "high", "medium", "low"].map((r) => <option key={r} value={r}>{humanize(r)}</option>)}</select>
        <select aria-label="Owner" className={inputClass} value={v.owner_user_id} onChange={set("owner_user_id")}><option value="">Accountable owner…</option>{people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
        <div className="md:col-span-4"><ErrorNote message={error} /></div>
        <div><Button type="submit" variant="primary" busy={busy === "c"}>Create candidate</Button></div>
      </form>
    </Panel>
  );
}
