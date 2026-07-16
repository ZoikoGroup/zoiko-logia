"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowUpRight, X } from "lucide-react";
import type { DomainStateEntry, GovernanceException } from "@/types/governance";
import { StateBadge, DOMAIN_STATE_RANK } from "./shared/StateBadge";
import { FreshnessIndicator } from "./shared/FreshnessIndicator";
import { SeverityBadge } from "./shared/SeverityBadge";

const DEGRADED_STATES = new Set(["ATTENTION_REQUIRED", "CONTROL_FAILURE", "ASSESSMENT_OVERDUE"]);

export function GovernancePostureSummary({
  domainStates,
  exceptions,
}: {
  domainStates: DomainStateEntry[];
  exceptions: GovernanceException[];
}) {
  const [activeDomain, setActiveDomain] = useState<DomainStateEntry | null>(null);
  const sorted = [...domainStates].sort((a, b) => DOMAIN_STATE_RANK[a.state] - DOMAIN_STATE_RANK[b.state]);

  const highestException = (domainLabel: string) =>
    exceptions
      .filter((e) => e.domain === domainLabel)
      .sort((a, b) => (a.severity === "CRITICAL" ? -1 : 1) - (b.severity === "CRITICAL" ? -1 : 1))[0];

  return (
    <section className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
      {sorted.map((domain) => {
        const degraded = DEGRADED_STATES.has(domain.state);
        const topException = degraded ? highestException(domain.domainLabel) : undefined;
        return (
          <button
            key={domain.domainCode}
            onClick={() => setActiveDomain(domain)}
            className="rounded-2xl border border-line bg-panel p-4 text-left shadow-[0_1px_2px_rgba(16,24,40,.04)] hover:border-brand/40"
          >
            <div className="flex items-start justify-between gap-2">
              <p className="text-xs font-bold text-ink">{domain.domainLabel}</p>
            </div>
            <div className="mt-2"><StateBadge state={domain.state} size="sm" /></div>

            {!degraded ? (
              <p className="mt-2 text-[11px] text-muted">
                Controls {domain.effectiveControlCount}/{domain.requiredControlCount} · {domain.ownerRole}
              </p>
            ) : (
              <div className="mt-2 space-y-1">
                <p className="text-[11px] text-muted">
                  Controls {domain.effectiveControlCount}/{domain.requiredControlCount} · {domain.ownerRole}
                </p>
                {topException && (
                  <p className="flex items-center gap-1.5 text-[11px] text-ink">
                    <SeverityBadge severity={topException.severity} />
                    <span className="truncate">{topException.title}</span>
                  </p>
                )}
              </div>
            )}

            <div className="mt-2.5 border-t border-line pt-2">
              <FreshnessIndicator state={domain.freshness} at={domain.lastEvaluatedAt} />
            </div>
          </button>
        );
      })}

      {activeDomain && (
        <div className="fixed inset-0 z-50 flex items-center justify-end bg-black/40" role="dialog" aria-modal="true">
          <div className="h-full w-full max-w-md overflow-y-auto border-l border-line bg-panel p-5 shadow-xl">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-bold uppercase tracking-wide text-muted">{activeDomain.ownerRole}</p>
                <h2 className="mt-0.5 text-lg font-bold text-ink">{activeDomain.domainLabel}</h2>
              </div>
              <button onClick={() => setActiveDomain(null)} aria-label="Close" className="text-muted hover:text-ink">
                <X size={17} />
              </button>
            </div>

            <div className="mt-3"><StateBadge state={activeDomain.state} /></div>

            <dl className="mt-4 space-y-2.5 text-xs">
              <div className="flex justify-between border-b border-line pb-2">
                <dt className="text-muted">Controls effective / required</dt>
                <dd className="font-semibold text-ink">{activeDomain.effectiveControlCount} / {activeDomain.requiredControlCount}</dd>
              </div>
              <div className="flex justify-between border-b border-line pb-2">
                <dt className="text-muted">Material exceptions</dt>
                <dd className="font-semibold text-ink">{activeDomain.exceptionCounts.critical} critical · {activeDomain.exceptionCounts.high} high</dd>
              </div>
              <div className="flex justify-between border-b border-line pb-2">
                <dt className="text-muted">Evidence freshness</dt>
                <dd><FreshnessIndicator state={activeDomain.freshness} at={activeDomain.lastEvaluatedAt} /></dd>
              </div>
              <div className="flex justify-between border-b border-line pb-2">
                <dt className="text-muted">Next obligation</dt>
                <dd className="font-semibold text-ink">
                  {activeDomain.nextObligation
                    ? `${activeDomain.nextObligation.label} · due ${new Date(activeDomain.nextObligation.dueAt).toLocaleDateString()}`
                    : "None scheduled"}
                </dd>
              </div>
            </dl>

            {exceptions.filter((e) => e.domain === activeDomain.domainLabel).length > 0 && (
              <div className="mt-4">
                <p className="mb-1.5 text-xs font-bold text-ink">Open exceptions in this domain</p>
                <ul className="space-y-1.5">
                  {exceptions.filter((e) => e.domain === activeDomain.domainLabel).map((e) => (
                    <li key={e.exceptionId} className="flex items-center gap-2 rounded-lg border border-line px-2.5 py-1.5 text-xs">
                      <SeverityBadge severity={e.severity} />
                      <span className="min-w-0 flex-1 truncate text-ink">{e.title}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <Link
              href={activeDomain.drilldownTarget}
              className="mt-5 flex items-center justify-center gap-1.5 rounded-xl bg-brand px-4 py-2.5 text-xs font-bold text-white hover:bg-brand-2"
            >
              Open {activeDomain.domainLabel} <ArrowUpRight size={13} />
            </Link>
          </div>
        </div>
      )}
    </section>
  );
}
