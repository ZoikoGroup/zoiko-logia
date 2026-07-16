"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowUpRight, ChevronDown, ChevronRight } from "lucide-react";
import type { ReleaseReadinessEntry } from "@/types/governance";

const CHAIN_ORDER: ReleaseReadinessEntry["artifactType"][] = [
  "RELEASE_CANDIDATE", "MODEL", "PROMPT_SET", "POLICY_MATRIX", "SOURCE_BUNDLE", "GATE",
];

const ARTIFACT_LABEL: Record<ReleaseReadinessEntry["artifactType"], string> = {
  RELEASE_CANDIDATE: "Release candidate",
  MODEL: "Model",
  PROMPT_SET: "Prompt set",
  POLICY_MATRIX: "Policy matrix",
  SOURCE_BUNDLE: "Source bundle",
  GATE: "Gate",
};

const GATE_LABEL: Record<string, string> = {
  FUNCTIONAL_EVALS: "Functional evals",
  GROUNDING_CITATION: "Grounding/citation gate",
  SAFETY_RISK: "Safety/risk gate",
  PROFESSIONAL_BOUNDARY: "Professional-boundary gate",
  SECURITY_PRIVACY: "Security/privacy gate",
};

const STATE_TONE: Record<ReleaseReadinessEntry["state"], string> = {
  PASSED: "text-ok bg-ok/10 border-ok/30",
  PASSED_WITH_CONDITIONS: "text-warn bg-warn/10 border-warn/30",
  FAILED: "text-bad bg-bad/10 border-bad/30",
  BLOCKED: "text-bad bg-bad/10 border-bad/30",
  PENDING: "text-muted bg-soft border-line",
};

const STATE_LABEL: Record<ReleaseReadinessEntry["state"], string> = {
  PASSED: "Passed",
  PASSED_WITH_CONDITIONS: "Passed with conditions",
  FAILED: "Failed",
  BLOCKED: "Blocked",
  PENDING: "Pending",
};

export function EvaluationReleaseReadiness({ entries }: { entries: ReleaseReadinessEntry[] }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const chainSummary = [...entries].sort((a, b) => CHAIN_ORDER.indexOf(a.artifactType) - CHAIN_ORDER.indexOf(b.artifactType));

  return (
    <section className="rounded-2xl border border-line bg-panel shadow-[0_1px_2px_rgba(16,24,40,.04)]">
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[.16em] text-muted">Read-only · deep-links to Release Gates</p>
          <h2 className="font-bold text-ink">Evaluation & release readiness</h2>
        </div>
        <Link href="/release-gates" className="flex shrink-0 items-center gap-1 text-xs font-semibold text-brand hover:text-brand-2">
          Open Release Gates <ArrowUpRight size={13} />
        </Link>
      </div>

      <div className="flex flex-wrap items-center gap-1 overflow-x-auto px-5 py-3 text-[11px] font-semibold text-muted">
        {CHAIN_ORDER.map((type, i) => (
          <span key={type} className="flex items-center gap-1 whitespace-nowrap">
            {ARTIFACT_LABEL[type]}
            {i < CHAIN_ORDER.length - 1 && <ChevronRight size={11} />}
          </span>
        ))}
      </div>

      <ul className="divide-y divide-line">
        {chainSummary.map((entry) => {
          const label = entry.gateCode ? GATE_LABEL[entry.gateCode] ?? entry.gateCode : ARTIFACT_LABEL[entry.artifactType];
          const isExpandable = !!entry.conditions?.length;
          const isOpen = expanded === entry.candidateId;
          return (
            <li key={entry.candidateId}>
              <div className="flex flex-wrap items-center justify-between gap-2 p-4">
                <div className="min-w-0">
                  <p className="text-xs font-semibold text-ink">{label}</p>
                  <p className="text-[11px] text-muted">v{entry.artifactVersion} · {entry.owner}</p>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${STATE_TONE[entry.state]}`}>
                    {STATE_LABEL[entry.state]}
                  </span>
                  <span className="text-[11px] text-muted">{entry.evidenceRef}</span>
                  {isExpandable && (
                    <button
                      onClick={() => setExpanded(isOpen ? null : entry.candidateId)}
                      className="text-muted hover:text-ink"
                      aria-label="Toggle conditions"
                    >
                      <ChevronDown size={14} className={isOpen ? "rotate-180 transition-transform" : "transition-transform"} />
                    </button>
                  )}
                </div>
              </div>
              {isExpandable && isOpen && (
                <div className="border-t border-line bg-soft px-4 py-3">
                  <p className="mb-1.5 text-[11px] font-bold uppercase tracking-wide text-muted">Conditions</p>
                  <ul className="space-y-1.5">
                    {entry.conditions!.map((c, i) => (
                      <li key={i} className="text-[11px] text-ink">
                        {c.text} — owner {c.owner}, expires {new Date(c.expiresAt).toLocaleDateString()}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
