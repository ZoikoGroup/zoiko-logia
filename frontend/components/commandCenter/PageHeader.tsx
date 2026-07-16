"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronRight, MessageSquareText, Plus, RotateCcw, X } from "lucide-react";
import type { ActiveContext, ActiveMatter, ProfessionalSummary } from "@/types/commandCenter";

const NON_TERMINAL: ActiveMatter["workflowState"][] = [
  "DRAFT", "IN_PROGRESS", "WAITING_FOR_EVIDENCE", "WAITING_FOR_CLIENT", "WAITING_FOR_REVIEWER", "CHANGES_REQUESTED",
];

function greetingForHour(hour: number): string {
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

export function PageHeader({
  context,
  summary,
  preferredName,
  activeMatters,
  reviewCount,
  hasReviewAuthority,
  canCreateMatter,
  canUploadEvidence,
  canAddEntity,
  canCreateWorkpaper,
  canCreateReport,
}: {
  context: ActiveContext;
  summary: ProfessionalSummary;
  preferredName: string;
  activeMatters: ActiveMatter[];
  reviewCount: number;
  hasReviewAuthority: boolean;
  canCreateMatter: boolean;
  canUploadEvidence: boolean;
  canAddEntity: boolean;
  canCreateWorkpaper: boolean;
  canCreateReport: boolean;
}) {
  const [showKritonConfirm, setShowKritonConfirm] = useState(false);
  const [showResumeChooser, setShowResumeChooser] = useState(false);

  const greeting = `${greetingForHour(new Date().getHours())}, ${preferredName}.`;

  const resumable = [...activeMatters]
    .filter((m) => NON_TERMINAL.includes(m.workflowState))
    .sort((a, b) => new Date(b.lastActivityAt).getTime() - new Date(a.lastActivityAt).getTime());

  const summaryLines: string[] = [];
  if (summary.attentionCount > 0) summaryLines.push(`${summary.attentionCount} matters require attention.`);
  if (summary.reviewCount > 0) summaryLines.push(`${summary.reviewCount} reviews await your decision.`);
  if (summary.deadlineCount > 0) summaryLines.push(`${summary.deadlineCount} deadlines fall within the next 14 days.`);

  return (
    <div className="space-y-3">
      <div>
        <p className="text-xs font-bold uppercase tracking-[.16em] text-brand">Command Center</p>
        <h1 className="mt-1 text-3xl font-bold tracking-tight text-ink sm:text-4xl">{greeting}</h1>
        {summaryLines.length > 0 && (
          <p className="mt-1.5 text-sm text-muted">{summaryLines.slice(0, 3).join(" ")}</p>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={() => setShowKritonConfirm(true)}
          className="inline-flex h-12 items-center gap-2 rounded-xl bg-brand px-5 text-sm font-bold text-white hover:bg-brand-2"
        >
          <MessageSquareText size={17} /> Ask Kriton
        </button>

        {resumable.length > 0 ? (
          <div className="relative">
            <button
              onClick={() => (resumable.length > 1 ? setShowResumeChooser((v) => !v) : undefined)}
              className="inline-flex h-12 items-center gap-2 rounded-xl border border-line bg-panel px-4 text-sm font-semibold text-ink hover:bg-soft"
            >
              <RotateCcw size={15} /> Resume work
            </button>
            {resumable.length > 1 && showResumeChooser && (
              <div className="absolute left-0 top-14 z-20 w-72 rounded-xl border border-line bg-panel p-1.5 shadow-lg">
                {resumable.slice(0, 5).map((m) => (
                  <Link
                    key={m.matterId}
                    href="/workpapers"
                    className="flex items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-left text-xs hover:bg-soft"
                  >
                    <span className="min-w-0 truncate font-semibold text-ink">{m.title}</span>
                    <ChevronRight size={13} className="shrink-0 text-muted" />
                  </Link>
                ))}
              </div>
            )}
          </div>
        ) : (
          canCreateMatter && (
            <Link href="/workpapers" className="inline-flex h-12 items-center gap-2 rounded-xl border border-line bg-panel px-4 text-sm font-semibold text-ink hover:bg-soft">
              <Plus size={15} /> Start a matter
            </Link>
          )
        )}

        {hasReviewAuthority && reviewCount > 0 && (
          <Link href="/review-tasks" className="relative inline-flex h-12 items-center gap-2 rounded-xl border border-line bg-panel px-4 text-sm font-semibold text-ink hover:bg-soft">
            Review queue
            <span className="grid h-5 min-w-5 place-items-center rounded-full bg-bad px-1 text-[10px] font-bold text-white">
              {reviewCount > 99 ? "99+" : reviewCount}
            </span>
          </Link>
        )}

        <details className="group relative">
          <summary className="flex h-12 cursor-pointer list-none items-center gap-1.5 rounded-xl border border-line bg-panel px-4 text-sm font-semibold text-ink hover:bg-soft">
            <Plus size={15} /> New
          </summary>
          <div className="absolute left-0 top-14 z-20 w-60 rounded-xl border border-line bg-panel p-1.5 shadow-lg">
            {canCreateMatter && <Link href="/workpapers" className="block rounded-lg px-2.5 py-2 text-xs font-semibold text-ink hover:bg-soft">Start a matter</Link>}
            {canUploadEvidence && <Link href="/evidence-packs" className="block rounded-lg px-2.5 py-2 text-xs font-semibold text-ink hover:bg-soft">Upload evidence</Link>}
            {canAddEntity && <Link href="/entities-clients" className="block rounded-lg px-2.5 py-2 text-xs font-semibold text-ink hover:bg-soft">Add entity/client</Link>}
            {canCreateWorkpaper && <Link href="/workpapers" className="block rounded-lg px-2.5 py-2 text-xs font-semibold text-ink hover:bg-soft">Create workpaper</Link>}
            {canCreateReport && <Link href="/reports-insights" className="block rounded-lg px-2.5 py-2 text-xs font-semibold text-ink hover:bg-soft">Create report</Link>}
          </div>
        </details>
      </div>

      {showKritonConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true">
          <div className="w-full max-w-sm rounded-2xl border border-line bg-panel p-5 shadow-xl">
            <div className="flex items-start justify-between gap-3">
              <p className="text-sm font-bold text-ink">Ask Kriton will inherit</p>
              <button onClick={() => setShowKritonConfirm(false)} aria-label="Close" className="text-muted hover:text-ink"><X size={15} /></button>
            </div>
            <ul className="mt-3 space-y-1.5 text-xs text-ink">
              <li>Workspace: {context.workspaceName}</li>
              {context.entityName && <li>Entity: {context.entityName}</li>}
              {context.jurisdictionCode && <li>Jurisdiction: {context.jurisdictionCode}</li>}
              {context.frameworkCode && <li>Framework: {context.frameworkCode}</li>}
              {context.periodLabel && <li>Period: {context.periodLabel}</li>}
              {context.matterId && <li>Matter: {context.matterId}</li>}
            </ul>
            <p className="mt-2.5 text-[11px] text-muted">
              Kriton will not broaden this context without asking you first.
            </p>
            <div className="mt-3 flex justify-end gap-2">
              <button onClick={() => setShowKritonConfirm(false)} className="rounded-lg border border-line px-3 py-1.5 text-xs font-semibold text-muted hover:bg-soft">
                Cancel
              </button>
              <Link href="/ask-kriton" className="rounded-lg bg-brand px-3 py-1.5 text-xs font-bold text-white hover:bg-brand-2">
                Continue to Ask Kriton
              </Link>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
