"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { RefreshCw, ShieldOff } from "lucide-react";
import { PageShell } from "@/components/governance/PageShell";
import { GovernanceScopeSelector } from "@/components/governance/GovernanceScopeSelector";
import { GovernancePageHeader } from "@/components/governance/GovernancePageHeader";
import { GovernancePostureSummary } from "@/components/governance/GovernancePostureSummary";
import { CriticalExceptions } from "@/components/governance/CriticalExceptions";
import { PendingDecisions } from "@/components/governance/PendingDecisions";
import { ControlDomainsMatrix } from "@/components/governance/ControlDomainsMatrix";
import { EvaluationReleaseReadiness } from "@/components/governance/EvaluationReleaseReadiness";
import { HumanAccountability } from "@/components/governance/HumanAccountability";
import { SourceKnowledgeGovernance } from "@/components/governance/SourceKnowledgeGovernance";
import { AuditIncidentReadiness } from "@/components/governance/AuditIncidentReadiness";
import { JurisdictionProviderSnapshot } from "@/components/governance/JurisdictionProviderSnapshot";
import { useRole } from "@/components/shell/RoleProvider";
import { governanceMock } from "@/mocks/governanceMock";
import type { GovernanceScope, GovernanceViewModel } from "@/types/governance";

const DECISION_AUTHORITY_ROLES = new Set(["AI Governance Lead", "Admin", "Audit Partner"]);
const NO_ACCESS_ROLES = new Set(["Learner"]);
const EXPORT_ALLOWED_ROLES = new Set(["AI Governance Lead", "Admin"]);

function ModuleSkeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-2xl border border-line bg-soft ${className}`} />;
}

export default function GovernanceDashboardPage() {
  const { role } = useRole();
  const [loading, setLoading] = useState(true);
  const [model, setModel] = useState<GovernanceViewModel>(governanceMock);

  useEffect(() => {
    // Phase 1 stands in for per-module Promise.allSettled fetches against
    // the future /overview/governance endpoint — one failing module must
    // never block the rest of the page (see §6). All modules here share
    // one mock payload, so there is one shared load, not independent ones.
    const timer = setTimeout(() => setLoading(false), 350);
    return () => clearTimeout(timer);
  }, []);

  if (NO_ACCESS_ROLES.has(role)) {
    return (
      <PageShell title="Governance Dashboard" subtitle="" showMetrics={false}>
        <div className="mx-auto flex max-w-lg flex-col items-center gap-3 py-24 text-center">
          <span className="grid h-12 w-12 place-items-center rounded-full bg-soft text-muted"><ShieldOff size={22} /></span>
          <p className="text-sm font-semibold text-ink">
            Your current role does not include Governance Dashboard access.
          </p>
          <Link href="/" className="text-xs font-semibold text-brand hover:text-brand-2">
            Return to Command Center
          </Link>
        </div>
      </PageShell>
    );
  }

  function handleScopeChange(next: Partial<GovernanceScope>) {
    setModel((m) => ({ ...m, scope: { ...m.scope, ...next } }));
  }

  const scopeLabel = `${model.scope.workspaceId} · ${model.scope.jurisdictionCodes.join(", ")}`;
  const hasDecisionAuthority = DECISION_AUTHORITY_ROLES.has(role);
  const canExport = EXPORT_ALLOWED_ROLES.has(role);
  const decisionsForRole = hasDecisionAuthority ? model.decisions : [];

  return (
    <PageShell title="Governance Dashboard" subtitle="" showMetrics={false}>
      <div className="mx-auto max-w-[1480px] space-y-4">
        <GovernanceScopeSelector
          scope={model.scope}
          freshnessState={model.summary.freshnessState}
          lastEvaluatedAt={model.summary.lastEvaluatedAt}
          onScopeChange={handleScopeChange}
        />

        {model.partialDataNotice && (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-warn/30 bg-warn/10 px-4 py-3 text-xs text-ink">
            <span>
              Partial governance view — {model.partialDataNotice.affectedModules.join(", ")} are delayed. Other modules
              were evaluated as of {new Date(model.partialDataNotice.asOf).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}.
            </span>
            <button className="flex items-center gap-1 font-semibold text-brand hover:text-brand-2">
              <RefreshCw size={12} /> Retry delayed modules
            </button>
          </div>
        )}

        <GovernancePageHeader
          summary={model.summary}
          scopeLabel={scopeLabel}
          environment={model.scope.environment}
          canExport={canExport}
          hasDecisionAuthority={hasDecisionAuthority}
        />

        {loading ? (
          <ModuleSkeleton className="h-24" />
        ) : (
          <GovernancePostureSummary domainStates={model.domainStates} exceptions={model.exceptions} />
        )}

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.66fr)_minmax(320px,.83fr)]">
          {loading ? <ModuleSkeleton className="h-80" /> : <CriticalExceptions exceptions={model.exceptions} />}
          {loading ? <ModuleSkeleton className="h-80" /> : <PendingDecisions decisions={decisionsForRole} />}
        </div>

        {loading ? <ModuleSkeleton className="h-64" /> : <ControlDomainsMatrix domainStates={model.domainStates} />}

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.66fr)_minmax(320px,.83fr)]">
          {loading ? <ModuleSkeleton className="h-72" /> : <EvaluationReleaseReadiness entries={model.releaseReadiness} />}
          {loading ? <ModuleSkeleton className="h-72" /> : <HumanAccountability summary={model.accountabilitySummary} />}
        </div>

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.66fr)_minmax(320px,.83fr)]">
          {loading ? <ModuleSkeleton className="h-56" /> : <SourceKnowledgeGovernance summary={model.sourceGovernanceSummary} />}
          {loading ? <ModuleSkeleton className="h-56" /> : <AuditIncidentReadiness summary={model.auditIncidentSummary} />}
        </div>

        {loading ? (
          <ModuleSkeleton className="h-48" />
        ) : (
          <JurisdictionProviderSnapshot summary={model.jurisdictionProviderSummary} materialChanges={model.materialChanges} />
        )}
      </div>
    </PageShell>
  );
}
