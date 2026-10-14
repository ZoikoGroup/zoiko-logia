// Shape returned by GET /governance-dashboard
// (backend/app/domains/command_center/service.py → build_governance).

export type GovernanceFreshness = { state: "current" | "stale" | "unknown"; label: string; at?: string };

export type GovernanceDomain = {
  key: string;
  name: string;
  href: string;
  state: string;
  metric: string;
  exceptions: string;
  freshness: GovernanceFreshness;
  next: string;
};

export type GovernanceException = {
  id: string;
  severity: "Critical" | "High" | "Medium" | "Low" | string;
  domain: string;
  title: string;
  detail: string;
  href: string;
};

export type GovernanceDecision = {
  id: string;
  severity: string;
  kind: string;
  title: string;
  due: string;
  href: string;
};

export type GovernanceDashboardViewModel = {
  contextToken: string;
  scope: {
    workspaceName: string;
    environment: string;
    jurisdictions: string[];
    windowDays: number;
    windowStart: string;
    windowEnd: string;
    policyVersion: string;
    evidenceFreshness: "current" | "degraded";
    auditLedger: { lastEventAt: string | null; lastEventAge: string; eventsInWindow: number };
  };
  summary: {
    criticalExceptionCount: number;
    highExceptionCount: number;
    pendingDecisionCount: number;
    blockedGateCount: number;
  };
  staleDomains: string[];
  domains: GovernanceDomain[];
  exceptions: GovernanceException[];
  decisions: GovernanceDecision[];
  panels: { sources: { state: string; lines: string[] }; audit: { state: string; lines: string[] } };
  generatedAt: string;
};
