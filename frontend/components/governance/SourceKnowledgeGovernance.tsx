import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import type { SourceGovernanceSummary } from "@/types/governance";
import { StateBadge } from "./shared/StateBadge";

export function SourceKnowledgeGovernance({ summary }: { summary: SourceGovernanceSummary }) {
  return (
    <section className="rounded-2xl border border-line bg-panel p-5 shadow-[0_1px_2px_rgba(16,24,40,.04)]">
      <div className="flex items-center justify-between">
        <h2 className="font-bold text-ink">Source & knowledge governance</h2>
        <StateBadge state={summary.state} size="sm" />
      </div>
      <ul className="mt-3 space-y-1.5 text-xs text-muted">
        <li>{summary.licenseStates.expiringWithin30d} license{summary.licenseStates.expiringWithin30d === 1 ? "" : "s"} expire within 30 days</li>
        <li>{summary.freshnessExceptions} source bundle{summary.freshnessExceptions === 1 ? " has" : "s have"} delayed evidence</li>
        <li>{summary.blockedBundles} blocked production bundle{summary.blockedBundles === 1 ? "" : "s"}</li>
        {summary.provenanceExceptions > 0 && <li>{summary.provenanceExceptions} provenance exception{summary.provenanceExceptions === 1 ? "" : "s"}</li>}
        {summary.syllabusMappingExceptions > 0 && <li>{summary.syllabusMappingExceptions} syllabus-mapping exception{summary.syllabusMappingExceptions === 1 ? "" : "s"}</li>}
      </ul>
      <Link href="/source-licensing" className="mt-3 flex items-center gap-1 text-xs font-semibold text-brand hover:text-brand-2">
        Open source governance <ArrowUpRight size={13} />
      </Link>
    </section>
  );
}
