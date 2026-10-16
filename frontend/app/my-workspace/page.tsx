"use client";

import Link from "next/link";
import { useState } from "react";
import { FileText } from "lucide-react";
import { getMyWorkspace } from "@/lib/api";
import { useLiveData } from "@/components/overview/useLiveData";
import { ErrorBlock, LoadingBlock, RefreshButton, SignedOutBlock } from "@/components/overview/states";
import { OverviewFrame, ContextStrip, OverviewPanel, Metric, Status, ActionLink, NavyBanner, ResearchDesk, NoItems } from "@/components/overview/OverviewUI";

export default function MyWorkspacePage() {
  const { data: view, error, loading, signedOut, reload } = useLiveData("my-workspace", getMyWorkspace);
  const [filter, setFilter] = useState("All");
  const tasks = view?.pendingTasks.filter(t => filter === "All" || (filter === "Needs attention" ? t.tone === "bad" || t.tone === "warn" : t.href.includes("review"))) ?? [];
  const recentResearch = view?.recentActivity.find(item => item.kind === "saved_answer");
  return <OverviewFrame title="My Workspace" subtitle="Your assignments, documents, Kriton research, and professional handoffs — all in one place." actions={!signedOut && <RefreshButton onClick={reload} loading={loading} generatedAt={view?.generatedAt} />}>
    <ContextStrip workspace={view?.workspaceName} jurisdiction="Your authorized workspace" framework="Per work item" period="Personal activity" />
    {signedOut && <SignedOutBlock />}{error && <ErrorBlock message={error} onRetry={reload} />}{!view && loading && <LoadingBlock label="Loading My Workspace" />}
    {view && <>
      <NavyBanner eyebrow="Personal professional workspace · your activity" title="Continue where you left off." action={<div className="flex gap-2"><ActionLink href="/ask-kriton">Ask Kriton</ActionLink><Link href="/workpapers" className="rounded-lg bg-[#f28a18] px-4 py-2 text-xs font-bold text-white">+ New Workpaper</Link></div>}>{view.pendingTasks.length} pending tasks · Your work remains scoped to your workspace.</NavyBanner>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><Metric label="My Uploaded Documents" value={view.counts.documents} detail="Documents in your workspace" href="/ask-kriton" /><Metric label="Open Review Queue" value={view.queues.reviews} detail="Role-accessible queue · not personal assignments" tone="amber" href="/review-tasks" /><Metric label="Open Escalation Queue" value={view.queues.escalations} detail="Role-accessible escalations" tone="red" href="/escalation-queue" /><Metric label="Drafts & Saved Outputs" value={view.counts.drafts + view.counts.savedAnswers + view.counts.generatedFiles} detail="Drafts, saved answers, and generated files" tone="green" href="/drafts-reports" /></div>
      <div className="grid gap-3 xl:grid-cols-[1.6fr_1fr]">
        <OverviewPanel title="Resume My Work" subtitle="Pick up your recent documents and research without losing context." href="#documents">{view.recentActivity.length ? <div className="grid gap-3 md:grid-cols-3">{view.recentActivity.slice(0, 3).map(item => <article key={`${item.kind}-${item.id}`} className="flex flex-col rounded-lg border border-line bg-soft/20 p-3"><p className="text-[9px] font-bold uppercase tracking-wider text-muted">{item.kind.replaceAll("_", " ")} · {item.id.slice(0, 8)}</p><h3 className="mt-2 text-xs font-bold text-ink">{item.title}</h3><p className="my-3 text-[10px] leading-4 text-muted">{item.context}</p><div className="mt-auto flex items-center justify-between gap-2 border-t border-line pt-3"><Status>{item.verb}</Status><ActionLink href={item.href}>Continue</ActionLink></div><p className="mt-2 text-[10px] text-muted">Updated {item.age}</p></article>)}</div> : <NoItems>Save an answer or start a draft in Ask Kriton to see it here.</NoItems>}</OverviewPanel>
        <OverviewPanel title="My Attention Queue" subtitle="Pending tasks and requests available to your role." href="#assigned-work" action="View queue">{view.pendingTasks.length ? view.pendingTasks.slice(0, 4).map(task => <Link key={task.id} href={task.href} className="flex items-center justify-between gap-3 border-b border-line py-3 last:border-0"><div><b className="block text-[11px] text-ink">{task.title}</b><small className="text-[10px] text-muted">{task.age}</small></div><Status>{task.status}</Status></Link>) : <NoItems>You have no pending tasks.</NoItems>}</OverviewPanel>
      </div>
      <div className="grid gap-3 xl:grid-cols-[2fr_1fr]">
        <OverviewPanel id="assigned-work" title="My Pending Work" subtitle="Drafts, reviews, and approvals available to your account."><div className="mb-3 flex flex-wrap gap-2">{["All", "Needs attention", "Reviews"].map(label => <button key={label} onClick={() => setFilter(label)} aria-pressed={filter === label} className={`rounded-md border px-3 py-1.5 text-[10px] font-semibold ${filter === label ? "border-amber-500/40 bg-amber-500/10 text-amber-700" : "border-line bg-soft text-muted"}`}>{label}</button>)}</div><div className="overflow-x-auto">{tasks.length ? <table className="min-w-[500px]"><thead><tr><th>Work item / reference</th><th>Updated</th><th>Status</th><th>Action</th></tr></thead><tbody>{tasks.map(task => <tr key={task.id}><td><b>{task.title}</b><small>{task.id.slice(0, 12)}</small></td><td>{task.age}</td><td><Status>{task.status}</Status></td><td><ActionLink href={task.href}>Open</ActionLink></td></tr>)}</tbody></table> : <NoItems>No pending work matches this filter.</NoItems>}</div></OverviewPanel>
        <ResearchDesk compact title="Ask Kriton · Research Desk" recent={recentResearch} />
      </div>
      <div className="grid gap-3 lg:grid-cols-[1.3fr_1fr_1fr]">
        <OverviewPanel id="documents" title="My Documents & Drafts" subtitle="Saved files and AI-assisted outputs." href="/drafts-reports">{view.recentActivity.length ? view.recentActivity.slice(0, 5).map(item => <Link key={`${item.kind}-${item.id}`} href={item.href} className="flex items-center gap-3 border-b border-line py-3 last:border-0"><FileText size={17} className="shrink-0 text-brand" /><span className="min-w-0 flex-1"><b className="block truncate text-[11px] text-ink">{item.title}</b><small className="text-[10px] text-muted">{item.kind.replaceAll("_", " ")} · {item.age}</small></span></Link>) : <NoItems>No saved documents yet.</NoItems>}</OverviewPanel>
        <OverviewPanel title="Upcoming for Me" subtitle="Check the calendar for dated work and handoffs." href="/compliance-calendar" action="Calendar"><NoItems>Personal due dates are not supplied by the workspace feed. Open the compliance calendar for available deadlines.</NoItems><ActionLink href="/compliance-calendar">Open calendar</ActionLink></OverviewPanel>
        <OverviewPanel title="Collaborations & Handoffs" subtitle="Requests and decisions shared with you."><NoItems>Personal handoff records are not supplied by the workspace feed.</NoItems><ActionLink href="/notifications">Open notifications</ActionLink><p className="mt-4 text-[10px] text-muted">{view.counts.reviewsResolved} reviews resolved by you.</p></OverviewPanel>
      </div>
    </>}
  </OverviewFrame>;
}
