import Link from "next/link";
import { RefreshCw } from "lucide-react";
import type { Deadline } from "@/types/commandCenter";

const STATUS_TONE: Record<Deadline["status"], string> = {
  OVERDUE: "text-bad",
  APPROACHING: "text-warn",
  SCHEDULED: "text-ink",
  COMPLETED: "text-muted",
};

const STATUS_LABEL: Record<Deadline["status"], string> = {
  OVERDUE: "Overdue",
  APPROACHING: "Approaching",
  SCHEDULED: "Scheduled",
  COMPLETED: "Completed",
};

const MAX_VISIBLE = 3;

export function UpcomingDeadlines({ deadlines, partialFailureReason }: { deadlines: Deadline[]; partialFailureReason?: string }) {
  const visible = deadlines.slice(0, MAX_VISIBLE);

  return (
    <section className="rounded-2xl border border-line bg-panel shadow-[0_1px_2px_rgba(16,24,40,.04)]">
      <div className="flex items-center justify-between border-b border-line px-4 py-3.5">
        <h2 className="text-sm font-bold text-ink">Upcoming deadlines</h2>
        <Link href="/compliance-calendar" className="text-xs font-semibold text-brand hover:text-brand-2">View calendar</Link>
      </div>

      {partialFailureReason && (
        <div className="flex items-center gap-1.5 border-b border-line bg-warn/10 px-4 py-2 text-[11px] text-warn">
          <RefreshCw size={11} /> {partialFailureReason}
        </div>
      )}

      <ul className="divide-y divide-line">
        {visible.map((d) => (
          <li key={d.deadlineId} className="p-3.5">
            <p className="text-xs font-semibold text-ink">{d.title}</p>
            <p className="mt-0.5 text-[11px] text-muted">
              {d.jurisdiction && `${d.jurisdiction} · `}{d.type}
            </p>
            <p
              className={`mt-1 text-[11px] font-bold ${STATUS_TONE[d.status]}`}
              title={`Source: ${d.sourceOfDeadline} · ${d.verificationState.toLowerCase()} · ${d.authoritativeTimezone}`}
            >
              {STATUS_LABEL[d.status]} · {new Date(d.dueAt).toLocaleDateString()}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
