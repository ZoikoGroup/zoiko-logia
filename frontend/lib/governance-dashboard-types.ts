/** GET /governance-dashboard — built from the tenant's real governance
 * records (backend app/domains/governance_dashboard/assessment.py). Anything
 * the platform cannot measure yet comes back "not_assessed" with a reason. */

export type DomainState = "critical" | "attention" | "effective" | "not_assessed";
export type AlertSeverity = "critical" | "high" | "medium" | "low";
export type GateState = "passed" | "blocked" | "partial" | "not_assessed";

export type GovernanceDomain = {
  key: string;
  label: string;
  state: DomainState;
  headline: string;
  metrics: { label: string; value: string | number | null }[];
  drilldownTarget: string;
  reason: string | null;
};

export type GovernanceAlert = {
  id: string;
  severity: AlertSeverity;
  domain: string;
  title: string;
  ownerRole: string;
  dueAt: string | null;
  openedAt: string | null;
  drilldownTarget: string;
  resolvedBy: string;
};

export type GovernanceDecision = {
  id: string;
  type: string;
  title: string;
  submittedAt: string | null;
  drilldownTarget: string;
  blockedReason: string | null;
};

export type ReleaseGate = { gate: string; state: GateState; reason: string };

export type GovernanceDashboardViewModel = {
  governanceScope: {
    tenantId: string;
    workspaceName: string;
    environment: string;
    assessmentWindow: { start: string; end: string; label: string };
    roleId: string;
  };
  governanceSummary: {
    overallState: DomainState;
    criticalExceptionCount: number;
    highExceptionCount: number;
    pendingDecisionCount: number;
    blockedGateCount: number;
    notAssessedDomains: string[];
    lastEvaluatedAt: string;
  };
  domainStates: GovernanceDomain[];
  exceptions: GovernanceAlert[];
  decisions: GovernanceDecision[];
  releaseReadiness: ReleaseGate[];
};
