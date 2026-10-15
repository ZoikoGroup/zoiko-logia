"use client";

import { useState, type ReactNode } from "react";
import { Search, RotateCcw, FileText } from "lucide-react";
import { OverviewPanel, Metric, Status, NoItems } from "@/components/overview/OverviewUI";

export type RegisterRecord = {
  id: string; title: string; subtitle?: string; state: string; category: string;
  scope?: string; version?: string; owner?: string; updated?: string;
  facts: Record<string, string>; evidence?: string[]; history?: string[];
  relations?: string[]; actions?: ReactNode;
};
export type RegisterMetric = { label: string; value: number | string; detail: string; tone?: "blue" | "amber" | "red" | "green" };

export function GovernedRegister({ title, inspector, records, metrics, doctrine, children, action, tabs = ["Overview", "Evidence", "History"], empty = "No records available in this workspace.", footerTitle = "Controlled release pathway" }: {
  title: string; inspector: string; records: RegisterRecord[]; metrics: RegisterMetric[]; doctrine: string; children?: ReactNode; action?: ReactNode; tabs?: string[]; empty?: string; footerTitle?: string;
}) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("All");
  const [state, setState] = useState("All states");
  const [scope, setScope] = useState("All scopes");
  const [sort, setSort] = useState("Default");
  const [selectedId, setSelectedId] = useState("");
  const [tab, setTab] = useState(tabs[0]);
  const [page, setPage] = useState(1);
  const categories = [...new Set(records.map(r => r.category))];
  const scopes = [...new Set(records.map(r => r.scope).filter((v): v is string => Boolean(v)))];
  const filtered = records.filter(r => (category === "All" || r.category === category) && (state === "All states" || r.state === state) && (scope === "All scopes" || r.scope === scope) && `${r.title} ${r.id} ${r.subtitle ?? ""} ${r.owner ?? ""} ${r.scope ?? ""} ${r.category} ${Object.values(r.facts).join(" ")}`.toLowerCase().includes(query.toLowerCase()));
  const sorted = sort === "Title" ? [...filtered].sort((a, b) => a.title.localeCompare(b.title)) : filtered;
  const pageCount = Math.max(1, Math.ceil(sorted.length / 10));
  const currentPage = Math.min(page, pageCount);
  const visible = sorted.slice((currentPage - 1) * 10, currentPage * 10);
  const selected = filtered.find(r => r.id === selectedId) ?? visible[0];
  const change = () => setPage(1);
  const reset = () => { setQuery(""); setCategory("All"); setState("All states"); setScope("All scopes"); setSort("Default"); change(); };
  const flagged = records.filter(r => /block|fail|restrict|pending|review|partial/i.test(r.state));
  return <div className="governed-register space-y-3">
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">{metrics.map(m => <Metric key={m.label} {...m} />)}</div>
    <div className="rounded-lg border border-amber-500/25 border-l-[3px] border-l-[#ee8b1e] bg-amber-500/5 px-4 py-3 text-[11px] leading-5 text-warn">{doctrine}</div>
    <div className="grid items-stretch gap-3 xl:grid-cols-[minmax(0,1.85fr)_minmax(300px,1fr)]">
      <OverviewPanel title={title} subtitle="Browse governed records; select a row to inspect its evidence and scope.">
        {action && <div className="mb-3 flex justify-end gap-2">{action}</div>}
        <div className="mb-3 flex flex-wrap gap-1.5" aria-label="Register categories">{["All", ...categories].map(c => <button key={c} type="button" aria-pressed={category === c} onClick={() => { setCategory(c); change(); }} className={`rounded-md border px-2.5 py-2 text-[10px] ${category === c ? "border-amber-500/40 bg-amber-500/10 font-bold text-warn" : "border-line bg-soft/30 text-muted"}`}>{c}</button>)}</div>
        <div className="mb-3 flex gap-2"><label className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-line px-3"><Search size={14} className="shrink-0 text-muted" /><input aria-label={`Search ${title}`} value={query} onChange={e => { setQuery(e.target.value); change(); }} placeholder="Search title, ID, framework, scope, or owner…" className="min-w-0 w-full bg-transparent py-3 text-xs text-ink outline-none" /></label><button onClick={reset} className="rounded-lg border border-line px-3 text-xs text-brand" aria-label="Reset register filters"><RotateCcw size={14} /></button></div>
        <div className="mb-3 grid gap-2 sm:grid-cols-3">{[
          { label: "Filter by state", value: state, options: ["All states", ...new Set(records.map(r => r.state))], set: setState },
          { label: "Filter by scope", value: scope, options: ["All scopes", ...scopes], set: setScope },
          { label: "Sort register", value: sort, options: ["Default", "Title"], set: setSort },
        ].map(f => <select key={f.label} aria-label={f.label} value={f.value} onChange={e => { f.set(e.target.value); change(); }} className="min-w-0 rounded-md border border-line bg-panel px-2 py-2 text-[10px] text-muted">{f.options.map(o => <option key={o}>{o}</option>)}</select>)}</div>
        <div className="overflow-x-auto"><table className="w-full min-w-[590px] text-left"><thead><tr>{["Record / reference", "Scope", "Category", "State", "Owner / updated"].map(h => <th key={h}>{h}</th>)}</tr></thead><tbody>{visible.map(r => <tr key={r.id} className={selected?.id === r.id ? "bg-amber-500/5" : "hover:bg-soft/50"}><td><button onClick={() => { setSelectedId(r.id); setTab(tabs[0]); }} aria-pressed={selected?.id === r.id} className="text-left font-bold text-ink hover:text-brand">{r.title}</button><small>{r.subtitle || r.id}{r.version ? ` · ${r.version}` : ""}</small></td><td>{r.scope || "Not recorded"}</td><td>{r.category}</td><td><Status>{r.state}</Status></td><td>{r.owner || "Not recorded"}<small>{r.updated}</small></td></tr>)}</tbody></table>{!visible.length && <NoItems>{records.length ? "No records match these filters." : empty}</NoItems>}</div>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[10px] text-muted"><span>{filtered.length} matching records · {records.length} loaded</span><div className="flex items-center gap-2"><button disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)} className="rounded border border-line px-2 py-1 disabled:opacity-30">Previous</button><span>{currentPage} / {pageCount}</span><button disabled={currentPage === pageCount} onClick={() => setPage(currentPage + 1)} className="rounded border border-line px-2 py-1 disabled:opacity-30">Next</button></div></div>
      </OverviewPanel>
      <aside className="min-w-0 rounded-xl border border-line bg-panel p-4 shadow-sm" aria-label={inspector}>
        <p className="text-[9px] font-bold uppercase tracking-[.12em] text-amber-700">{inspector} · selected record</p>
        {selected ? <><div className="mt-3 flex items-start justify-between gap-2"><div><h2 className="break-words text-lg font-bold leading-6 text-ink">{selected.title}</h2><p className="mt-1 break-all text-[10px] text-muted">{selected.id}{selected.version && ` · ${selected.version}`}</p></div><Status>{selected.state}</Status></div>
          <div className="my-4 flex flex-wrap gap-3 border-b border-line" aria-label="Inspector sections">{tabs.map(t => <button key={t} aria-pressed={tab === t} onClick={() => setTab(t)} className={`border-b-2 pb-2 text-[10px] ${tab === t ? "border-amber-600 font-bold text-amber-700" : "border-transparent text-muted"}`}>{t}</button>)}</div>
          {tab === tabs[0] ? <><dl className="grid grid-cols-2 gap-4 rounded-lg border border-line bg-soft/30 p-3">{Object.entries(selected.facts).map(([k, v]) => <div key={k} className="min-w-0"><dt className="text-[9px] uppercase text-muted">{k}</dt><dd className="mt-1 break-words text-[11px] font-semibold text-ink">{v || "Not recorded"}</dd></div>)}</dl><h3 className="mb-2 mt-4 text-xs font-bold text-ink">Evidence & validation</h3><Evidence lines={selected.evidence} /></> : /history|version|audit/i.test(tab) ? <Evidence lines={selected.history} empty="Version and audit history is not supplied by this record feed." /> : /relation|composition|lineage/i.test(tab) ? <Evidence lines={selected.relations} empty="No relationship manifest is supplied by this record feed." /> : <Evidence lines={selected.evidence} />}
          <p className="mt-5 rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-[10px] leading-4 text-warn">A register state alone does not grant retrieval, publication, or production release authority. Current scope, rights, evidence, and independent approvals still apply.</p>
          {selected.actions && <div className="mt-4 flex flex-wrap gap-2">{selected.actions}</div>}
        </> : <NoItems>Select an available record to inspect it.</NoItems>}
      </aside>
    </div>
    <div className="grid gap-3 lg:grid-cols-3"><OverviewPanel title="Priority governance watch" subtitle="Records requiring further attention.">{flagged.length ? flagged.slice(0, 4).map(r => <button key={r.id} onClick={() => { reset(); setSelectedId(r.id); }} className="flex w-full items-start justify-between gap-2 border-b border-line py-3 text-left last:border-0"><span className="text-[11px] font-semibold text-ink">{r.title}</span><Status>{r.state}</Status></button>) : <NoItems>No pending or blocked states reported in the loaded register.</NoItems>}</OverviewPanel>
      <OverviewPanel title={footerTitle} subtitle="Independent checks before governed release."><div className="my-5 flex justify-between gap-1">{["Scope", "Integrity", "Rights", "Review", "Release"].map((s, i) => <div key={s} className="text-center"><span className="mx-auto flex h-7 w-7 items-center justify-center rounded-full bg-soft text-xs text-brand">{i + 1}</span><span className="mt-2 block text-[9px] text-muted">{s}</span></div>)}</div><p className="text-[10px] leading-4 text-muted">Required workflow stages; completion is not asserted without recorded gate evidence.</p></OverviewPanel>
      <OverviewPanel title="Record evidence & traceability" subtitle="Trace selected metadata to its recorded source.">{selected ? <><p className="flex items-center gap-2 text-xs font-semibold text-ink"><FileText size={14} />{selected.title}</p><Evidence lines={selected.history?.length ? selected.history : selected.evidence} /></> : <NoItems>No record selected.</NoItems>}</OverviewPanel>
    </div>{children}
  </div>;
}
function Evidence({ lines, empty = "Validation evidence is not supplied by this record feed." }: { lines?: string[]; empty?: string }) {
  return lines?.length ? <ul className="divide-y divide-line">{lines.map((line, i) => <li key={`${i}-${line}`} className="flex gap-2 py-3 text-[11px] leading-5 text-muted"><FileText size={13} className="mt-1 shrink-0 text-brand" /><span>{line}</span></li>)}</ul> : <NoItems>{empty}</NoItems>;
}
