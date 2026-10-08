"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  BookOpenCheck,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  FileCheck2,
  FileText,
  FolderOpen,
  Loader2,
  MessageSquareText,
  Plus,
  RotateCcw,
  Scale,
  ShieldCheck,
  Siren,
  Sparkles,
  UsersRound,
} from "lucide-react";
import { useRole } from "@/components/shell/RoleProvider";
import { useAuth } from "@/hooks/useAuth";
import { getAuthToken, getCommandCenter, switchCommandCenterContext } from "@/lib/api";

// Shape returned by GET /api/v1/command-center (backend/app/domains/command_center).
type Freshness = { state: string; failedReason?: string };
type AttentionItem = {
  id: string; kind: "escalation" | "incident" | "source_licence"; level: "high" | "attention" | "info";
  title: string; context: string; dueAt: string | null; daysRemaining?: number; action: string; href: string;
};
type Matter = { id: string; name: string; status: string; createdAt: string | null; href: string };
type Deadline = { id: string; title: string; context: string; dueAt: string | null; state: "overdue" | "approaching" | "scheduled"; href: string };
type ReviewItem = { id: string; title: string; riskLevel: string; reason: string; source: string; status: string; createdAt: string | null; href: string };
type RecentItem = { id: string; kind: "saved_answer" | "draft"; title: string; subtitle: string; at: string | null; href: string };
type CommandCenterData = {
  contextToken: string;
  activeContext: { workspaceName: string; jurisdictionCode: string; frameworkCode: string; periodLabel: string };
  professionalSummary: { attentionCount: number; reviewCount: number; deadlineCount: number };
  attentionItems: AttentionItem[];
  activeMatters: Matter[];
  deadlines: Deadline[];
  reviewQueue: ReviewItem[];
  recentWork: RecentItem[];
  assuranceStatus: { overallState: string; controls: Record<string, string>; policyVersion: string };
  moduleFreshness: Record<string, Freshness>;
};

type Context = { jurisdiction: string; framework: string; period: string };
const DEFAULT_CONTEXT: Context = { jurisdiction: "US", framework: "US-GAAP", period: "FY2026" };
// The combinations POST /command-center/context accepts (command_center/router.py).
const CONTEXT_CHOICES = {
  jurisdiction: [["US", "United States"], ["GB", "United Kingdom"]],
  framework: [["US-GAAP", "US GAAP"], ["IFRS", "IFRS"]],
  period: [["FY2026", "FY2026"], ["FY2025", "FY2025"]],
} as const;

const ATTENTION_ICON = { escalation: AlertTriangle, incident: Siren, source_licence: CircleAlert } as const;

function relativeTime(iso: string | null): string {
  if (!iso) return "";
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (Math.abs(minutes) < 1) return "just now";
  const future = minutes < 0;
  const abs = Math.abs(minutes);
  const text = abs < 60 ? `${abs} min` : abs < 1440 ? `${Math.round(abs / 60)} hr` : `${Math.round(abs / 1440)} days`;
  return future ? `in ${text}` : `${text} ago`;
}

function shortDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "";
}

function greeting(): string {
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

function PanelEmpty({ freshness, empty }: { freshness?: Freshness; empty: string }) {
  const text = freshness?.state === "restricted" ? "Your role cannot see this panel." : freshness?.state === "current" || !freshness ? empty : freshness.failedReason || "Not available yet.";
  return <p className="px-5 py-6 text-center text-sm text-muted">{text}</p>;
}

export function CommandCenter() {
  const { role } = useRole();
  const { user, profile } = useAuth();
  const [newOpen, setNewOpen] = useState(false);
  const [assuranceOpen, setAssuranceOpen] = useState(false);
  const [data, setData] = useState<CommandCenterData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [context, setContext] = useState<Context>(DEFAULT_CONTEXT);
  const [contextOpen, setContextOpen] = useState(false);
  const [contextError, setContextError] = useState("");
  const hasReviewAuthority = ["CFO", "Controller", "Audit Partner", "Finance Manager", "AI Governance Lead", "Admin"].includes(role);
  const firstName = (profile?.full_name || user?.user_metadata?.full_name || "").split(" ")[0];

  useEffect(() => {
    const controller = new AbortController();
    getCommandCenter(getAuthToken(), context, controller.signal)
      .then((result) => { setData(result as unknown as CommandCenterData); setError(""); })
      .catch((err) => { if (err?.name !== "AbortError") setError("Could not load the Command Center from the server."); })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [context]);

  async function changeContext(next: Context) {
    setContextError("");
    try {
      await switchCommandCenterContext(getAuthToken(), { ...next, previous_context_token: data?.contextToken ?? "" });
      setContextOpen(false);
      setContext(next);
    } catch (err) {
      setContextError((err instanceof Error && err.message) || "That accounting context is not available.");
    }
  }

  const summary = data?.professionalSummary;
  const freshness = data?.moduleFreshness ?? {};
  const assuranceOk = data?.assuranceStatus.overallState === "ok";
  const activeContext = data?.activeContext;

  return (
    <main className="flex-1 overflow-y-auto p-4 lg:p-6" aria-labelledby="command-center-title">
      <div className="mx-auto max-w-[1500px] space-y-5">
        <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-line bg-panel p-2.5 shadow-sm">
          <div className="relative min-w-[280px] flex-1">
            <button onClick={() => setContextOpen((v) => !v)} aria-expanded={contextOpen} className="flex min-h-12 w-full items-center justify-between gap-4 rounded-xl px-3 text-left hover:bg-soft" aria-label="Change accounting context">
              <span className="min-w-0"><span className="block truncate text-sm font-semibold text-ink">{activeContext?.workspaceName ?? "Current workspace"}</span><span className="block truncate text-xs text-muted">{activeContext ? `${activeContext.jurisdictionCode} · ${activeContext.frameworkCode} · ${activeContext.periodLabel}` : "Loading context…"}</span></span>
              <ChevronDown size={17} className="shrink-0 text-muted" />
            </button>
            {contextOpen && (
              <div className="absolute left-0 top-full z-20 mt-2 w-80 space-y-3 rounded-xl border border-line bg-panel p-4 shadow-xl">
                <p className="font-semibold text-ink">Accounting context</p>
                {(Object.keys(CONTEXT_CHOICES) as (keyof Context)[]).map((field) => (
                  <label key={field} className="block text-xs font-semibold capitalize text-muted">
                    {field}
                    <select value={context[field]} onChange={(e) => void changeContext({ ...context, [field]: e.target.value })} className="mt-1 block w-full rounded-lg border border-line bg-panel px-2 py-1.5 text-sm font-normal normal-case text-ink">
                      {CONTEXT_CHOICES[field].map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select>
                  </label>
                ))}
                {contextError && <p className="text-xs text-bad" role="alert">{contextError}</p>}
                <p className="text-xs text-muted">Each change is recorded in the audit ledger.</p>
              </div>
            )}
          </div>
          <div className="hidden h-8 w-px bg-line sm:block" />
          {data?.assuranceStatus.controls.boundary_enforcement === "ok" && <span className="flex min-h-11 items-center gap-2 rounded-xl px-3 text-sm font-medium text-ink"><ShieldCheck size={17} className="text-brand" /> Workspace boundary enforced</span>}
          <div className="relative">
            <button onClick={() => setAssuranceOpen((v) => !v)} aria-expanded={assuranceOpen} className="flex min-h-11 items-center gap-2 rounded-xl px-3 text-sm font-medium text-ink hover:bg-soft">{assuranceOk ? <CheckCircle2 size={17} className="text-ok" /> : <CircleAlert size={17} className="text-warn" />} {assuranceOk ? "Assurance active" : "Assurance not fully assessed"} <ChevronDown size={14} /></button>
            {assuranceOpen && data && <div className="absolute right-0 top-full z-20 mt-2 w-80 rounded-xl border border-line bg-panel p-4 shadow-xl"><p className="font-semibold text-ink">Kriton assurance controls</p><ul className="mt-2 space-y-1 text-sm">{Object.entries(data.assuranceStatus.controls).map(([name, state]) => <li key={name} className="flex justify-between gap-3"><span className="text-muted">{name.replace(/_/g, " ")}</span><span className={state === "ok" ? "text-ok" : "text-warn"}>{state}</span></li>)}</ul><p className="mt-3 text-xs text-muted">Policy {data.assuranceStatus.policyVersion}</p></div>}
          </div>
        </div>

        <header className="flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <p className="mb-1 text-sm font-medium text-brand">Command Center</p>
            <h1 id="command-center-title" className="text-3xl font-semibold tracking-tight text-ink">{greeting()}{firstName ? `, ${firstName}` : ""}.</h1>
            <p className="mt-2 max-w-2xl text-[15px] leading-6 text-muted">{summary ? <>{summary.attentionCount} {summary.attentionCount === 1 ? "item needs" : "items need"} attention. {hasReviewAuthority ? `${summary.reviewCount} ${summary.reviewCount === 1 ? "review awaits" : "reviews await"} a decision. ` : ""}{summary.deadlineCount} {summary.deadlineCount === 1 ? "deadline falls" : "deadlines fall"} within the next 14 days.</> : loading ? "Loading your workspace…" : ""}</p>
            {error && <p className="mt-2 text-sm text-bad">{error}</p>}
          </div>
          <div className="flex flex-wrap gap-2.5">
            <Link href="/ask-kriton" className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-brand px-5 text-sm font-semibold text-white shadow-sm hover:bg-brand-2"><Sparkles size={17} /> Ask Kriton</Link>
            <Link href="/my-workspace" className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-line bg-panel px-4 text-sm font-semibold text-ink hover:bg-soft"><RotateCcw size={16} /> Resume work</Link>
            {hasReviewAuthority && <Link href="/review-tasks" className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-line bg-panel px-4 text-sm font-semibold text-ink hover:bg-soft"><FileCheck2 size={16} /> Review queue {summary && summary.reviewCount > 0 && <span className="rounded-full bg-bad/10 px-1.5 text-xs text-bad">{summary.reviewCount}</span>}</Link>}
            <div className="relative">
              <button onClick={() => setNewOpen((v) => !v)} aria-expanded={newOpen} className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-line bg-panel px-4 text-sm font-semibold text-ink hover:bg-soft"><Plus size={16} /> New <ChevronDown size={14} /></button>
              {newOpen && <div className="absolute right-0 top-full z-20 mt-2 w-56 overflow-hidden rounded-xl border border-line bg-panel p-1.5 shadow-xl">{[["Start a matter", "/workpapers"], ["Upload evidence", "/evidence-packs"], ["Add entity or client", "/entities-clients"], ["Create workpaper", "/workpapers"], ["Create report", "/drafts-reports"]].map(([label, href]) => <Link key={label} href={href} className="block rounded-lg px-3 py-2.5 text-sm text-ink hover:bg-soft">{label}</Link>)}</div>}
            </div>
          </div>
        </header>

        {loading ? (
          <div className="flex items-center justify-center py-16 text-muted"><Loader2 className="mr-2 animate-spin" size={16} /> Loading Command Center…</div>
        ) : (
          <>
            <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
              <div className="min-w-0 space-y-5">
                <Panel>
                  <PanelTitle title="Needs your attention" count={summary?.attentionCount ?? 0} action="View all" href="/alerts-center" />
                  {data?.attentionItems.length ? (
                    <div className="divide-y divide-line">
                      {data.attentionItems.map((item) => {
                        const Icon = ATTENTION_ICON[item.kind] ?? CircleAlert;
                        const high = item.level === "high";
                        const due = item.daysRemaining !== undefined ? (item.daysRemaining < 0 ? `Expired ${-item.daysRemaining} days ago` : `${item.daysRemaining} days left`) : item.dueAt ? `Due ${relativeTime(item.dueAt)}` : "";
                        return <div key={item.id} className="grid gap-3 px-5 py-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"><div className="flex min-w-0 gap-3"><div className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${high ? "bg-bad/10 text-bad" : "bg-warn/10 text-warn"}`}><Icon size={18} /></div><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className={`text-xs font-bold uppercase tracking-wide ${high ? "text-bad" : "text-warn"}`}>{high ? "High" : "Attention"}</span>{due && <span className="text-xs text-muted">{due}</span>}</div><h3 className="mt-1 text-sm font-semibold text-ink">{item.title}</h3><p className="mt-0.5 text-sm text-muted">{item.context}</p></div></div><Link href={item.href} className="ml-12 inline-flex min-h-10 items-center gap-1.5 text-sm font-semibold text-brand sm:ml-0">{item.action}<ArrowRight size={14} /></Link></div>;
                      })}
                    </div>
                  ) : <PanelEmpty freshness={freshness.attentionItems} empty="Nothing needs your attention right now." />}
                </Panel>

                <Panel className="overflow-hidden">
                  <PanelTitle title="Active matters" count={data?.activeMatters.length ?? 0} action="View all matters" href="/workpapers" />
                  {data?.activeMatters.length ? (
                    <div className="overflow-x-auto">
                      <table className="w-full min-w-[560px] text-left text-sm">
                        <thead><tr className="bg-soft/70 text-xs uppercase tracking-wide text-muted"><th scope="col" className="px-5 py-3 font-semibold">Matter</th><th scope="col" className="px-4 py-3 font-semibold">Status</th><th scope="col" className="px-5 py-3 font-semibold">Opened</th></tr></thead>
                        <tbody className="divide-y divide-line">{data.activeMatters.map((matter) => <tr key={matter.id} className="group hover:bg-soft/50"><th scope="row" className="px-5 py-4 font-normal"><Link href={matter.href} className="font-semibold text-ink group-hover:text-brand">{matter.name}</Link></th><td className="px-4 py-4"><span className="inline-flex rounded-full bg-info/10 px-2.5 py-1 text-xs font-semibold capitalize text-info">{matter.status}</span></td><td className="px-5 py-4 text-muted">{shortDate(matter.createdAt)}</td></tr>)}</tbody>
                      </table>
                    </div>
                  ) : <PanelEmpty freshness={freshness.activeMatters} empty="You are not a member of any active matter yet." />}
                </Panel>
              </div>

              <aside className="space-y-5" aria-label="Command Center supporting information">
                <Panel>
                  <PanelTitle title="Upcoming deadlines" action="View calendar" href="/compliance-calendar" />
                  {data?.deadlines.length ? (
                    <div className="divide-y divide-line">{data.deadlines.map((deadline) => { const tone = deadline.state === "overdue" ? "bad" : deadline.state === "approaching" ? "warn" : "muted"; return <Link href={deadline.href} key={deadline.id} className="flex gap-3 px-4 py-3.5 hover:bg-soft"><div className={`mt-0.5 flex h-10 w-10 shrink-0 flex-col items-center justify-center rounded-lg ${tone === "bad" ? "bg-bad/10 text-bad" : tone === "warn" ? "bg-warn/10 text-warn" : "bg-soft text-muted"}`}><CalendarDays size={16} /></div><div className="min-w-0 flex-1"><p className="text-sm font-semibold text-ink">{deadline.title}</p><p className="mt-0.5 truncate text-xs text-muted">{deadline.context}</p></div><span className={`text-xs font-semibold ${tone === "bad" ? "text-bad" : tone === "warn" ? "text-warn" : "text-muted"}`}>{deadline.state === "overdue" ? "Overdue" : shortDate(deadline.dueAt)}</span></Link>; })}</div>
                  ) : <PanelEmpty freshness={freshness.deadlines} empty="No deadlines in the next 14 days." />}
                </Panel>

                {hasReviewAuthority && (
                  <Panel>
                    <PanelTitle title="Review queue" count={summary?.reviewCount ?? 0} action="Open queue" href="/review-tasks" />
                    {data?.reviewQueue.length ? (
                      <div className="divide-y divide-line">{data.reviewQueue.map((item) => <Link key={item.id} href={item.href} className="block px-4 py-3.5 hover:bg-soft"><div className="flex items-start justify-between gap-2"><p className="text-sm font-semibold text-ink">{item.title}</p>{item.riskLevel && <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold ${item.riskLevel === "HIGH" || item.riskLevel === "RESTRICTED" ? "bg-bad/10 text-bad" : "bg-warn/10 text-warn"}`}>{item.riskLevel.charAt(0) + item.riskLevel.slice(1).toLowerCase()}</span>}</div><p className="mt-1 text-xs text-muted">{item.source === "user_feedback" ? "Reported by a user" : "Escalated by Kriton"} · {relativeTime(item.createdAt)}</p></Link>)}</div>
                    ) : <PanelEmpty freshness={freshness.reviewQueue} empty="No reviews are waiting." />}
                  </Panel>
                )}

                <Link href="/evidence-packs" className="flex items-center gap-3 rounded-2xl border border-line bg-panel p-4 hover:bg-soft"><Scale size={20} className="shrink-0 text-brand" /><span className="min-w-0 flex-1"><span className="block text-sm font-semibold text-ink">Evidence packs</span><span className="mt-0.5 block text-xs text-muted">Open the supporting evidence for your matters</span></span><ArrowRight size={16} className="text-brand" /></Link>
              </aside>
            </div>

            <Panel>
              <PanelTitle title="Continue your work" action="View all recent work" href="/my-workspace" />
              {data?.recentWork.length ? (
                <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5">{data.recentWork.map((item) => { const Icon = item.kind === "draft" ? FileText : MessageSquareText; return <Link href={item.href} key={`${item.kind}:${item.id}`} className="group min-h-32 rounded-xl border border-line p-4 hover:border-brand/40 hover:bg-soft"><div className="mb-4 flex h-9 w-9 items-center justify-center rounded-lg bg-brand/10 text-brand"><Icon size={18} /></div><p className="truncate text-sm font-semibold text-ink group-hover:text-brand">{item.title}</p><p className="mt-1 truncate text-xs text-muted">{item.subtitle}</p><p className="mt-2 text-xs text-muted">{relativeTime(item.at)}</p></Link>; })}</div>
              ) : (
                <div className="flex flex-col items-center gap-3 px-5 py-8 text-center"><p className="text-sm text-muted">No saved answers or drafts yet.</p><div className="flex gap-2"><Link href="/ask-kriton" className="inline-flex items-center gap-1.5 text-sm font-semibold text-brand"><BookOpenCheck size={15} /> Ask Kriton</Link><Link href="/saved-answers" className="inline-flex items-center gap-1.5 text-sm font-semibold text-brand"><FolderOpen size={15} /> Saved answers</Link></div></div>
              )}
            </Panel>
          </>
        )}

        <p className="pb-2 text-center text-xs text-muted"><UsersRound size={13} className="mr-1 inline" />Composed for {role}{data ? " · Live data" : ""}</p>
      </div>
    </main>
  );
}
