import Link from "next/link";
import { FileSpreadsheet, Plus } from "lucide-react";
import type { ActiveMatter } from "@/types/commandCenter";
import { StatusChip } from "./shared/StatusChip";

const ACTION_LABEL: Record<string, string> = {
  OPEN_MATTER: "Open",
  ASK_KRITON_ABOUT_MATTER: "Ask Kriton",
  ADD_EVIDENCE: "Add evidence",
  CREATE_WORKPAPER: "Create workpaper",
  CREATE_REPORT: "Create report",
  REQUEST_REVIEW: "Request review",
};

function relativeTime(iso: string): string {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hr ago`;
  return `${Math.round(hours / 24)} day${Math.round(hours / 24) === 1 ? "" : "s"} ago`;
}

export function ActiveMatters({ matters, canStartMatter }: { matters: ActiveMatter[]; canStartMatter: boolean }) {
  return (
    <section className="rounded-2xl border border-line bg-panel shadow-[0_1px_2px_rgba(16,24,40,.04)]">
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <h2 className="font-bold text-ink">Active matters</h2>
        <Link href="/workpapers" className="text-xs font-semibold text-brand hover:text-brand-2">View all ({matters.length})</Link>
      </div>

      {matters.length === 0 ? (
        <div className="p-6 text-center">
          <p className="text-sm font-semibold text-ink">No active matters</p>
          <p className="mx-auto mt-1 max-w-sm text-xs text-muted">
            Start a matter to organize analysis, evidence, workpapers and review in one governed workspace.
          </p>
          {canStartMatter && (
            <Link href="/workpapers" className="mt-3 inline-flex items-center gap-1.5 rounded-xl bg-brand px-3.5 py-2 text-xs font-bold text-white hover:bg-brand-2">
              <Plus size={14} /> Start a matter
            </Link>
          )}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-line">
                <th scope="col" className="px-5 py-2.5 text-left text-[11px] font-bold uppercase tracking-wide text-muted">Matter</th>
                <th scope="col" className="px-3 py-2.5 text-left text-[11px] font-bold uppercase tracking-wide text-muted">Status</th>
                <th scope="col" className="px-3 py-2.5 text-left text-[11px] font-bold uppercase tracking-wide text-muted">Due / next action</th>
                <th scope="col" className="px-3 py-2.5 text-left text-[11px] font-bold uppercase tracking-wide text-muted">Evidence</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {matters.map((m) => (
                <tr key={m.matterId}>
                  <td className="px-5 py-3">
                    <Link href="/workpapers" className="flex min-w-0 items-start gap-2.5">
                      <FileSpreadsheet size={17} className="mt-0.5 shrink-0 text-brand" />
                      <span className="min-w-0">
                        <span className="block truncate font-semibold text-ink">{m.title}</span>
                        <span className="block truncate text-[11px] text-muted">{m.entityName} · {m.topic}</span>
                      </span>
                    </Link>
                  </td>
                  <td className="px-3 py-3"><StatusChip status={m.workflowState} /></td>
                  <td className="px-3 py-3">
                    <p className="text-ink">{m.nextAction}</p>
                    <p className="mt-0.5 text-[11px] text-muted">
                      {m.dueAt && `Due ${new Date(m.dueAt).toLocaleDateString()} · `}Updated {relativeTime(m.lastActivityAt)}
                    </p>
                  </td>
                  <td className="px-3 py-3">
                    <span
                      className="text-ink"
                      title={`${m.evidenceCount - m.unresolvedEvidenceCount} of ${m.evidenceCount} required evidence items attached`}
                    >
                      {m.evidenceCount} source{m.evidenceCount === 1 ? "" : "s"}
                    </span>
                    {m.unresolvedEvidenceCount > 0 && (
                      <span className="ml-1.5 text-[11px] font-semibold text-warn">{m.unresolvedEvidenceCount} unresolved</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
