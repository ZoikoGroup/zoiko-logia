"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowUpDown, ArrowUpRight } from "lucide-react";
import type { DomainStateEntry } from "@/types/governance";
import { StateBadge, DOMAIN_STATE_RANK } from "./shared/StateBadge";
import { FreshnessIndicator } from "./shared/FreshnessIndicator";

type SortKey = "state" | "exceptions" | "obligation";

function SortableHeader({ label, k, sortKey, onSort }: { label: string; k: SortKey; sortKey: SortKey; onSort: (k: SortKey) => void }) {
  const active = sortKey === k;
  return (
    <th scope="col" className="px-3 py-2.5 text-left text-[11px] font-bold uppercase tracking-wide text-muted">
      <button
        onClick={() => onSort(k)}
        className={`flex items-center gap-1 hover:text-ink ${active ? "text-ink" : ""}`}
        aria-sort={active ? "descending" : "none"}
      >
        {label} <ArrowUpDown size={11} />
      </button>
    </th>
  );
}

export function ControlDomainsMatrix({ domainStates }: { domainStates: DomainStateEntry[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("state");

  const rows = [...domainStates].sort((a, b) => {
    if (sortKey === "exceptions") {
      const aTotal = a.exceptionCounts.critical + a.exceptionCounts.high;
      const bTotal = b.exceptionCounts.critical + b.exceptionCounts.high;
      if (bTotal !== aTotal) return bTotal - aTotal;
    }
    if (sortKey === "obligation") {
      const aDue = a.nextObligation ? new Date(a.nextObligation.dueAt).getTime() : Infinity;
      const bDue = b.nextObligation ? new Date(b.nextObligation.dueAt).getTime() : Infinity;
      if (aDue !== bDue) return aDue - bDue;
    }
    // default + tiebreak: state severity, then exception count, then next obligation
    if (DOMAIN_STATE_RANK[a.state] !== DOMAIN_STATE_RANK[b.state]) return DOMAIN_STATE_RANK[a.state] - DOMAIN_STATE_RANK[b.state];
    const aTotal = a.exceptionCounts.critical + a.exceptionCounts.high;
    const bTotal = b.exceptionCounts.critical + b.exceptionCounts.high;
    if (bTotal !== aTotal) return bTotal - aTotal;
    const aDue = a.nextObligation ? new Date(a.nextObligation.dueAt).getTime() : Infinity;
    const bDue = b.nextObligation ? new Date(b.nextObligation.dueAt).getTime() : Infinity;
    return aDue - bDue;
  });

  return (
    <section className="rounded-2xl border border-line bg-panel shadow-[0_1px_2px_rgba(16,24,40,.04)]">
      <div className="border-b border-line px-5 py-4">
        <p className="text-[10px] font-bold uppercase tracking-[.16em] text-muted">Full posture</p>
        <h2 className="font-bold text-ink">Control domains matrix</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[900px] text-xs">
          <thead>
            <tr className="border-b border-line">
              <th scope="col" className="px-3 py-2.5 text-left text-[11px] font-bold uppercase tracking-wide text-muted">Domain</th>
              <SortableHeader label="State" k="state" sortKey={sortKey} onSort={setSortKey} />
              <th scope="col" className="px-3 py-2.5 text-left text-[11px] font-bold uppercase tracking-wide text-muted">Controls</th>
              <SortableHeader label="Exceptions" k="exceptions" sortKey={sortKey} onSort={setSortKey} />
              <th scope="col" className="px-3 py-2.5 text-left text-[11px] font-bold uppercase tracking-wide text-muted">Evidence freshness</th>
              <th scope="col" className="px-3 py-2.5 text-left text-[11px] font-bold uppercase tracking-wide text-muted">Last evaluated</th>
              <SortableHeader label="Next obligation" k="obligation" sortKey={sortKey} onSort={setSortKey} />
              <th scope="col" className="px-3 py-2.5 text-left text-[11px] font-bold uppercase tracking-wide text-muted">Open</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map((d) => (
              <tr key={d.domainCode}>
                <td className="px-3 py-3">
                  <p className="font-semibold text-ink">{d.domainLabel}</p>
                  <p className="text-[11px] text-muted">{d.ownerRole}</p>
                </td>
                <td className="px-3 py-3"><StateBadge state={d.state} size="sm" /></td>
                <td className="px-3 py-3">
                  <Link href={d.drilldownTarget} className="font-semibold text-brand hover:text-brand-2">
                    {d.effectiveControlCount}/{d.requiredControlCount}
                  </Link>
                </td>
                <td className="px-3 py-3 text-ink">
                  {d.exceptionCounts.critical > 0 && <span className="mr-1.5 font-bold text-bad">{d.exceptionCounts.critical} critical</span>}
                  {d.exceptionCounts.high > 0 && <span className="font-semibold text-warn">{d.exceptionCounts.high} high</span>}
                  {d.exceptionCounts.critical === 0 && d.exceptionCounts.high === 0 && <span className="text-muted">None</span>}
                </td>
                <td className="px-3 py-3"><FreshnessIndicator state={d.freshness} at={d.lastEvaluatedAt} /></td>
                <td className="px-3 py-3 text-muted">
                  {new Date(d.lastEvaluatedAt).toLocaleDateString()}
                </td>
                <td className="px-3 py-3 text-muted">
                  {d.nextObligation ? `${d.nextObligation.label} · ${new Date(d.nextObligation.dueAt).toLocaleDateString()}` : "None scheduled"}
                </td>
                <td className="px-3 py-3">
                  <Link href={d.drilldownTarget} className="inline-flex items-center gap-1 font-semibold text-brand hover:text-brand-2">
                    Open <ArrowUpRight size={12} />
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
