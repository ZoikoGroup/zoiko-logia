"use client";

import { useEffect, useState } from "react";
import { ContextBoundaryBar } from "./ContextBoundaryBar";
import { BoundaryExplanationPanel } from "./BoundaryExplanationPanel";
import { PageHeader } from "./PageHeader";
import { NeedsYourAttention } from "./NeedsYourAttention";
import { ActiveMatters } from "./ActiveMatters";
import { RightRail } from "./RightRail";
import { ContinueYourWork } from "./ContinueYourWork";
import { useRole } from "@/components/shell/RoleProvider";
import { commandCenterMock } from "@/mocks/commandCenterMock";
import type { ActiveContext, CommandCenterViewModel } from "@/types/commandCenter";

// Roles authorized for accounting-workflow objects (matters, workpapers,
// evidence, reports) — mirrors ACCOUNTING_WORKFLOWS in lib/nav.ts so the
// Command Center never renders a module a user has no sidebar access to.
const ACCOUNTING_ROLES = new Set(["CFO", "Controller", "Tax Director", "Finance Manager", "Business Owner", "Audit Partner", "Admin"]);
const REVIEW_AUTHORITY_ROLES = new Set(["CFO", "Controller", "Audit Partner", "Admin"]);

function ModuleSkeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-2xl border border-line bg-soft ${className}`} />;
}

export function CommandCenter() {
  const { role } = useRole();
  const [loading, setLoading] = useState(true);
  const [model, setModel] = useState<CommandCenterViewModel>(commandCenterMock);
  const [showBoundaryPanel, setShowBoundaryPanel] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setLoading(false), 350);
    return () => clearTimeout(timer);
  }, []);

  const hasAccountingAccess = ACCOUNTING_ROLES.has(role);
  const hasReviewAuthority = REVIEW_AUTHORITY_ROLES.has(role);

  const entities = new Set(model.recentWork.map((r) => r.entityId).filter(Boolean));
  const entityBound = model.activeContext.boundaryType === "ENTITY" || model.activeContext.boundaryType === "MATTER";

  function handleContextChange(next: Partial<ActiveContext>) {
    // §11.1 steps 4-9: stop in-flight work, clear caches scoped to the prior
    // context, then re-resolve. Phase 1 has one shared mock payload, so the
    // "re-resolve" step is simulated by narrowing what's shown for the new
    // boundary rather than re-fetching per module.
    setModel((m) => ({
      ...m,
      activeContext: { ...m.activeContext, ...next },
    }));
  }

  const deadlinesFailureReason = model.partialFailures?.find((f) => f.module === "Upcoming Deadlines")?.reason;

  return (
    <main className="flex-1 overflow-y-auto p-4 sm:p-6">
      <div className="mx-auto max-w-[1480px] space-y-4">
        <ContextBoundaryBar
          context={model.activeContext}
          assuranceStatus={model.assuranceStatus}
          hasUnsavedWork={false}
          onOpenBoundaryPanel={() => setShowBoundaryPanel(true)}
          onContextChange={handleContextChange}
        />

        <PageHeader
          context={model.activeContext}
          summary={model.professionalSummary}
          preferredName="Lennox"
          activeMatters={hasAccountingAccess ? model.activeMatters : []}
          reviewCount={model.reviewQueue.length}
          hasReviewAuthority={hasReviewAuthority}
          canCreateMatter={hasAccountingAccess}
          canUploadEvidence={hasAccountingAccess}
          canAddEntity={role === "Admin"}
          canCreateWorkpaper={hasAccountingAccess}
          canCreateReport={hasAccountingAccess}
        />

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.66fr)_336px]">
          <div className="space-y-4">
            {loading ? (
              <ModuleSkeleton className="h-56" />
            ) : (
              <NeedsYourAttention items={model.attentionItems} entityBound={entityBound} />
            )}

            {hasAccountingAccess && (loading ? (
              <ModuleSkeleton className="h-72" />
            ) : (
              <ActiveMatters matters={model.activeMatters} canStartMatter={hasAccountingAccess} />
            ))}
          </div>

          {loading ? (
            <div className="space-y-4">
              <ModuleSkeleton className="h-48" />
              <ModuleSkeleton className="h-40" />
            </div>
          ) : (
            <RightRail
              deadlines={model.deadlines}
              deadlinesPartialFailureReason={deadlinesFailureReason}
              reviewQueue={hasReviewAuthority ? model.reviewQueue : []}
              evidenceExceptionSummary={hasAccountingAccess ? model.evidenceExceptionSummary : undefined}
            />
          )}
        </div>

        {loading ? (
          <ModuleSkeleton className="h-40" />
        ) : (
          <ContinueYourWork items={model.recentWork} spansMultipleEntities={entities.size > 1} />
        )}
      </div>

      {showBoundaryPanel && (
        <BoundaryExplanationPanel
          context={model.activeContext}
          assuranceStatus={model.assuranceStatus}
          onClose={() => setShowBoundaryPanel(false)}
        />
      )}
    </main>
  );
}
