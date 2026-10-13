"use client";

import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  BookmarkCheck,
  Briefcase,
  CalendarClock,
  CheckCircle2,
  FileCheck2,
  FileText,
  MessageSquareText,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { timeAgo, useCommandCenter } from "@/hooks/useCommandCenter";
import type { DomainState } from "@/lib/governance-dashboard-types";

const ASSURANCE_LABEL: Record<DomainState, { text: string; className: string }> = {
  critical: { text: "Critical issues open", className: "text-bad" },
  attention: { text: "Needs attention", className: "text-warn" },
  effective: { text: "Controls effective", className: "text-ok" },
  not_assessed: { text: "Not assessed yet", className: "text-muted" },
};

function greeting(date = new Date()): string {
  const hour = date.getHours();
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

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="px-5 py-6 text-sm text-muted">{children}</p>;
}

/** Home page: the signed-in user's real attention items, review queue,
 * deadlines, engagements and recent Kriton work (GET /command-center).
 * Nothing on this page is sample data — empty sections say so. */
export function CommandCenter() {
  const { model, error } = useCommandCenter();

  if (error) {
    return (
      <main className="flex-1 p-4 lg:p-6">
        <p role="alert" className="rounded-xl border border-bad/30 bg-bad/10 px-4 py-3 text-sm text-bad">{error}</p>
      </main>
    );
  }
  if (!model) {
    return (
      <main className="flex-1 p-4 lg:p-6" aria-busy="true">
        <div className="mx-auto max-w-[1500px] space-y-5">
          <div className="h-24 animate-pulse rounded-2xl border border-line bg-panel" />
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
            <div className="h-72 animate-pulse rounded-2xl border border-line bg-panel" />
            <div className="h-72 animate-pulse rounded-2xl border border-line bg-panel" />
          </div>
        </div>
      </main>
    );
  }

  const { counts, assurance } = model;
  const summary = [
    counts.attention ? `${counts.attention} item${counts.attention === 1 ? "" : "s"} need${counts.attention === 1 ? "s" : ""} attention` : null,
    counts.reviews ? `${counts.reviews} decision${counts.reviews === 1 ? "" : "s"} await${counts.reviews === 1 ? "s" : ""} you` : null,
    counts.deadlines ? `${counts.deadlines} deadline${counts.deadlines === 1 ? "" : "s"} in the next 30 days` : null,
  ].filter(Boolean);

  return (
    <main className="flex-1 overflow-y-auto p-4 lg:p-6" aria-labelledby="command-center-title">
      <div className="mx-auto max-w-[1500px] space-y-5">
        <header className="flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <p className="mb-1 text-sm font-medium text-brand">{model.workspace.name}</p>
            <h1 id="command-center-title" className="text-3xl font-semibold tracking-tight text-ink">
              {greeting()}{model.user.firstName ? `, ${model.user.firstName}` : ""}.
            </h1>
            <p className="mt-2 max-w-2xl text-[15px] leading-6 text-muted">
              {summary.length ? `${summary.join(" · ")}.` : "Nothing needs your attention right now."}
            </p>
          </div>
          <div className="flex flex-wrap gap-2.5">
            <Link href="/ask-kriton" className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-brand px-5 text-sm font-semibold text-white shadow-sm hover:bg-brand-2">
              <Sparkles size={17} /> Ask Kriton
            </Link>
            {counts.reviews > 0 && (
              <Link href="/review-tasks" className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-line bg-panel px-4 text-sm font-semibold text-ink hover:bg-soft">
                <FileCheck2 size={16} /> Your decisions <span className="rounded-full bg-soft px-2 text-xs">{counts.reviews}</span>
              </Link>
            )}
          </div>
        </header>

        <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
          <div className="min-w-0 space-y-5">
            <Panel>
              <PanelTitle title="Needs your attention" count={model.attentionItems.length} action="Governance Dashboard" href="/overview/governance" />
              {model.attentionItems.length === 0 ? (
                <Empty><CheckCircle2 size={15} className="mr-1.5 inline text-ok" />No critical or high-priority issues.</Empty>
              ) : (
                <ul className="divide-y divide-line">
                  {model.attentionItems.map((item) => (
                    <li key={item.id} className="grid gap-3 px-5 py-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
                      <div className="flex min-w-0 gap-3">
                        <div className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${item.severity === "critical" ? "bg-bad/10 text-bad" : "bg-warn/10 text-warn"}`}>
                          <AlertTriangle size={17} />
                        </div>
                        <div className="min-w-0">
                          <p className="font-semibold text-ink">{item.title}</p>
                          <p className="mt-0.5 text-sm text-muted">{item.domain} · Owner: {item.ownerRole}</p>
                        </div>
                      </div>
                      <Link href={item.drilldownTarget} className="inline-flex items-center gap-1 text-sm font-semibold text-brand hover:underline">
                        Resolve <ArrowRight size={14} />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>

            <Panel className="overflow-hidden">
              <PanelTitle title="Your engagements" count={model.activeMatters.length} />
              {model.activeMatters.length === 0 ? (
                <Empty>You are not a member of any engagement yet. An administrator can add you to one.</Empty>
              ) : (
                <ul className="divide-y divide-line">
                  {model.activeMatters.map((matter) => (
                    <li key={matter.id} className="flex items-center justify-between gap-3 px-5 py-3.5">
                      <span className="flex min-w-0 items-center gap-2.5">
                        <Briefcase size={16} className="shrink-0 text-brand" />
                        <span className="truncate font-medium text-ink">{matter.name}</span>
                      </span>
                      <span className="shrink-0 text-xs text-muted">{matter.myRole} · {matter.status}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>

          <aside className="space-y-5" aria-label="Deadlines and decisions">
            <Panel>
              <PanelTitle title="Upcoming deadlines" count={model.deadlines.length} />
              {model.deadlines.length === 0 ? (
                <Empty>No deadlines in the next 30 days.</Empty>
              ) : (
                <ul className="divide-y divide-line">
                  {model.deadlines.map((deadline) => (
                    <li key={deadline.id}>
                      <Link href={deadline.href} className="flex gap-3 px-4 py-3.5 hover:bg-soft">
                        <CalendarClock size={18} className={`mt-0.5 shrink-0 ${deadline.overdue ? "text-bad" : "text-warn"}`} />
                        <span className="min-w-0">
                          <span className="block text-sm font-medium text-ink">{deadline.title}</span>
                          <span className={`block text-xs ${deadline.overdue ? "text-bad" : "text-muted"}`}>
                            {deadline.overdue ? "Overdue · " : "Due "}
                            {new Date(deadline.dueAt).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}
                          </span>
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>

            {model.reviewQueue.length > 0 && (
              <Panel>
                <PanelTitle title="Waiting for your decision" count={model.reviewQueue.length} />
                <ul className="divide-y divide-line">
                  {model.reviewQueue.slice(0, 5).map((item) => (
                    <li key={item.id}>
                      <Link href={item.drilldownTarget} className="block px-4 py-3.5 hover:bg-soft">
                        <span className="block text-[11px] font-bold uppercase tracking-wide text-muted">{item.type}</span>
                        <span className="block text-sm font-medium text-ink">{item.title}</span>
                        {item.blockedReason && <span className="block text-xs text-warn">{item.blockedReason}</span>}
                      </Link>
                    </li>
                  ))}
                </ul>
              </Panel>
            )}

            {assurance && (
              <Link href="/overview/governance" className="flex items-center gap-3 rounded-2xl border border-line bg-panel p-4 hover:bg-soft">
                <ShieldCheck size={20} className={`shrink-0 ${ASSURANCE_LABEL[assurance.overallState].className}`} />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-semibold text-ink">Governance: {ASSURANCE_LABEL[assurance.overallState].text}</span>
                  <span className="block text-xs text-muted">
                    {assurance.blockedGates ? `${assurance.blockedGates} release gate${assurance.blockedGates === 1 ? "" : "s"} blocked` : "No release gate blocked"}
                  </span>
                </span>
                <ArrowRight size={16} className="text-muted" />
              </Link>
            )}
          </aside>
        </div>

        <Panel>
          <PanelTitle title="Continue your work" action="All your activity" href="/my-workspace" />
          {model.recentWork.length === 0 ? (
            <Empty>Nothing yet — ask Kriton a question to get started.</Empty>
          ) : (
            <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5">
              {model.recentWork.slice(0, 5).map((item) => {
                const Icon = item.kind === "Saved answer" ? BookmarkCheck : item.kind.startsWith("Draft") ? FileText : MessageSquareText;
                return (
                  <Link key={item.id} href={item.href} className="group min-h-32 rounded-xl border border-line p-4 hover:border-brand/40 hover:bg-soft">
                    <Icon size={18} className="text-brand" />
                    <p className="mt-3 line-clamp-2 text-sm font-semibold text-ink">{item.title}</p>
                    <p className="mt-1 text-xs text-muted">{item.kind} · {timeAgo(item.at)}</p>
                  </Link>
                );
              })}
            </div>
          )}
        </Panel>
      </div>
    </main>
  );
}
