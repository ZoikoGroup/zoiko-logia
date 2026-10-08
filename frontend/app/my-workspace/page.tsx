"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PageHeader } from "@/components/governance/PageHeader";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { CheckSquare, ClipboardCheck, Clock3, FileText, Loader2, MessageSquareText, ScrollText, ShieldAlert } from "lucide-react";
import { getMyWorkspace, type MyWorkspace, type WorkspaceActivity } from "@/lib/my-workspace-api";

const ACTIVITY_ICON: Record<WorkspaceActivity["kind"], typeof FileText> = {
  saved_answer: MessageSquareText,
  draft: FileText,
  review: CheckSquare,
  escalation: ShieldAlert,
  audit: ScrollText,
};

function relativeTime(iso: string | null): string {
  if (!iso) return "";
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  if (minutes < 1440) return `${Math.round(minutes / 60)}h ago`;
  return `${Math.round(minutes / 1440)}d ago`;
}

export default function MyWorkspacePage() {
  const [data, setData] = useState<MyWorkspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    getMyWorkspace(controller.signal)
      .then(setData)
      .catch((err) => { if (err?.name !== "AbortError") setError("Could not load your workspace from the server."); })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  return (
    <main className="flex-1 overflow-y-auto p-4">
      <PageHeader title="My Workspace" subtitle="Your personal activity, pending tasks, and saved items in one place." />
      {error && <p className="mb-3 text-sm text-bad">{error}</p>}

      {loading ? (
        <div className="flex items-center justify-center py-12 text-muted"><Loader2 className="mr-2 animate-spin" size={16} /> Loading your workspace…</div>
      ) : data && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          <Card title="Recent Activity">
            {data.recentActivity.length ? (
              <div className="space-y-3">
                {data.recentActivity.map((item) => {
                  const Icon = ACTIVITY_ICON[item.kind] ?? FileText;
                  return (
                    <Link key={item.id} href={item.href} className="flex items-start gap-2.5 rounded-lg hover:bg-soft">
                      <Icon size={15} className="text-brand mt-0.5 shrink-0" />
                      <div>
                        <div className="text-sm text-ink">{item.label}</div>
                        <div className="text-[11px] text-muted flex items-center gap-1"><Clock3 size={11} /> {relativeTime(item.at)}</div>
                      </div>
                    </Link>
                  );
                })}
              </div>
            ) : <p className="py-4 text-center text-sm text-muted">No activity yet. Saved answers, drafts and reviews you complete appear here.</p>}
          </Card>

          <Card title="Pending Tasks">
            {data.pendingTasks.length ? (
              <div className="space-y-3">
                {data.pendingTasks.map((task) => (
                  <Link key={task.id} href={task.href} className="flex items-center justify-between gap-2 rounded-lg hover:bg-soft">
                    <span className="flex items-center gap-2 text-sm text-ink"><ClipboardCheck size={14} className="shrink-0 text-muted" />{task.label}</span>
                    <Pill tone={task.tone}>{task.status}</Pill>
                  </Link>
                ))}
              </div>
            ) : <p className="py-4 text-center text-sm text-muted">Nothing is waiting on you.</p>}
          </Card>
        </div>
      )}
    </main>
  );
}
