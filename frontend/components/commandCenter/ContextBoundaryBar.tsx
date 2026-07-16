"use client";

import { useState } from "react";
import { ChevronDown, ShieldAlert, ShieldCheck, ShieldQuestion, X } from "lucide-react";
import type { ActiveContext, AssuranceStatus, BoundaryType } from "@/types/commandCenter";

const BOUNDARY_LABEL: Record<BoundaryType, string> = {
  PERSONAL: "Personal",
  WORKSPACE: "Workspace",
  CLIENT: "Client",
  ENTITY: "Entity",
  MATTER: "Matter",
  RESTRICTED_MATTER: "Restricted matter",
};

const ENTITY_OPTIONS = [
  { id: "ent_zoiko_group_inc", name: "Zoiko Group Inc.", jurisdiction: "US", framework: "US_GAAP" },
  { id: "ent_zoiko_sema", name: "Zoiko Sema Ltd.", jurisdiction: "UK", framework: "IFRS" },
  { id: "ent_zoiko_electronics", name: "Zoiko Electronics Ltd.", jurisdiction: "UK", framework: "IFRS" },
];

function assuranceMeta(state: AssuranceStatus["overallState"]) {
  if (state === "ASSURANCE_ACTIVE") return { label: "Assurance active", icon: ShieldCheck, tone: "text-ok" };
  if (state === "ASSURANCE_EXCEPTION") return { label: "Assurance exception", icon: ShieldAlert, tone: "text-bad" };
  return { label: "Assurance verification unavailable", icon: ShieldQuestion, tone: "text-muted" };
}

export function ContextBoundaryBar({
  context,
  assuranceStatus,
  hasUnsavedWork,
  onOpenBoundaryPanel,
  onContextChange,
}: {
  context: ActiveContext;
  assuranceStatus: AssuranceStatus;
  hasUnsavedWork: boolean;
  onOpenBoundaryPanel: () => void;
  onContextChange: (next: Partial<ActiveContext>) => void;
}) {
  const [open, setOpen] = useState(false);
  const [pendingEntityId, setPendingEntityId] = useState(context.entityId ?? "");
  const [confirming, setConfirming] = useState(false);

  const assurance = assuranceMeta(assuranceStatus.overallState);
  const AssuranceIcon = assurance.icon;
  const pendingEntity = ENTITY_OPTIONS.find((e) => e.id === pendingEntityId);
  const targetIsDifferent = pendingEntityId !== context.entityId;

  function requestSwitch() {
    if (!targetIsDifferent) {
      setOpen(false);
      return;
    }
    // §11.1 steps 2-3: confirm only when there's unsaved work or the switch
    // narrows/expands the boundary in a way that carries meaningful risk.
    setConfirming(true);
  }

  function confirmSwitch() {
    if (pendingEntity) {
      onContextChange({
        entityId: pendingEntity.id,
        entityName: pendingEntity.name,
        jurisdictionCode: pendingEntity.jurisdiction,
        frameworkCode: pendingEntity.framework,
        boundaryType: "ENTITY",
      });
    }
    setConfirming(false);
    setOpen(false);
  }

  return (
    <div className="relative rounded-2xl border border-line bg-panel px-4 py-3 shadow-[0_1px_2px_rgba(16,24,40,.04)]">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <button onClick={() => setOpen((v) => !v)} className="flex min-w-0 items-center gap-2 text-left" aria-expanded={open}>
          <div className="min-w-0">
            <p className="flex flex-wrap items-center gap-1.5 text-sm font-bold text-ink">
              {context.workspaceName}
              {context.entityName && <span className="text-muted">· {context.entityName}</span>}
              <ChevronDown size={14} className="text-muted" />
            </p>
            <p className="mt-0.5 truncate text-xs text-muted">
              {context.jurisdictionCode ?? "All jurisdictions"} · {context.frameworkCode ?? "No framework set"} · {context.periodLabel ?? "No period set"}
              {context.matterId && ` · Matter: ${context.matterId}`}
            </p>
          </div>
        </button>

        <div className="flex items-center gap-3">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-ok/30 bg-ok/10 px-2.5 py-1 text-xs font-bold text-ok">
            🛡 {BOUNDARY_LABEL[context.boundaryType]} boundary enforced
          </span>
          <button
            onClick={onOpenBoundaryPanel}
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-bold hover:bg-soft ${assurance.tone} ${
              assuranceStatus.overallState === "ASSURANCE_ACTIVE" ? "border-ok/30 bg-ok/10" : assuranceStatus.overallState === "ASSURANCE_EXCEPTION" ? "border-bad/30 bg-bad/10" : "border-line bg-soft"
            }`}
          >
            <AssuranceIcon size={13} />
            {assurance.label}
          </button>
        </div>
      </div>

      {open && (
        <div className="absolute left-0 right-0 top-full z-20 mt-2 rounded-2xl border border-line bg-panel p-4 shadow-lg">
          <div className="flex items-center justify-between">
            <p className="text-xs font-bold uppercase tracking-wide text-muted">Change entity</p>
            <button onClick={() => setOpen(false)} aria-label="Close" className="text-muted hover:text-ink"><X size={15} /></button>
          </div>
          <div className="mt-3 space-y-1.5">
            {ENTITY_OPTIONS.map((e) => (
              <button
                key={e.id}
                onClick={() => setPendingEntityId(e.id)}
                className={`flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left text-xs ${
                  pendingEntityId === e.id ? "border-brand bg-brand/5 font-semibold text-ink" : "border-line text-muted hover:bg-soft"
                }`}
              >
                <span>{e.name}</span>
                <span className="text-[11px]">{e.jurisdiction} · {e.framework}</span>
              </button>
            ))}
          </div>

          {confirming ? (
            <div className="mt-3 rounded-xl border border-warn/30 bg-warn/10 p-3">
              <p className="text-xs font-bold text-ink">Confirm context switch</p>
              <p className="mt-1 text-xs text-muted">
                {context.entityName} → {pendingEntity?.name}. Boundary narrows to Entity — matters, deadlines, review
                assignments, and Kriton context from {context.entityName} will be cleared.
                {hasUnsavedWork && " You have unsaved work that will be left in its current state."}
              </p>
              <div className="mt-2.5 flex gap-2">
                <button onClick={confirmSwitch} className="rounded-lg bg-brand px-3 py-1.5 text-xs font-bold text-white hover:bg-brand-2">
                  Confirm switch
                </button>
                <button onClick={() => setConfirming(false)} className="rounded-lg border border-line px-3 py-1.5 text-xs font-semibold text-muted hover:bg-soft">
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <div className="mt-3 flex justify-end gap-2">
              <button onClick={() => setOpen(false)} className="rounded-lg border border-line px-3 py-1.5 text-xs font-semibold text-muted hover:bg-soft">
                Cancel
              </button>
              <button onClick={requestSwitch} className="rounded-lg bg-brand px-3 py-1.5 text-xs font-bold text-white hover:bg-brand-2">
                Apply
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
