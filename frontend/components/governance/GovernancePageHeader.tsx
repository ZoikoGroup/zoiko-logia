"use client";

import Link from "next/link";
import { useState } from "react";
import { AlertTriangle, Download, MessageSquare, MoreHorizontal, X } from "lucide-react";
import type { GovernanceSummary } from "@/types/governance";
import { relativeTime } from "./shared/FreshnessIndicator";

export function GovernancePageHeader({
  summary,
  scopeLabel,
  environment,
  canExport,
  hasDecisionAuthority,
}: {
  summary: GovernanceSummary;
  scopeLabel: string;
  environment: string;
  canExport: boolean;
  hasDecisionAuthority: boolean;
}) {
  const [showKritonDisclaimer, setShowKritonDisclaimer] = useState(false);
  const showExceptionsCta = summary.criticalExceptionCount + summary.highExceptionCount >= 1;
  const showDecisionsCta = hasDecisionAuthority && summary.pendingDecisionCount > 0;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-ink">Governance Dashboard</h1>
          <p className="mt-0.5 text-sm text-muted">
            Evidence-backed oversight of AI, source, professional, release and operational controls.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {showExceptionsCta && (
            <Link
              href="/escalation-queue"
              className="inline-flex h-10 items-center gap-1.5 rounded-xl bg-bad px-3.5 text-xs font-bold text-white hover:opacity-90"
            >
              <AlertTriangle size={14} />
              Open critical exceptions
            </Link>
          )}
          {showDecisionsCta && (
            <Link
              href="/escalation-queue"
              className="inline-flex h-10 items-center gap-1.5 rounded-xl border border-line bg-panel px-3.5 text-xs font-bold text-ink hover:bg-soft"
            >
              Review pending decisions
            </Link>
          )}

          <div className="relative">
            <details className="group">
              <summary className="flex h-10 w-10 cursor-pointer list-none items-center justify-center rounded-xl border border-line bg-panel text-muted hover:bg-soft">
                <MoreHorizontal size={16} />
              </summary>
              <div className="absolute right-0 top-11 z-20 w-56 rounded-xl border border-line bg-panel p-1.5 shadow-lg">
                {canExport && (
                  <button className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-xs font-semibold text-ink hover:bg-soft">
                    <Download size={13} /> Export governance brief
                  </button>
                )}
                <button
                  onClick={() => setShowKritonDisclaimer(true)}
                  className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-xs font-semibold text-muted hover:bg-soft"
                >
                  <MessageSquare size={13} /> Ask Kriton about governance
                </button>
              </div>
            </details>
          </div>
        </div>
      </div>

      <p className="text-sm font-semibold text-ink">
        {summary.criticalExceptionCount} critical exception{summary.criticalExceptionCount === 1 ? "" : "s"} ·{" "}
        {summary.pendingDecisionCount} decisions pending · {summary.blockedGateCount} release gates blocked
      </p>
      <p className="text-xs text-muted">
        Last evaluated {relativeTime(summary.lastEvaluatedAt)} · Scope: {scopeLabel} · {environment}
        {summary.partialDataDomains.length > 0 && (
          <span className="text-warn"> · Partial data: {summary.partialDataDomains.join(", ")} are delayed</span>
        )}
      </p>

      {showKritonDisclaimer && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true">
          <div className="w-full max-w-sm rounded-2xl border border-line bg-panel p-5 shadow-xl">
            <div className="flex items-start justify-between gap-3">
              <p className="text-sm font-bold text-ink">Ask Kriton about governance</p>
              <button onClick={() => setShowKritonDisclaimer(false)} aria-label="Close" className="text-muted hover:text-ink">
                <X size={15} />
              </button>
            </div>
            <p className="mt-2 text-xs leading-5 text-muted">
              Kriton can help you understand governance concepts and terminology. Its answers are not a governance
              approval, exception acceptance, or release decision — those must be completed in the authoritative
              system of record.
            </p>
            <div className="mt-3 flex justify-end gap-2">
              <button
                onClick={() => setShowKritonDisclaimer(false)}
                className="rounded-lg border border-line px-3 py-1.5 text-xs font-semibold text-muted hover:bg-soft"
              >
                Cancel
              </button>
              <Link
                href="/ask-kriton"
                className="rounded-lg bg-brand px-3 py-1.5 text-xs font-bold text-white hover:bg-brand-2"
              >
                Continue to Ask Kriton
              </Link>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
