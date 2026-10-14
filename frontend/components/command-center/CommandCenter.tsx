"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  BookOpenCheck,
  Briefcase,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  FileCheck2,
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
import { getAuthToken, getCommandCenter, switchCommandCenterContext } from "@/lib/api";
import type { CommandCenterViewModel, WorkItem } from "@/lib/command-center-types";
import { useLiveData } from "@/components/overview/useLiveData";
import { EmptyRow, ErrorBlock, LoadingBlock, RefreshButton, SignedOutBlock } from "@/components/overview/states";

const CONTEXTS = [
  { jurisdiction: "US", framework: "US-GAAP", label: "United States · US GAAP" },
  { jurisdiction: "GB", framework: "IFRS", label: "United Kingdom · IFRS" },
  { jurisdiction: "US", framework: "IFRS", label: "United States · IFRS" },
  { jurisdiction: "GB", framework: "US-GAAP", label: "United Kingdom · US GAAP" },
];
const PERIOD = `FY${new Date().getFullYear()}`;

const WORK_ICONS: Record<WorkItem["kind"], typeof FileText> = {
  saved_answer: MessageSquareText,
  draft: FileText,
  document: FolderOpen,
  artifact: BookOpenCheck,
  review: FileCheck2,
};

const CONTROL_LABELS: Record<string, string> = {
  boundary_enforcement: "Tenant boundary",
  audit_recording: "Audit recording",
  source_licensing: "Source licensing",
  source_authority: "Source approval",
  human_review: "Human review backlog",
  escalation_sla: "Escalation SLAs",
};

function greeting() {
  const hour = new Date().getHours();
  return hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
}

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

function headline(view: CommandCenterViewModel, showReviews: boolean) {
  const { summary, reviewQueue } = view;
  const parts = [
    summary.attentionCount === 0 ? "Nothing needs your attention right now." : `${summary.attentionCount} ${summary.attentionCount === 1 ? "item needs" : "items need"} your attention.`,
  ];
  if (showReviews && reviewQueue) parts.push(`${reviewQueue.open} ${reviewQueue.open === 1 ? "answer awaits" : "answers await"} review.`);
  if (summary.overdueCount) parts.push(`${summary.overdueCount} overdue.`);
  parts.push(`${summary.upcomingDeadlineCount} ${summary.upcomingDeadlineCount === 1 ? "deadline falls" : "deadlines fall"} within the next ${summary.deadlineHorizonDays} days.`);
  return parts.join(" ");
}

export function CommandCenter() {
  const { role } = useRole();
  // The backend gates on the real account; this also respects an Admin's
  // "Viewing as" preview of a role without review authority.
  const hasReviewAuthority = ["CFO", "Controller", "Audit Partner", "Finance Manager", "AI Governance Lead", "Admin", "SME Reviewer", "Governance Ops Lead"].includes(role);
  const [newOpen, setNewOpen] = useState(false);
  const [assuranceOpen, setAssuranceOpen] = useState(false);
  const [contextOpen, setContextOpen] = useState(false);
  const [contextIndex, setContextIndex] = useState(0);
  const [contextError, setContextError] = useState("");
  const contextRef = useRef(CONTEXTS[0]);
  const { data: view, error, loading, signedOut, reload } = useLiveData(`command-center:${CONTEXTS[contextIndex].jurisdiction}:${CONTEXTS[contextIndex].framework}`, (token, signal, fresh) =>
    getCommandCenter(token, { jurisdiction: contextRef.current.jurisdiction, framework: contextRef.current.framework, period: PERIOD }, signal, fresh),
  );

  async function chooseContext(index: number) {
    setContextOpen(false);
    setContextError("");
    if (!view) return;
    const next = CONTEXTS[index];
    try {
      await switchCommandCenterContext(getAuthToken(), {
        jurisdiction: next.jurisdiction, framework: next.framework, period: PERIOD, previous_context_token: view.contextToken,
      });
      contextRef.current = next;
      setContextIndex(index);
      reload();
    } catch (err) {
      setContextError(err instanceof Error ? err.message : "That accounting context is not available.");
    }
  }

  if (signedOut) return <main className="flex-1 overflow-y-auto p-4 lg:p-6"><div className="mx-auto max-w-[1500px]"><SignedOutBlock /></div></main>;

  return (
    <main className="flex-1 overflow-y-auto p-4 lg:p-6" aria-labelledby="command-center-title">
      <div className="mx-auto max-w-[1500px] space-y-5">
        <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-line bg-panel p-2.5 shadow-sm">
          <div className="relative min-w-[280px] flex-1">
            <button onClick={() => setContextOpen((v) => !v)} aria-expanded={contextOpen} className="flex min-h-12 w-full items-center justify-between gap-4 rounded-xl px-3 text-left hover:bg-soft" aria-label="Change accounting context">
              <span className="min-w-0"><span className="block truncate text-sm font-semibold text-ink">{view?.workspaceName ?? "Loading workspace…"}</span><span className="block truncate text-xs text-muted">{CONTEXTS[contextIndex].label} · {PERIOD}</span></span>
              <ChevronDown size={17} className="shrink-0 text-muted" />
            </button>
            {contextOpen && <div className="absolute left-0 top-full z-20 mt-2 w-72 overflow-hidden rounded-xl border border-line bg-panel p-1.5 shadow-xl">{CONTEXTS.map((c, i) => <button key={c.label} onClick={() => chooseContext(i)} className={`block w-full rounded-lg px-3 py-2.5 text-left text-sm hover:bg-soft ${i === contextIndex ? "font-semibold text-brand" : "text-ink"}`}>{c.label}</button>)}</div>}
          </div>
          <div className="hidden h-8 w-px bg-line sm:block" />
          <span className="flex min-h-11 items-center gap-2 rounded-xl px-3 text-sm font-medium text-ink"><ShieldCheck size={17} className="text-brand" /> Entity boundary enforced</span>
          {view && <div className="relative">
            <button onClick={() => setAssuranceOpen((v) => !v)} aria-expanded={assuranceOpen} className="flex min-h-11 items-center gap-2 rounded-xl px-3 text-sm font-medium text-ink hover:bg-soft">{view.assurance.overallState === "ok" ? <CheckCircle2 size={17} className="text-ok" /> : <CircleAlert size={17} className="text-warn" />} {view.assurance.overallState === "ok" ? "Assurance active" : "Assurance needs attention"} <ChevronDown size={14} /></button>
            {assuranceOpen && <div className="absolute right-0 top-full z-20 mt-2 w-80 rounded-xl border border-line bg-panel p-4 shadow-xl"><p className="font-semibold text-ink">Kriton assurance controls</p><ul className="mt-2 space-y-1.5 text-sm">{Object.entries(view.assurance.controls).map(([key, state]) => <li key={key} className="flex items-center justify-between gap-3"><span className="text-muted">{CONTROL_LABELS[key] ?? key}</span><span className={`font-semibold ${state === "ok" ? "text-ok" : "text-warn"}`}>{state === "ok" ? "OK" : state === "stale" ? "Stale" : "Attention"}</span></li>)}</ul><p className="mt-3 text-xs text-muted">Last audit event {view.assurance.lastAuditEventAge} · Policy {view.assurance.policyVersion}</p></div>}
          </div>}
        </div>
        {contextError && <p className="text-sm text-bad">{contextError}</p>}

        <header className="flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <p className="mb-1 text-sm font-medium text-brand">Command Center</p>
            <h1 id="command-center-title" className="text-3xl font-semibold tracking-tight text-ink">{greeting()}{view ? `, ${view.user.displayName}` : ""}.</h1>
            <p className="mt-2 max-w-2xl text-[15px] leading-6 text-muted">{view ? headline(view, hasReviewAuthority) : loading ? "Loading your workspace…" : ""}</p>
          </div>
          <div className="flex flex-wrap gap-2.5">
            <Link href="/ask-kriton" className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-brand px-5 text-sm font-semibold text-white shadow-sm hover:bg-brand-2"><Sparkles size={17} /> Ask Kriton</Link>
            <Link href={view?.recentWork[0]?.href ?? "/my-workspace"} className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-line bg-panel px-4 text-sm font-semibold text-ink hover:bg-soft"><RotateCcw size={16} /> Resume work</Link>
            {hasReviewAuthority && view?.reviewQueue && <Link href="/review-tasks" className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-line bg-panel px-4 text-sm font-semibold text-ink hover:bg-soft"><FileCheck2 size={16} /> Review queue <span className="rounded-full bg-bad/10 px-1.5 text-xs text-bad">{view.reviewQueue.open}</span></Link>}
            <div className="relative">
              <button onClick={() => setNewOpen((v) => !v)} aria-expanded={newOpen} className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-line bg-panel px-4 text-sm font-semibold text-ink hover:bg-soft"><Plus size={16} /> New <ChevronDown size={14} /></button>
              {newOpen && <div className="absolute right-0 top-full z-20 mt-2 w-56 overflow-hidden rounded-xl border border-line bg-panel p-1.5 shadow-xl">{[["Ask a new question", "/ask-kriton"], ["Upload evidence", "/evidence-packs"], ["Add entity or client", "/entities-clients"], ["Create workpaper", "/workpapers"], ["Create report", "/drafts-reports"]].map(([label, href]) => <Link key={label} href={href} className="block rounded-lg px-3 py-2.5 text-sm text-ink hover:bg-soft">{label}</Link>)}</div>}
            </div>
            <RefreshButton onClick={reload} loading={loading} generatedAt={view?.generatedAt} />
          </div>
        </header>

        {error && <ErrorBlock message={error} onRetry={reload} />}
        {!view && loading && <LoadingBlock label="Loading Command Center" />}

        {view && <>
          <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
            <div className="min-w-0 space-y-5">
              <Panel>
                <PanelTitle title="Needs your attention" count={view.attentionItems.length} action="View all" href="/alerts-center" />
                <div className="divide-y divide-line">
                  {view.attentionItems.length === 0 && <EmptyRow>Nothing needs your attention. Open incidents, overdue escalations, high-risk reviews and pending source approvals will appear here.</EmptyRow>}
                  {view.attentionItems.map((item) => {
                    const high = item.level === "high";
                    const Icon = high ? AlertTriangle : CircleAlert;
                    return <div key={item.id} className="grid gap-3 px-5 py-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"><div className="flex min-w-0 gap-3"><div className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${high ? "bg-bad/10 text-bad" : "bg-warn/10 text-warn"}`}><Icon size={18} /></div><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className={`text-xs font-bold uppercase tracking-wide ${high ? "text-bad" : "text-warn"}`}>{high ? "High" : "Attention"}</span>{item.due && <span className="text-xs text-muted">{item.due}</span>}</div><h3 className="mt-1 text-sm font-semibold text-ink">{item.title}</h3><p className="mt-0.5 truncate text-sm text-muted">{item.context}</p></div></div><Link href={item.href} className="ml-12 inline-flex min-h-10 items-center gap-1.5 text-sm font-semibold text-brand sm:ml-0">{item.action}<ArrowRight size={14} /></Link></div>;
                  })}
                </div>
              </Panel>

              <Panel className="overflow-hidden">
                <PanelTitle title="Active matters" count={view.activeMatterCount} action="View all matters" href="/entities-clients" />
                {view.activeMatters.length === 0 ? (
                  <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-6"><p className="text-sm text-muted">No active matters yet. Matters are the client engagements your team works on.</p><Link href="/entities-clients" className="inline-flex items-center gap-1.5 text-sm font-semibold text-brand"><Briefcase size={15} /> Add a client</Link></div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[560px] text-left text-sm">
                      <thead><tr className="bg-soft/70 text-xs uppercase tracking-wide text-muted"><th scope="col" className="px-5 py-3 font-semibold">Matter</th><th scope="col" className="px-4 py-3 font-semibold">Status</th><th scope="col" className="px-5 py-3 font-semibold">Opened</th></tr></thead>
                      <tbody className="divide-y divide-line">{view.activeMatters.map((m) => <tr key={m.id} className="group hover:bg-soft/50"><th scope="row" className="px-5 py-4 font-normal"><Link href="/entities-clients" className="font-semibold text-ink group-hover:text-brand">{m.name}</Link></th><td className="px-4 py-4"><span className="inline-flex rounded-full bg-ok/10 px-2.5 py-1 text-xs font-semibold capitalize text-ok">{m.status}</span></td><td className="px-5 py-4 text-muted">{m.age}</td></tr>)}</tbody>
                    </table>
                  </div>
                )}
              </Panel>
            </div>

            <aside className="space-y-5" aria-label="Command Center supporting information">
              <Panel>
                <PanelTitle title="Upcoming deadlines" action="View calendar" href="/compliance-calendar" />
                <div className="divide-y divide-line">
                  {view.deadlines.length === 0 && <EmptyRow>No deadlines in the next {view.summary.deadlineHorizonDays} days.</EmptyRow>}
                  {view.deadlines.map((d) => <Link href={d.href} key={d.id} className="flex gap-3 px-4 py-3.5 hover:bg-soft"><div className={`mt-0.5 flex h-10 w-10 shrink-0 flex-col items-center justify-center rounded-lg ${d.state === "critical" ? "bg-bad/10 text-bad" : d.state === "approaching" ? "bg-warn/10 text-warn" : "bg-soft text-muted"}`}><CalendarDays size={16} /></div><div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold text-ink">{d.title}</p><p className="mt-0.5 truncate text-xs text-muted">{d.context}</p></div><span className={`whitespace-nowrap text-xs font-semibold ${d.state === "critical" ? "text-bad" : d.state === "approaching" ? "text-warn" : "text-muted"}`}>{d.date}</span></Link>)}
                </div>
              </Panel>

              {hasReviewAuthority && view.reviewQueue && <Panel><PanelTitle title="Review queue" count={view.reviewQueue.open} action="Open queue" href="/review-tasks" /><div className="divide-y divide-line">
                {view.reviewQueue.items.length === 0 && <EmptyRow>The review queue is empty.</EmptyRow>}
                {view.reviewQueue.items.map((item) => { const high = ["HIGH", "REPORTED", "RESTRICTED"].includes(item.risk); return <Link key={item.id} href={item.href} className="block px-4 py-3.5 hover:bg-soft"><div className="flex items-start justify-between gap-2"><p className="text-sm font-semibold text-ink">{item.title}</p><span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold ${high ? "bg-bad/10 text-bad" : "bg-warn/10 text-warn"}`}>{item.risk === "REPORTED" ? "User reported" : `${item.risk.charAt(0)}${item.risk.slice(1).toLowerCase()} risk`}</span></div><p className="mt-1 line-clamp-2 text-xs text-muted">{item.reason} · {item.age}</p></Link>; })}
              </div></Panel>}

              {view.evidence && <Link href="/source-library" className={`flex items-center gap-3 rounded-2xl border p-4 ${view.evidence.proposed || view.evidence.restrictedLicence ? "border-warn/30 bg-warn/5 hover:bg-warn/10" : "border-line bg-panel hover:bg-soft"}`}><Scale size={20} className="shrink-0 text-warn" /><span className="min-w-0 flex-1"><span className="block text-sm font-semibold text-ink">Source evidence</span><span className="mt-0.5 block text-xs text-muted">{view.evidence.proposed} awaiting approval · {view.evidence.unreviewed} not yet quality-reviewed · {view.evidence.restrictedLicence} restricted licence</span></span><ArrowRight size={16} className="text-warn" /></Link>}
            </aside>
          </div>

          <Panel>
            <PanelTitle title="Continue your work" action="View all recent work" href="/my-workspace" />
            {view.recentWork.length === 0 ? <EmptyRow>Nothing yet. Answers you save, drafts you write and files you upload in Ask Kriton will appear here.</EmptyRow> : (
              <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5">{view.recentWork.map((w) => { const Icon = WORK_ICONS[w.kind] ?? FileText; return <Link href={w.href} key={`${w.kind}-${w.id}`} className="group min-h-32 rounded-xl border border-line p-4 hover:border-brand/40 hover:bg-soft"><div className="mb-4 flex h-9 w-9 items-center justify-center rounded-lg bg-brand/10 text-brand"><Icon size={18} /></div><p className="truncate text-sm font-semibold text-ink group-hover:text-brand">{w.title}</p><p className="mt-1 truncate text-xs text-muted">{w.context}</p><p className="mt-2 text-xs text-muted">{w.verb} {w.age}</p></Link>; })}</div>
            )}
          </Panel>

          <p className="pb-2 text-center text-xs text-muted"><UsersRound size={13} className="mr-1 inline" />Composed for {role} · Live data from {view.workspaceName} · Updated {new Date(view.generatedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</p>
        </>}
      </div>
    </main>
  );
}
