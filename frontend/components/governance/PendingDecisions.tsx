import Link from "next/link";
import type { GovernanceDecision } from "@/types/governance";

const IMPACT_TONE: Record<GovernanceDecision["impact"], string> = {
  HIGH: "text-bad bg-bad/10 border-bad/30",
  MEDIUM: "text-warn bg-warn/10 border-warn/30",
  LOW: "text-muted bg-soft border-line",
};

const TYPE_LABEL: Record<GovernanceDecision["type"], string> = {
  POLICY: "Policy",
  RELEASE: "Release",
  EXCEPTION_ACCEPTANCE: "Exception acceptance",
  SOURCE_LICENSE: "Source license",
  JURISDICTION_ROLLOUT: "Jurisdiction rollout",
  ATTESTATION: "Attestation",
};

export function PendingDecisions({ decisions }: { decisions: GovernanceDecision[] }) {
  return (
    <section className="rounded-2xl border border-line bg-panel shadow-[0_1px_2px_rgba(16,24,40,.04)]">
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[.16em] text-muted">Assigned to you</p>
          <h2 className="font-bold text-ink">Pending decisions</h2>
        </div>
      </div>

      {decisions.length === 0 ? (
        <div className="p-6 text-center">
          <p className="text-sm font-semibold text-ink">
            No governance decisions or attestations currently require your action.
          </p>
        </div>
      ) : (
        <ul className="divide-y divide-line">
          {decisions.map((d) => (
            <li key={d.decisionId} className="p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-1.5">
                  <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${IMPACT_TONE[d.impact]}`}>
                    {d.impact}
                  </span>
                  <span className="text-[10px] font-semibold uppercase tracking-wide text-muted">{TYPE_LABEL[d.type]}</span>
                </div>
                <span className="shrink-0 text-[11px] text-muted">Due {new Date(d.dueAt).toLocaleDateString()}</span>
              </div>
              <p className="mt-1.5 text-sm font-semibold text-ink">{d.title}</p>
              <p className="mt-1 text-[11px] text-muted">Scope: {d.scope}</p>
              <p className="mt-0.5 text-[11px] text-muted">Requested by {d.requestor}</p>
              <p className="mt-0.5 text-[11px] text-muted">
                Requires {d.requiredRoles.join(", ")} · quorum {d.quorum}
              </p>
              <Link
                href="/escalation-queue"
                className="mt-2 inline-block text-xs font-semibold text-brand hover:text-brand-2"
              >
                Review decision →
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
