// ZL-UX-OV-GOV-02 — Governance Dashboard data contracts.
// The frontend renders these values; it never derives/recomputes a
// governance conclusion (state, score, or routing) from raw counts.

export type ScopeClass = "WORKSPACE" | "ENTITY" | "JURISDICTION" | "PLATFORM_INTERNAL" | "EXTERNAL_ASSURANCE";
export type Environment = "PRODUCTION" | "PREPRODUCTION" | "SANDBOX";
export type FreshnessState = "CURRENT" | "DELAYED" | "STALE" | "UNKNOWN";
export type Severity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFORMATIONAL";

// Canonical state taxonomy — spec §7.1. Do not add states outside this set.
export type DomainState =
  | "EFFECTIVE"
  | "EFFECTIVE_WITH_OBSERVATIONS"
  | "ATTENTION_REQUIRED"
  | "CONTROL_FAILURE"
  | "ASSESSMENT_OVERDUE"
  | "NOT_ASSESSED";

export interface GovernanceScope {
  scopeClass: ScopeClass;
  tenantId?: string;
  workspaceId?: string;
  entityIds: string[];
  jurisdictionCodes: string[];
  environment: Environment;
  assessmentWindow: { start: string; end: string; includesUnresolvedMaterial: true };
  roleId: string;
  permissionSetVersion: string;
  policyMatrixVersion: string;
}

export interface GovernanceSummary {
  overallState: DomainState; // derived server-side from domain states — never numeric
  criticalExceptionCount: number;
  highExceptionCount: number;
  pendingDecisionCount: number;
  blockedGateCount: number;
  partialDataDomains: string[];
  lastEvaluatedAt: string;
  freshnessState: FreshnessState;
}

export interface DomainStateEntry {
  domainCode: string;
  domainLabel: string;
  state: DomainState;
  ownerRole: string;
  effectiveControlCount: number;
  requiredControlCount: number;
  exceptionCounts: { critical: number; high: number };
  freshness: FreshnessState;
  lastEvaluatedAt: string;
  nextObligation: { label: string; dueAt: string } | null;
  drilldownTarget: string; // route to dedicated system of record
}

export interface GovernanceException {
  exceptionId: string;
  severity: Extract<Severity, "CRITICAL" | "HIGH">;
  domain: string;
  title: string;
  affectedScope: string;
  impact: string;
  owner: string; // role/team, personal name only where policy allows
  openedAt: string;
  slaAt: string;
  evidenceState: "CURRENT" | "STALE" | "MISSING" | "CONFLICTING";
  sourceObjectVersion: string;
  allowedActions: string[]; // e.g. ["OPEN_EXCEPTION"] — never "RESOLVE" inline
}

export interface GovernanceDecision {
  decisionId: string;
  type: "POLICY" | "RELEASE" | "EXCEPTION_ACCEPTANCE" | "SOURCE_LICENSE" | "JURISDICTION_ROLLOUT" | "ATTESTATION";
  impact: "HIGH" | "MEDIUM" | "LOW";
  objectVersion: string;
  title: string;
  scope: string;
  requestor: string;
  dueAt: string;
  requiredRoles: string[];
  quorum: number;
  evidenceState: "CURRENT" | "STALE" | "MISSING" | "CONFLICTING";
  status: "PENDING";
  allowedActions: string[]; // e.g. ["REVIEW_DECISION"] — never "APPROVE" inline
}

export interface ReleaseReadinessEntry {
  candidateId: string;
  artifactType: "RELEASE_CANDIDATE" | "MODEL" | "PROMPT_SET" | "POLICY_MATRIX" | "SOURCE_BUNDLE" | "GATE";
  artifactVersion: string;
  gateCode?: string;
  state: "PASSED" | "PASSED_WITH_CONDITIONS" | "FAILED" | "BLOCKED" | "PENDING";
  evidenceRef: string;
  evaluatedAt: string;
  owner: string;
  dependencyRefs: string[];
  conditions?: { text: string; owner: string; expiresAt: string }[];
}

export interface AccountabilitySummary {
  mandatoryReviews: number;
  overdueReviews: number;
  boundaryEscalations: number;
  acceptedExceptions: number;
  reviewerCoverageState: DomainState;
  traceCompletenessState: DomainState;
}

export interface SourceGovernanceSummary {
  state: DomainState;
  licenseStates: { expiringWithin30d: number };
  blockedBundles: number;
  provenanceExceptions: number;
  freshnessExceptions: number;
  ontologyExceptions: number;
  syllabusMappingExceptions: number;
}

export interface AuditIncidentSummary {
  ledgerState: DomainState;
  replayState: DomainState;
  openIncidentCounts: { critical: number; high: number };
  escalationCounts: number;
  correctiveActionCounts: { overdue: number };
  lastVerifiedAt: string;
}

export interface JurisdictionProviderSummary {
  jurisdictionStates: { code: string; state: "ENABLED" | "LIMITED_PILOT" | "PENDING" | "BLOCKED" | "RETIRED" }[];
  rolloutBlocks: number;
  providerAssessmentStates: { critical: number; expired: number };
  integrationExceptions: number;
  nextObligations: { label: string; dueAt: string }[];
}

export interface MaterialChange {
  changeId: string;
  category: string;
  title: string;
  actorRole: string;
  effectiveAt: string;
  affectedScope: string;
  reassessmentTriggered: boolean;
  auditRef: string;
}

export interface GovernanceViewModel {
  scope: GovernanceScope;
  summary: GovernanceSummary;
  domainStates: DomainStateEntry[];
  exceptions: GovernanceException[];
  decisions: GovernanceDecision[];
  releaseReadiness: ReleaseReadinessEntry[];
  accountabilitySummary: AccountabilitySummary;
  sourceGovernanceSummary: SourceGovernanceSummary;
  auditIncidentSummary: AuditIncidentSummary;
  jurisdictionProviderSummary: JurisdictionProviderSummary;
  materialChanges: MaterialChange[];
  partialDataNotice?: { affectedModules: string[]; asOf: string };
}
