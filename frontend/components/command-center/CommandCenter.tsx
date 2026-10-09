"use client";

import Link from "next/link";
import { useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  BookOpenCheck,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  Clock3,
  FileCheck2,
  FileSpreadsheet,
  FileText,
  FolderOpen,
  MessageSquareText,
  Plus,
  RotateCcw,
  Scale,
  ShieldCheck,
  Sparkles,
  UsersRound,
} from "lucide-react";
import { useRole } from "@/components/shell/RoleProvider";

const attentionItems = [
  {
    level: "High",
    icon: AlertTriangle,
    iconClass: "bg-bad/10 text-bad",
    labelClass: "text-bad",
    title: "IFRS 15 matter requires human review",
    context: "Zoiko Sema Ltd · Revenue recognition",
    due: "Due today",
    action: "Open review",
    href: "/review-tasks",
  },
  {
    level: "Attention",
    icon: CircleAlert,
    iconClass: "bg-warn/10 text-warn",
    labelClass: "text-warn",
    title: "Two sources require licence verification",
    context: "Zoiko Group Inc. · Lease assessment",
    due: "Due tomorrow",
    action: "Review evidence",
    href: "/evidence-packs",
  },
  {
    level: "Attention",
    icon: Clock3,
    iconClass: "bg-warn/10 text-warn",
    labelClass: "text-warn",
    title: "Client response is overdue",
    context: "Zoiko Electronics Ltd. · Impairment",
    due: "2 days overdue",
    action: "Open matter",
    href: "/workpapers",
  },
];

const matters = [
  ["IFRS 15 — Multiple-Element Revenue Arrangement", "Zoiko Sema Ltd · Revenue recognition", "Human review required", "Due today", "Updated 18 min ago", "14 sources"],
  ["Lease vs. Service Contract Assessment", "Zoiko Group Inc. · Leases", "In progress", "5 Sep 2026", "Updated 1 hr ago", "9 sources"],
  ["Impairment Indicators under IAS 36", "Zoiko Electronics Ltd. · Impairment", "On track", "12 Sep 2026", "Updated 2 hr ago", "12 sources"],
  ["Group Consolidation — Non-controlling Interest", "Zoiko Group Inc. · Consolidation", "Draft", "30 Sep 2026", "Updated 1 day ago", "7 sources"],
];

const deadlines = [
  ["Revenue review decision", "Zoiko Sema Ltd", "Today", "critical"],
  ["Evidence request response", "Zoiko Electronics Ltd", "12 Aug", "approaching"],
  ["Quarterly close sign-off", "Zoiko Group Inc.", "18 Aug", "scheduled"],
];

const recent = [
  [FileSpreadsheet, "Revenue analysis", "Workpaper · Zoiko Sema Ltd", "Edited 18 min ago", "/workpapers"],
  [FolderOpen, "IFRS 15 evidence pack", "Evidence pack · Zoiko Sema Ltd", "Opened 42 min ago", "/evidence-packs"],
  [FileText, "Lease assessment memo", "Draft report · Zoiko Group Inc.", "Edited yesterday", "/drafts-reports"],
  [MessageSquareText, "Control assessment", "Saved Kriton answer", "Viewed 2 days ago", "/saved-answers"],
  [BookOpenCheck, "IAS 36 analysis", "Regulatory analysis", "Viewed 3 days ago", "/reports-insights"],
] as const;

function Panel({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <section className={`rounded-2xl border border-line bg-panel shadow-[0_1px_2px_rgba(16,24,40,.04)] ${className}`}>{children}</section>;
}

function PanelTitle({ title, count, action, href }: { title: string; count?: number; action?: string; href?: string }) {
  return (
    <div className="flex min-h-14 items-center justify-between gap-4 border-b border-line px-5 py-3">
      <div className="flex items-center gap-2.5">
        <h2 className="text-base font-semibold text-ink">{title}</h2>
        {count !== undefined && <span className="rounded-full bg-soft px-2 py-0.5 text-xs font-semibold text-muted">{count}</span>}
      </div>
      {action && href && <Link href={href} className="text-sm font-semibold text-brand hover:text-brand-2">{action}</Link>}
    </div>
  );
}

export function CommandCenter() {
  const { role } = useRole();
  const [newOpen, setNewOpen] = useState(false);
  const [assuranceOpen, setAssuranceOpen] = useState(false);
  const hasReviewAuthority = ["CFO", "Controller", "Audit Partner", "Finance Manager", "AI Governance Lead", "Admin"].includes(role);

  return (
    <main className="flex-1 overflow-y-auto p-4 lg:p-6" aria-labelledby="command-center-title">
      <div className="mx-auto max-w-[1500px] space-y-5">
        <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-line bg-panel p-2.5 shadow-sm">
          <button className="flex min-h-12 min-w-[280px] flex-1 items-center justify-between gap-4 rounded-xl px-3 text-left hover:bg-soft" aria-label="Change accounting context">
            <span className="min-w-0"><span className="block truncate text-sm font-semibold text-ink">Zoiko Group Finance</span><span className="block truncate text-xs text-muted">Zoiko Group Inc. · United States · US GAAP · FY2026</span></span>
            <ChevronDown size={17} className="shrink-0 text-muted" />
          </button>
          <div className="hidden h-8 w-px bg-line sm:block" />
          <button className="flex min-h-11 items-center gap-2 rounded-xl px-3 text-sm font-medium text-ink hover:bg-soft"><ShieldCheck size={17} className="text-brand" /> Entity boundary enforced</button>
          <div className="relative">
            <button onClick={() => setAssuranceOpen((v) => !v)} aria-expanded={assuranceOpen} className="flex min-h-11 items-center gap-2 rounded-xl px-3 text-sm font-medium text-ink hover:bg-soft"><CheckCircle2 size={17} className="text-ok" /> Assurance active <ChevronDown size={14} /></button>
            {assuranceOpen && <div className="absolute right-0 top-full z-20 mt-2 w-80 rounded-xl border border-line bg-panel p-4 shadow-xl"><p className="font-semibold text-ink">Kriton assurance controls</p><p className="mt-1 text-sm leading-6 text-muted">Boundary, jurisdiction, source licensing, citation validation and audit recording are operating normally.</p><p className="mt-3 text-xs text-muted">Verified just now · Policy v4.2</p></div>}
          </div>
        </div>

        <header className="flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <p className="mb-1 text-sm font-medium text-brand">Command Center</p>
            <h1 id="command-center-title" className="text-3xl font-semibold tracking-tight text-ink">Good morning, Lennox.</h1>
            <p className="mt-2 max-w-2xl text-[15px] leading-6 text-muted">4 matters require attention. {hasReviewAuthority ? "2 reviews await your decision. " : ""}3 deadlines fall within the next 14 days.</p>
          </div>
          <div className="flex flex-wrap gap-2.5">
            <Link href="/ask-kriton" className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-brand px-5 text-sm font-semibold text-white shadow-sm hover:bg-brand-2"><Sparkles size={17} /> Ask Kriton</Link>
            <Link href="/workpapers" className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-line bg-panel px-4 text-sm font-semibold text-ink hover:bg-soft"><RotateCcw size={16} /> Resume work</Link>
            {hasReviewAuthority && <Link href="/review-tasks" className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-line bg-panel px-4 text-sm font-semibold text-ink hover:bg-soft"><FileCheck2 size={16} /> Review queue <span className="rounded-full bg-bad/10 px-1.5 text-xs text-bad">2</span></Link>}
            <div className="relative">
              <button onClick={() => setNewOpen((v) => !v)} aria-expanded={newOpen} className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-line bg-panel px-4 text-sm font-semibold text-ink hover:bg-soft"><Plus size={16} /> New <ChevronDown size={14} /></button>
              {newOpen && <div className="absolute right-0 top-full z-20 mt-2 w-56 overflow-hidden rounded-xl border border-line bg-panel p-1.5 shadow-xl">{[["Start a matter", "/workpapers"], ["Upload evidence", "/evidence-packs"], ["Add entity or client", "/entities-clients"], ["Create workpaper", "/workpapers"], ["Create report", "/drafts-reports"]].map(([label, href]) => <Link key={label} href={href} className="block rounded-lg px-3 py-2.5 text-sm text-ink hover:bg-soft">{label}</Link>)}</div>}
            </div>
          </div>
        </header>

        <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
          <div className="min-w-0 space-y-5">
            <Panel>
              <PanelTitle title="Needs your attention" count={attentionItems.length} action="View all" href="/alerts-center" />
              <div className="divide-y divide-line">
                {attentionItems.map((item) => <div key={item.title} className="grid gap-3 px-5 py-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"><div className="flex min-w-0 gap-3"><div className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${item.iconClass}`}><item.icon size={18} /></div><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className={`text-xs font-bold uppercase tracking-wide ${item.labelClass}`}>{item.level}</span><span className="text-xs text-muted">{item.due}</span></div><h3 className="mt-1 text-sm font-semibold text-ink">{item.title}</h3><p className="mt-0.5 text-sm text-muted">{item.context}</p></div></div><Link href={item.href} className="ml-12 inline-flex min-h-10 items-center gap-1.5 text-sm font-semibold text-brand sm:ml-0">{item.action}<ArrowRight size={14} /></Link></div>)}
              </div>
            </Panel>

            <Panel className="overflow-hidden">
              <PanelTitle title="Active matters" count={4} action="View all matters" href="/workpapers" />
              <div className="overflow-x-auto">
                <table className="w-full min-w-[760px] text-left text-sm">
                  <thead><tr className="bg-soft/70 text-xs uppercase tracking-wide text-muted"><th scope="col" className="px-5 py-3 font-semibold">Matter</th><th scope="col" className="px-4 py-3 font-semibold">Status</th><th scope="col" className="px-4 py-3 font-semibold">Due / next action</th><th scope="col" className="px-5 py-3 font-semibold">Evidence</th></tr></thead>
                  <tbody className="divide-y divide-line">{matters.map(([title, context, status, due, updated, evidence], index) => <tr key={title} className="group hover:bg-soft/50"><th scope="row" className="px-5 py-4 font-normal"><Link href="/workpapers" className="font-semibold text-ink group-hover:text-brand">{title}</Link><span className="mt-1 block text-xs text-muted">{context}</span></th><td className="px-4 py-4"><span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${index === 0 ? "bg-bad/10 text-bad" : index === 1 ? "bg-info/10 text-info" : index === 2 ? "bg-ok/10 text-ok" : "bg-chip text-muted"}`}>{status}</span></td><td className="px-4 py-4"><span className="font-medium text-ink">{due}</span><span className="mt-1 block text-xs text-muted">{updated}</span></td><td className="px-5 py-4 text-muted">{evidence}</td></tr>)}</tbody>
                </table>
              </div>
            </Panel>
          </div>

          <aside className="space-y-5" aria-label="Command Center supporting information">
            <Panel>
              <PanelTitle title="Upcoming deadlines" action="View calendar" href="/compliance-calendar" />
              <div className="divide-y divide-line">{deadlines.map(([title, entity, date, state]) => <Link href="/compliance-calendar" key={title} className="flex gap-3 px-4 py-3.5 hover:bg-soft"><div className={`mt-0.5 flex h-10 w-10 shrink-0 flex-col items-center justify-center rounded-lg ${state === "critical" ? "bg-bad/10 text-bad" : state === "approaching" ? "bg-warn/10 text-warn" : "bg-soft text-muted"}`}><CalendarDays size={16} /></div><div className="min-w-0 flex-1"><p className="text-sm font-semibold text-ink">{title}</p><p className="mt-0.5 truncate text-xs text-muted">{entity}</p></div><span className={`text-xs font-semibold ${state === "critical" ? "text-bad" : state === "approaching" ? "text-warn" : "text-muted"}`}>{date}</span></Link>)}</div>
            </Panel>

            {hasReviewAuthority && <Panel><PanelTitle title="Review queue" count={2} action="Open queue" href="/review-tasks" /><div className="divide-y divide-line"><Link href="/review-tasks" className="block px-4 py-3.5 hover:bg-soft"><div className="flex items-start justify-between gap-2"><p className="text-sm font-semibold text-ink">Revenue arrangement conclusion</p><span className="rounded-full bg-bad/10 px-2 py-0.5 text-[11px] font-semibold text-bad">High risk</span></div><p className="mt-1 text-xs text-muted">Requested by Amara Chen · Due today</p></Link><Link href="/review-tasks" className="block px-4 py-3.5 hover:bg-soft"><div className="flex items-start justify-between gap-2"><p className="text-sm font-semibold text-ink">Lease classification workpaper</p><span className="rounded-full bg-warn/10 px-2 py-0.5 text-[11px] font-semibold text-warn">Medium</span></div><p className="mt-1 text-xs text-muted">Requested by Daniel Ross · Due 13 Aug</p></Link></div></Panel>}

            <Link href="/evidence-packs" className="flex items-center gap-3 rounded-2xl border border-warn/30 bg-warn/5 p-4 hover:bg-warn/10"><Scale size={20} className="shrink-0 text-warn" /><span className="min-w-0 flex-1"><span className="block text-sm font-semibold text-ink">Evidence requiring action</span><span className="mt-0.5 block text-xs text-muted">7 missing · 2 due for review · 1 conflicting</span></span><ArrowRight size={16} className="text-warn" /></Link>
          </aside>
        </div>

        <Panel>
          <PanelTitle title="Continue your work" action="View all recent work" href="/my-workspace" />
          <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5">{recent.map(([Icon, title, kind, time, href]) => <Link href={href} key={title} className="group min-h-32 rounded-xl border border-line p-4 hover:border-brand/40 hover:bg-soft"><div className="mb-4 flex h-9 w-9 items-center justify-center rounded-lg bg-brand/10 text-brand"><Icon size={18} /></div><p className="truncate text-sm font-semibold text-ink group-hover:text-brand">{title}</p><p className="mt-1 truncate text-xs text-muted">{kind}</p><p className="mt-2 text-xs text-muted">{time}</p></Link>)}</div>
        </Panel>

        <p className="pb-2 text-center text-xs text-muted"><UsersRound size={13} className="mr-1 inline" />Composed for {role} · Updated just now</p>
      </div>
    </main>
  );
}
