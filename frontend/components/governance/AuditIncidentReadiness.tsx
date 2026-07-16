import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import type { AuditIncidentSummary } from "@/types/governance";
import { StateBadge } from "./shared/StateBadge";

export function AuditIncidentReadiness({ summary }: { summary: AuditIncidentSummary }) {
  return (
    <section className="rounded-2xl border border-line bg-panel p-5 shadow-[0_1px_2px_rgba(16,24,40,.04)]">
      <div className="flex items-center justify-between">
        <h2 className="font-bold text-ink">Audit / incident readiness</h2>
        <div className="flex flex-col items-end gap-1">
          <StateBadge state={summary.ledgerState} size="sm" />
          <StateBadge state={summary.replayState} size="sm" />
        </div>
      </div>
      <ul className="mt-3 space-y-1.5 text-xs text-muted">
        <li>{summary.openIncidentCounts.critical} critical / {summary.openIncidentCounts.high} high open incidents</li>
        <li>{summary.escalationCounts} escalation{summary.escalationCounts === 1 ? "" : "s"} in progress</li>
        <li>{summary.correctiveActionCounts.overdue} overdue corrective action{summary.correctiveActionCounts.overdue === 1 ? "" : "s"}</li>
      </ul>
      <Link href="/audit-replay" className="mt-3 flex items-center gap-1 text-xs font-semibold text-brand hover:text-brand-2">
        Open audit & incident readiness <ArrowUpRight size={13} />
      </Link>
    </section>
  );
}
