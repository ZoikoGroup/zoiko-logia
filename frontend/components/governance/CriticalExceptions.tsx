import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import type { GovernanceException } from "@/types/governance";
import { SeverityBadge } from "./shared/SeverityBadge";

const SEVERITY_ORDER: Record<GovernanceException["severity"], number> = { CRITICAL: 0, HIGH: 1 };
const MAX_ROWS = 5;

function slaState(slaAt: string): { label: string; tone: string } {
  const hoursLeft = (new Date(slaAt).getTime() - Date.now()) / 3_600_000;
  if (hoursLeft < 0) return { label: "SLA breached", tone: "text-bad" };
  if (hoursLeft < 6) return { label: `${Math.max(1, Math.round(hoursLeft))}h to SLA`, tone: "text-warn" };
  return { label: `${Math.round(hoursLeft / 24)}d to SLA`, tone: "text-muted" };
}

function ageLabel(openedAt: string): string {
  const hours = Math.round((Date.now() - new Date(openedAt).getTime()) / 3_600_000);
  if (hours < 24) return `${hours}h open`;
  return `${Math.round(hours / 24)}d open`;
}

export function CriticalExceptions({ exceptions }: { exceptions: GovernanceException[] }) {
  const unresolved = [...exceptions].sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]);
  const rows = unresolved.slice(0, MAX_ROWS);

  return (
    <section className="rounded-2xl border border-line bg-panel shadow-[0_1px_2px_rgba(16,24,40,.04)]">
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[.16em] text-muted">Exception-first</p>
          <h2 className="font-bold text-ink">Critical exceptions</h2>
        </div>
        <Link href="/escalation-queue" className="flex shrink-0 items-center gap-1 text-xs font-semibold text-brand hover:text-brand-2">
          View all critical exceptions <ArrowUpRight size={13} />
        </Link>
      </div>

      {rows.length === 0 ? (
        <div className="p-6 text-center">
          <p className="text-sm font-semibold text-ink">
            No Critical or High governance exceptions are open in this scope.
          </p>
          <Link href="/ai-safety-dashboard" className="mt-2 inline-block text-xs font-semibold text-brand hover:text-brand-2">
            View all controls
          </Link>
        </div>
      ) : (
        <ul className="divide-y divide-line">
          {rows.map((exc) => {
            const sla = slaState(exc.slaAt);
            return (
              <li key={exc.exceptionId} className="p-4">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="flex items-start gap-2.5">
                    <SeverityBadge severity={exc.severity} />
                    <div className="min-w-0">
                      <p className="text-xs font-bold uppercase tracking-wide text-muted">{exc.domain}</p>
                      <p className="mt-0.5 text-sm font-semibold text-ink">{exc.title}</p>
                    </div>
                  </div>
                  <Link
                    href="/escalation-queue"
                    className="shrink-0 whitespace-nowrap text-xs font-semibold text-brand hover:text-brand-2"
                  >
                    Open exception →
                  </Link>
                </div>
                <p className="mt-2 text-xs text-muted">{exc.impact}</p>
                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted">
                  <span>Scope: {exc.affectedScope}</span>
                  <span>Owner: {exc.owner}</span>
                  <span>{ageLabel(exc.openedAt)}</span>
                  <span className={sla.tone}>{sla.label}</span>
                  <span>Evidence: {exc.evidenceState.toLowerCase()}</span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
