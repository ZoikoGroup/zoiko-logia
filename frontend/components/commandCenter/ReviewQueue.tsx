import Link from "next/link";
import type { ReviewQueueItem } from "@/types/commandCenter";

const RISK_TONE: Record<string, string> = {
  HIGH: "text-bad bg-bad/10 border-bad/30",
  MEDIUM: "text-warn bg-warn/10 border-warn/30",
  LOW: "text-muted bg-soft border-line",
};

// Renders only for users with review authority/assigned review work — an
// unauthorized user must see nothing here, never a disabled placeholder.
export function ReviewQueue({ items }: { items: ReviewQueueItem[] }) {
  if (items.length === 0) return null;

  return (
    <section className="rounded-2xl border border-line bg-panel shadow-[0_1px_2px_rgba(16,24,40,.04)]">
      <div className="flex items-center justify-between border-b border-line px-4 py-3.5">
        <h2 className="text-sm font-bold text-ink">Review queue</h2>
        <Link href="/review-tasks" className="text-xs font-semibold text-brand hover:text-brand-2">View all</Link>
      </div>
      <ul className="divide-y divide-line">
        {items.map((r) => (
          <li key={r.reviewId} className="p-3.5">
            <div className="flex items-start justify-between gap-2">
              <p className="text-xs font-semibold text-ink">{r.objectTypeOrTitle}</p>
              <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-bold ${RISK_TONE[r.riskClassification] ?? RISK_TONE.LOW}`}>
                {r.riskClassification}
              </span>
            </div>
            <p className="mt-0.5 text-[11px] text-muted">Requested by {r.requestedBy}</p>
            <p className="mt-0.5 text-[11px] text-muted">Due {new Date(r.dueAt).toLocaleDateString()}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
