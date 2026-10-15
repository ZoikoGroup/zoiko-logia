"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { FileText, FolderOpen, ShieldCheck, BarChart3 } from "lucide-react";
import { getAuthToken, getCommandCenter, switchCommandCenterContext } from "@/lib/api";
import { useLiveData } from "@/components/overview/useLiveData";
import { ErrorBlock, LoadingBlock, RefreshButton, SignedOutBlock } from "@/components/overview/states";
import { OverviewFrame, ContextStrip, OverviewPanel, Metric, Status, ActionLink, ResearchDesk, NoItems } from "@/components/overview/OverviewUI";

const CONTEXTS = [
  { jurisdiction: "US", framework: "US-GAAP", label: "United States · US GAAP" },
  { jurisdiction: "GB", framework: "IFRS", label: "United Kingdom · IFRS" },
  { jurisdiction: "US", framework: "IFRS", label: "United States · IFRS" },
  { jurisdiction: "GB", framework: "US-GAAP", label: "United Kingdom · US GAAP" },
];
const PERIOD = `FY${new Date().getFullYear()}`;
const CONTROL_LABELS: Record<string, string> = { boundary_enforcement: "Tenant boundary", audit_recording: "Audit recording", source_licensing: "Source licensing", source_authority: "Source approval", human_review: "Human review backlog", escalation_sla: "Escalation SLAs" };

export function CommandCenter() {
  const [contextIndex, setContextIndex] = useState(0);
  const [contextError, setContextError] = useState("");
  const [switching, setSwitching] = useState(false);
  const options = useRef(CONTEXTS[0]);
  const { data: view, error, loading, signedOut, reload } = useLiveData(`command-center:${CONTEXTS[contextIndex].jurisdiction}:${CONTEXTS[contextIndex].framework}`, (token, signal, fresh) => getCommandCenter(token, { ...options.current, period: PERIOD }, signal, fresh));
  async function chooseContext(index: number) {
    if (!view || switching) return;
    setSwitching(true); setContextError("");
    try {
      const next = CONTEXTS[index];
      await switchCommandCenterContext(getAuthToken(), { ...next, period: PERIOD, previous_context_token: view.contextToken });
      options.current = next; setContextIndex(index);
    } catch (err) { setContextError(err instanceof Error ? err.message : "Could not change context."); }
    finally { setSwitching(false); }
  }
  const ctx = CONTEXTS[contextIndex];
  return <OverviewFrame title="Command Center" subtitle="Professional priorities, source-governed answers, and reviewable accounting evidence." actions={!signedOut && <RefreshButton onClick={reload} loading={loading} generatedAt={view?.generatedAt} />}>
    <ContextStrip workspace={view?.workspaceName} jurisdiction={ctx.jurisdiction === "US" ? "United States" : "United Kingdom"} framework={ctx.framework} period={PERIOD}>
      <select aria-label="Change accounting context" disabled={!view || switching} value={contextIndex} onChange={e => void chooseContext(Number(e.target.value))} className="ml-auto w-7 rounded bg-panel text-ink">{CONTEXTS.map((c, i) => <option key={c.label} value={i}>{c.label}</option>)}</select>
    </ContextStrip>
    {contextError && <p role="alert" className="text-xs text-bad">{contextError}</p>}
    {signedOut && <SignedOutBlock />}{error && <ErrorBlock message={error} onRetry={reload} />}{!view && loading && <LoadingBlock label="Loading Command Center" />}
    {view && <>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Metric label="Reviews Awaiting Action" value={view.reviewQueue?.open ?? "—"} detail={view.reviewQueue ? "Open reviews · workspace queue" : "Review access is not available for your role"} href={view.permissions.review ? "/review-tasks" : undefined} />
        <Metric label="Source Approval Exceptions" value={view.evidence?.proposed ?? "—"} detail="Sources awaiting approval" tone="amber" href={view.permissions.source ? "/source-library" : undefined} />
        <Metric label="Items Requiring Attention" value={view.summary.attentionCount} detail={`${view.summary.overdueCount} overdue · across available queues`} tone="red" href="/alerts-center" />
        <Metric label="Upcoming Deadlines" value={view.summary.upcomingDeadlineCount} detail={`Next ${view.summary.deadlineHorizonDays} days · workspace scope`} tone="green" href="/compliance-calendar" />
      </div>
      <div className="grid gap-3 xl:grid-cols-[2.2fr_1fr]"><ResearchDesk /><OverviewPanel title="Quick Actions" subtitle="Start your next professional workflow."><div className="grid grid-cols-2 gap-2">{[
        ["New Workpaper", "/workpapers", FileText], ["Generate Report", "/drafts-reports", BarChart3], ["Build Evidence Pack", "/evidence-packs", FolderOpen], ...(view.permissions.review ? [["Review Exceptions", "/review-tasks", ShieldCheck]] : []),
      ].map(([label, href, Icon]) => { const Glyph = Icon as typeof FileText; return <Link key={String(label)} href={String(href)} className="flex min-h-16 items-center gap-2 rounded-lg border border-line p-3 text-[11px] font-semibold text-ink hover:bg-soft"><Glyph size={18} className="shrink-0 text-brand" />{String(label)}</Link>; })}</div><p className="mt-4 text-[10px] leading-4 text-muted">Actions follow your account permissions and assigned workspace.</p></OverviewPanel></div>
      <div className="grid gap-3 xl:grid-cols-[1.8fr_1fr_1.1fr]">
        <OverviewPanel title="Priority Review Queue" subtitle="Open items requiring professional attention." href="/review-tasks"><div className="overflow-x-auto">{view.reviewQueue?.items.length ? <table><thead><tr><th>Work item</th><th>Risk</th><th>Updated</th><th>Action</th></tr></thead><tbody>{view.reviewQueue.items.slice(0, 4).map(item => <tr key={item.id}><td><b>{item.title}</b><small>{item.reason}</small></td><td><Status>{item.risk}</Status></td><td>{item.age}</td><td><ActionLink href={item.href}>Review</ActionLink></td></tr>)}</tbody></table> : <NoItems>{view.permissions.review ? "Your review queue is empty." : "Review access is not available for your role."}</NoItems>}</div></OverviewPanel>
        <OverviewPanel title="Source & Evidence Assurance" subtitle="Approval, licensing, and source readiness." href={view.permissions.source ? "/source-library" : undefined} action="Source library">{view.evidence ? <div className="divide-y divide-line">{[["Sources in use", view.evidence.inUse], ["Awaiting approval", view.evidence.proposed], ["Not quality-reviewed", view.evidence.unreviewed], ["Restricted licences", view.evidence.restrictedLicence]].map(([label, count]) => <div key={label} className="flex justify-between gap-3 py-3 text-[11px]"><span className="text-ink">{label}</span><b>{count}</b></div>)}</div> : <NoItems>Source data is not available for your role.</NoItems>}</OverviewPanel>
        <OverviewPanel title="Jurisdiction & Compliance" subtitle="Upcoming deadlines for the workspace." href="/compliance-calendar" action="Calendar">{view.deadlines.length ? view.deadlines.slice(0, 4).map(item => <Link href={item.href} key={item.id} className="flex items-start gap-3 border-b border-line py-3 last:border-0"><span className="rounded-md border border-line px-2 py-1 text-[10px] font-bold text-amber-700">{item.date}</span><span className="min-w-0 flex-1"><b className="block text-[11px] text-ink">{item.title}</b><small className="text-[10px] text-muted">{item.context}</small></span><Status>{item.state}</Status></Link>) : <NoItems>No upcoming deadlines.</NoItems>}</OverviewPanel>
      </div>
      <div className="grid gap-3 lg:grid-cols-3">
        <OverviewPanel title="My Active Work" href="/my-workspace" action="My workspace">{view.recentWork.length ? view.recentWork.slice(0, 4).map(item => <Link key={`${item.kind}-${item.id}`} href={item.href} className="flex items-start gap-3 border-b border-line py-3 last:border-0"><FileText size={17} className="mt-1 shrink-0 text-brand" /><span><b className="block text-[11px] text-ink">{item.title}</b><small className="text-[10px] text-muted">{item.context} · {item.age}</small></span></Link>) : <NoItems>Saved answers, drafts, and documents will appear here.</NoItems>}</OverviewPanel>
        <OverviewPanel title="Attention & Recent Updates" href="/alerts-center" action="All alerts">{view.attentionItems.length ? view.attentionItems.slice(0, 4).map(item => <Link key={item.id} href={item.href} className="block border-b border-line py-3 last:border-0"><b className="block text-[11px] text-ink">{item.title}</b><small className="text-[10px] text-muted">{item.context} · {item.due}</small></Link>) : <NoItems>Nothing needs your attention right now.</NoItems>}</OverviewPanel>
        <OverviewPanel title="Governance Snapshot" href="/overview/governance" action="Full dashboard"><div className="mb-2 rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-xs font-semibold text-amber-700">{view.assurance.overallState === "ok" ? "No assurance alerts reported" : "Controls need attention"}</div>{Object.entries(view.assurance.controls).map(([key, state]) => <div key={key} className="flex items-center justify-between gap-2 border-b border-line py-2 last:border-0"><span className="text-[11px] text-ink">{CONTROL_LABELS[key] ?? key}</span><Status>{state === "ok" ? "Passed" : state}</Status></div>)}<p className="mt-3 text-[10px] text-muted">Last audit event {view.assurance.lastAuditEventAge} · Policy {view.assurance.policyVersion}</p></OverviewPanel>
      </div>
    </>}
  </OverviewFrame>;
}
