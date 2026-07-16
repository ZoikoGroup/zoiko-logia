"use client";

import { useState } from "react";
import { ChevronDown, Pin, X } from "lucide-react";
import type { GovernanceScope } from "@/types/governance";
import { FreshnessIndicator } from "./shared/FreshnessIndicator";

const SCOPE_CLASS_LABEL: Record<GovernanceScope["scopeClass"], string> = {
  WORKSPACE: "Workspace scope",
  ENTITY: "Entity scope",
  JURISDICTION: "Jurisdiction scope",
  PLATFORM_INTERNAL: "Platform-Internal scope",
  EXTERNAL_ASSURANCE: "External assurance scope",
};

const RECENT_SCOPES = ["ws_uk_advisory · UK, US", "ws_uk_advisory · UK only"];
const PINNED_SCOPES = ["ws_uk_advisory · UK, US"];

function windowLabel(scope: GovernanceScope) {
  const start = new Date(scope.assessmentWindow.start).toLocaleDateString();
  const end = new Date(scope.assessmentWindow.end).toLocaleDateString();
  return `${start} – ${end}`;
}

export function GovernanceScopeSelector({
  scope,
  freshnessState,
  lastEvaluatedAt,
  onScopeChange,
}: {
  scope: GovernanceScope;
  freshnessState: "CURRENT" | "DELAYED" | "STALE" | "UNKNOWN";
  lastEvaluatedAt: string;
  onScopeChange: (next: Partial<GovernanceScope>) => void;
}) {
  const [open, setOpen] = useState(false);
  const [pendingEnv, setPendingEnv] = useState<GovernanceScope["environment"]>(scope.environment);
  const [pendingPlatform, setPendingPlatform] = useState(scope.scopeClass === "PLATFORM_INTERNAL");
  const [confirming, setConfirming] = useState(false);

  const hasDiff = pendingEnv !== scope.environment || pendingPlatform !== (scope.scopeClass === "PLATFORM_INTERNAL");

  function requestApply() {
    if (!hasDiff) {
      setOpen(false);
      return;
    }
    setConfirming(true);
  }

  function confirmApply() {
    onScopeChange({
      environment: pendingEnv,
      scopeClass: pendingPlatform ? "PLATFORM_INTERNAL" : "WORKSPACE",
    });
    setConfirming(false);
    setOpen(false);
  }

  return (
    <div className="relative rounded-2xl border border-line bg-panel px-4 py-3 shadow-[0_1px_2px_rgba(16,24,40,.04)]">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full flex-wrap items-center justify-between gap-2 text-left"
        aria-expanded={open}
      >
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-1.5 text-sm font-bold text-ink">
            {scope.workspaceId} · {SCOPE_CLASS_LABEL[scope.scopeClass]}
            <ChevronDown size={14} className="text-muted" />
          </p>
          <p className="mt-0.5 truncate text-xs text-muted">
            {scope.environment} · Jurisdictions: {scope.jurisdictionCodes.join(", ")} · Entities: {scope.entityIds.length} ·{" "}
            {windowLabel(scope)}
          </p>
        </div>
        <FreshnessIndicator state={freshnessState} at={lastEvaluatedAt} />
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-full z-20 mt-2 rounded-2xl border border-line bg-panel p-4 shadow-lg">
          <div className="flex items-center justify-between">
            <p className="text-xs font-bold uppercase tracking-wide text-muted">Change scope</p>
            <button onClick={() => setOpen(false)} aria-label="Close" className="text-muted hover:text-ink">
              <X size={15} />
            </button>
          </div>

          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-[11px] font-semibold text-muted">Workspace / Platform</label>
              <div className="flex overflow-hidden rounded-lg border border-line text-xs">
                <button
                  onClick={() => setPendingPlatform(false)}
                  className={`flex-1 px-2 py-1.5 ${!pendingPlatform ? "bg-brand text-white" : "bg-panel text-muted"}`}
                >
                  Workspace
                </button>
                <button
                  onClick={() => setPendingPlatform(true)}
                  className={`flex-1 px-2 py-1.5 ${pendingPlatform ? "bg-brand text-white" : "bg-panel text-muted"}`}
                  title="Requires an internal-role flag"
                >
                  Platform-Internal
                </button>
              </div>
            </div>

            <div>
              <label className="mb-1 block text-[11px] font-semibold text-muted">Environment</label>
              <select
                value={pendingEnv}
                onChange={(e) => setPendingEnv(e.target.value as GovernanceScope["environment"])}
                className="w-full rounded-lg border border-line bg-panel px-2 py-1.5 text-xs text-ink"
              >
                <option value="PRODUCTION">Production</option>
                <option value="PREPRODUCTION">Preproduction</option>
                <option value="SANDBOX">Sandbox</option>
              </select>
            </div>

            <div>
              <label className="mb-1 block text-[11px] font-semibold text-muted">Jurisdictions</label>
              <p className="rounded-lg border border-line bg-soft px-2 py-1.5 text-xs text-muted">
                {scope.jurisdictionCodes.join(", ")} (read-only in Phase 1)
              </p>
            </div>

            <div>
              <label className="mb-1 block text-[11px] font-semibold text-muted">Entity / client</label>
              <p className="rounded-lg border border-line bg-soft px-2 py-1.5 text-xs text-muted">
                {scope.entityIds.length} constituent entit{scope.entityIds.length === 1 ? "y" : "ies"} (read-only in Phase 1)
              </p>
            </div>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div>
              <p className="mb-1 text-[11px] font-semibold text-muted">Recent scopes</p>
              <ul className="space-y-1">
                {RECENT_SCOPES.map((s) => (
                  <li key={s} className="truncate text-xs text-muted">{s}</li>
                ))}
              </ul>
            </div>
            <div>
              <p className="mb-1 flex items-center gap-1 text-[11px] font-semibold text-muted"><Pin size={11} /> Pinned scopes</p>
              <ul className="space-y-1">
                {PINNED_SCOPES.map((s) => (
                  <li key={s} className="truncate text-xs text-muted">{s}</li>
                ))}
              </ul>
            </div>
          </div>

          {confirming ? (
            <div className="mt-4 rounded-xl border border-warn/30 bg-warn/10 p-3">
              <p className="text-xs font-bold text-ink">Confirm scope change</p>
              <ul className="mt-1.5 space-y-0.5 text-xs text-muted">
                {pendingEnv !== scope.environment && <li>Environment: {scope.environment} → {pendingEnv}</li>}
                {pendingPlatform !== (scope.scopeClass === "PLATFORM_INTERNAL") && (
                  <li>Scope class: {SCOPE_CLASS_LABEL[scope.scopeClass]} → {pendingPlatform ? "Platform-Internal scope" : "Workspace scope"}</li>
                )}
              </ul>
              <div className="mt-2.5 flex gap-2">
                <button onClick={confirmApply} className="rounded-lg bg-brand px-3 py-1.5 text-xs font-bold text-white hover:bg-brand-2">
                  Confirm change
                </button>
                <button onClick={() => setConfirming(false)} className="rounded-lg border border-line px-3 py-1.5 text-xs font-semibold text-muted hover:bg-soft">
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <div className="mt-4 flex justify-end gap-2">
              <button onClick={() => setOpen(false)} className="rounded-lg border border-line px-3 py-1.5 text-xs font-semibold text-muted hover:bg-soft">
                Cancel
              </button>
              <button onClick={requestApply} className="rounded-lg bg-brand px-3 py-1.5 text-xs font-bold text-white hover:bg-brand-2">
                Apply
              </button>
            </div>
          )}
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 border-t border-line pt-2.5 text-[11px] text-muted">
        <span>Tenant isolation: <strong className="text-ok">boundary enforced</strong></span>
        <span>Evidence freshness: <strong className={freshnessState === "CURRENT" ? "text-ok" : "text-warn"}>{freshnessState === "CURRENT" ? "up to date" : "degraded"}</strong></span>
        <span>Audit ledger: <strong className="text-ok">writable, verified</strong></span>
        <span>Policy matrix: <strong className="text-ink">{scope.policyMatrixVersion}</strong></span>
      </div>
    </div>
  );
}
