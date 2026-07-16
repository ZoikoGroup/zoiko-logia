import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import type { JurisdictionProviderSummary, MaterialChange } from "@/types/governance";

const JURISDICTION_TONE: Record<JurisdictionProviderSummary["jurisdictionStates"][number]["state"], string> = {
  ENABLED: "text-ok bg-ok/10 border-ok/30",
  LIMITED_PILOT: "text-warn bg-warn/10 border-warn/30",
  PENDING: "text-muted bg-soft border-line",
  BLOCKED: "text-bad bg-bad/10 border-bad/30",
  RETIRED: "text-muted bg-soft border-line",
};

const JURISDICTION_LABEL: Record<JurisdictionProviderSummary["jurisdictionStates"][number]["state"], string> = {
  ENABLED: "Enabled",
  LIMITED_PILOT: "Limited pilot",
  PENDING: "Pending",
  BLOCKED: "Blocked",
  RETIRED: "Retired",
};

export function JurisdictionProviderSnapshot({
  summary,
  materialChanges,
}: {
  summary: JurisdictionProviderSummary;
  materialChanges: MaterialChange[];
}) {
  return (
    <section className="grid gap-4 rounded-2xl border border-line bg-panel p-5 shadow-[0_1px_2px_rgba(16,24,40,.04)] lg:grid-cols-2">
      <div>
        <div className="flex items-center justify-between">
          <h2 className="font-bold text-ink">Jurisdiction & provider coverage</h2>
          <Link href="/jurisdiction-rollout" className="flex items-center gap-1 text-xs font-semibold text-brand hover:text-brand-2">
            Open <ArrowUpRight size={13} />
          </Link>
        </div>
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {summary.jurisdictionStates.map((j) => (
            <span key={j.code} className={`rounded-full border px-2.5 py-1 text-[11px] font-bold ${JURISDICTION_TONE[j.state]}`}>
              {j.code} · {JURISDICTION_LABEL[j.state]}
            </span>
          ))}
        </div>
        <ul className="mt-3 space-y-1.5 text-xs text-muted">
          <li>{summary.rolloutBlocks} rollout block{summary.rolloutBlocks === 1 ? "" : "s"}</li>
          <li>{summary.providerAssessmentStates.critical} critical / {summary.providerAssessmentStates.expired} expired provider assessment{summary.providerAssessmentStates.expired === 1 ? "" : "s"}</li>
          <li>{summary.integrationExceptions} integration exception{summary.integrationExceptions === 1 ? "" : "s"}</li>
          {summary.nextObligations.map((o) => (
            <li key={o.label}>Next: {o.label} — due {new Date(o.dueAt).toLocaleDateString()}</li>
          ))}
        </ul>
      </div>

      <div className="border-t border-line pt-4 lg:border-l lg:border-t-0 lg:pl-5 lg:pt-0">
        <h3 className="font-bold text-ink">Recent material changes</h3>
        <ul className="mt-2.5 space-y-2.5">
          {materialChanges.map((c) => (
            <li key={c.changeId} className="text-xs">
              <p className="font-semibold text-ink">{c.title}</p>
              <p className="mt-0.5 text-[11px] text-muted">
                {c.category} · {c.actorRole} · {new Date(c.effectiveAt).toLocaleDateString()}
                {c.reassessmentTriggered && <span className="ml-1.5 font-semibold text-warn">· reassessment triggered</span>}
              </p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
