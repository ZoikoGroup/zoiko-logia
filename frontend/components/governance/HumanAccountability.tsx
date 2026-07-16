import type { AccountabilitySummary } from "@/types/governance";
import { StateBadge } from "./shared/StateBadge";

export function HumanAccountability({ summary }: { summary: AccountabilitySummary }) {
  const stats: { label: string; value: number; warn?: boolean }[] = [
    { label: "Mandatory reviews", value: summary.mandatoryReviews },
    { label: "Overdue reviews", value: summary.overdueReviews, warn: summary.overdueReviews > 0 },
    { label: "Boundary escalations", value: summary.boundaryEscalations },
    { label: "Accepted exceptions", value: summary.acceptedExceptions },
  ];

  return (
    <section className="rounded-2xl border border-line bg-panel shadow-[0_1px_2px_rgba(16,24,40,.04)]">
      <div className="border-b border-line px-5 py-4">
        <p className="text-[10px] font-bold uppercase tracking-[.16em] text-muted">Oversight & sign-off</p>
        <h2 className="font-bold text-ink">Human accountability</h2>
      </div>
      <div className="grid grid-cols-2 gap-3 p-4">
        {stats.map((s) => (
          <div key={s.label} className="rounded-xl border border-line bg-soft p-3">
            <p className={`text-2xl font-bold ${s.warn ? "text-warn" : "text-ink"}`}>{s.value}</p>
            <p className="mt-0.5 text-[11px] text-muted">{s.label}</p>
          </div>
        ))}
      </div>
      <div className="space-y-2 border-t border-line px-4 py-3">
        <div className="flex items-center justify-between text-xs">
          <span className="text-muted">Reviewer coverage</span>
          <StateBadge state={summary.reviewerCoverageState} size="sm" />
        </div>
        <div className="flex items-center justify-between text-xs">
          <span className="text-muted">Trace completeness</span>
          <StateBadge state={summary.traceCompletenessState} size="sm" />
        </div>
      </div>
    </section>
  );
}
