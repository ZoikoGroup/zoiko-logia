"use client";

import { CheckCircle2, CircleAlert, CircleHelp, X } from "lucide-react";
import type { ActiveContext, AssuranceStatus, BoundaryType } from "@/types/commandCenter";

const BOUNDARY_LABEL: Record<BoundaryType, string> = {
  PERSONAL: "Personal",
  WORKSPACE: "Workspace",
  CLIENT: "Client",
  ENTITY: "Entity",
  MATTER: "Matter",
  RESTRICTED_MATTER: "Restricted matter",
};

const CONTROL_META: Record<"OK" | "DEGRADED" | "UNKNOWN", { label: string; icon: typeof CheckCircle2; tone: string }> = {
  OK: { label: "OK", icon: CheckCircle2, tone: "text-ok" },
  DEGRADED: { label: "Degraded", icon: CircleAlert, tone: "text-bad" },
  UNKNOWN: { label: "Unknown", icon: CircleHelp, tone: "text-muted" },
};

export function BoundaryExplanationPanel({
  context,
  assuranceStatus,
  onClose,
}: {
  context: ActiveContext;
  assuranceStatus: AssuranceStatus;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-end bg-black/40" role="dialog" aria-modal="true">
      <div className="h-full w-full max-w-md overflow-y-auto border-l border-line bg-panel p-5 shadow-xl">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs font-bold uppercase tracking-wide text-muted">Current boundary</p>
            <h2 className="mt-0.5 text-lg font-bold text-ink">{BOUNDARY_LABEL[context.boundaryType]}</h2>
          </div>
          <button onClick={onClose} aria-label="Close" className="text-muted hover:text-ink"><X size={17} /></button>
        </div>

        <div className="mt-4 space-y-3">
          <div className="rounded-xl border border-ok/30 bg-ok/5 p-3">
            <p className="text-xs font-bold text-ok">Kriton may use</p>
            <ul className="mt-1.5 space-y-1 text-xs text-ink">
              <li>Approved workspace policies</li>
              {context.entityName && <li>{context.entityName} entity data</li>}
              <li>Evidence attached to the active matter</li>
            </ul>
          </div>
          <div className="rounded-xl border border-bad/30 bg-bad/5 p-3">
            <p className="text-xs font-bold text-bad">Kriton may not use</p>
            <ul className="mt-1.5 space-y-1 text-xs text-ink">
              <li>Other client data</li>
              <li>Other entity evidence</li>
              <li>Personal context outside current permissions</li>
            </ul>
          </div>
        </div>

        <div className="mt-5">
          <p className="mb-2 text-xs font-bold uppercase tracking-wide text-muted">Assurance controls</p>
          <ul className="space-y-1.5">
            {assuranceStatus.controlStates.map((c) => {
              const meta = CONTROL_META[c.state];
              const Icon = meta.icon;
              return (
                <li key={c.control} className="flex items-center justify-between rounded-lg border border-line px-3 py-2 text-xs">
                  <span className="text-ink">{c.control}</span>
                  <span className={`flex items-center gap-1.5 font-semibold ${meta.tone}`}>
                    <Icon size={13} /> {meta.label}
                  </span>
                </li>
              );
            })}
          </ul>
          <p className="mt-3 text-[11px] text-muted">
            Policy {assuranceStatus.policyVersion} · Last evaluated {new Date(assuranceStatus.lastEvaluatedAt).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}
          </p>
        </div>
      </div>
    </div>
  );
}
