"use client";

import Link from "next/link";
import { BookOpenCheck, Clock3, FileCheck2, FileText, FolderOpen, MessageSquareText } from "lucide-react";
import { PageHeader } from "@/components/governance/PageHeader";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { getMyWorkspace } from "@/lib/api";
import type { WorkItem } from "@/lib/command-center-types";
import { useLiveData } from "@/components/overview/useLiveData";
import { ErrorBlock, LoadingBlock, RefreshButton, SignedOutBlock } from "@/components/overview/states";

const ICONS: Record<WorkItem["kind"], typeof FileText> = {
  saved_answer: MessageSquareText,
  draft: FileText,
  document: FolderOpen,
  artifact: BookOpenCheck,
  review: FileCheck2,
};

export default function MyWorkspacePage() {
  const { data: view, error, loading, signedOut, reload } = useLiveData("my-workspace", getMyWorkspace);

  const stats = view ? [
    { label: "Saved answers", value: view.counts.savedAnswers, href: "/saved-answers" },
    { label: "Drafts", value: view.counts.drafts, href: "/drafts-reports" },
    { label: "Uploaded documents", value: view.counts.documents, href: "/ask-kriton" },
    { label: "Generated files", value: view.counts.generatedFiles, href: "/ask-kriton" },
    { label: "Reviews you resolved", value: view.counts.reviewsResolved, href: "/review-tasks" },
  ] : [];

  return (
    <main className="flex-1 overflow-y-auto p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <PageHeader
          title="My Workspace"
          subtitle={view ? `${view.user.fullName || view.user.displayName} · ${view.user.role} · ${view.user.email}` : "Your personal activity, pending tasks, and saved items in one place."}
        />
        {!signedOut && <RefreshButton onClick={reload} loading={loading} generatedAt={view?.generatedAt} />}
      </div>

      {signedOut && <SignedOutBlock />}
      {error && <ErrorBlock message={error} onRetry={reload} />}
      {!view && loading && <LoadingBlock label="Loading My Workspace" />}

      {view && <>
        <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-5">
          {stats.map((s) => <Link key={s.label} href={s.href} className="rounded-xl border border-line bg-panel p-4 hover:border-brand/40"><div className="text-2xl font-extrabold text-ink">{s.value}</div><div className="mt-1 text-xs text-muted">{s.label}</div></Link>)}
        </div>

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
          <Card title="Recent Activity">
            {view.recentActivity.length === 0 ? (
              <p className="text-sm text-muted">No activity yet. Save an answer, start a draft or upload a document in <Link href="/ask-kriton" className="text-brand">Ask Kriton</Link> and it will appear here.</p>
            ) : (
              <div className="space-y-3">
                {view.recentActivity.map((item) => {
                  const Icon = ICONS[item.kind] ?? FileText;
                  return (
                    <Link key={`${item.kind}-${item.id}`} href={item.href} className="flex items-start gap-2.5 rounded-lg p-1 hover:bg-soft">
                      <Icon size={15} className="mt-0.5 shrink-0 text-brand" />
                      <div className="min-w-0">
                        <div className="truncate text-sm text-ink">{item.title}</div>
                        <div className="flex items-center gap-1 text-[11px] text-muted"><Clock3 size={11} /> {item.verb} {item.age} · {item.context}</div>
                      </div>
                    </Link>
                  );
                })}
              </div>
            )}
          </Card>

          <Card title="Pending Tasks">
            {view.pendingTasks.length === 0 ? (
              <p className="text-sm text-muted">You have no pending tasks.</p>
            ) : (
              <div className="space-y-3">
                {view.pendingTasks.map((task) => (
                  <Link key={task.id} href={task.href} className="flex items-center justify-between gap-3 rounded-lg p-1 hover:bg-soft">
                    <span className="min-w-0">
                      <span className="block truncate text-sm text-ink">{task.title}</span>
                      <span className="block text-[11px] text-muted">{task.age}</span>
                    </span>
                    <Pill tone={task.tone}>{task.status}</Pill>
                  </Link>
                ))}
                {(view.queues.reviews > 0 || view.queues.escalations > 0) && (
                  <p className="pt-1 text-xs text-muted">
                    Queues: {view.queues.reviews > 0 && <Link href="/review-tasks" className="text-brand">{view.queues.reviews} answers awaiting review</Link>}
                    {view.queues.reviews > 0 && view.queues.escalations > 0 && " · "}
                    {view.queues.escalations > 0 && <Link href="/escalation-queue" className="text-brand">{view.queues.escalations} open escalations</Link>}
                  </p>
                )}
              </div>
            )}
          </Card>
        </div>
      </>}
    </main>
  );
}
