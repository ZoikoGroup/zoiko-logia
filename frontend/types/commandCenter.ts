// ZL-UX-OV-CMD-01 — Command Center data contracts.
// The frontend composes this view; it never derives permissions, severity,
// status, or priority ordering from raw joins on the client.

export type BoundaryType = "PERSONAL" | "WORKSPACE" | "CLIENT" | "ENTITY" | "MATTER" | "RESTRICTED_MATTER";
export type Severity = "CRITICAL" | "HIGH" | "ATTENTION" | "INFORMATIONAL";
export type FreshnessState = "CURRENT" | "DELAYED" | "STALE" | "UNKNOWN";

export type MatterStatus =
  | "DRAFT" | "IN_PROGRESS" | "WAITING_FOR_EVIDENCE" | "WAITING_FOR_CLIENT"
  | "WAITING_FOR_REVIEWER" | "HUMAN_REVIEW_REQUIRED" | "CHANGES_REQUESTED"
  | "APPROVED" | "BLOCKED" | "CLOSED_ARCHIVED";

export interface ActiveContext {
  tenantId: string;
  workspaceId: string;
  workspaceName: string;
  entityId?: string;
  entityName?: string;
  jurisdictionCode?: string;
  frameworkCode?: string;
  periodId?: string;
  periodLabel?: string;
  matterId?: string;
  boundaryType: BoundaryType;
  roleId: string;
  permissionSetVersion: string;
}

export interface ProfessionalSummary {
  attentionCount: number;
  reviewCount: number;
  deadlineCount: number;
  summaryGeneratedAt: string;
  dataFreshnessState: FreshnessState;
}

export interface AttentionItem {
  id: string;
  category: string; // e.g. "boundary_breach" | "overdue_review" | "material_matter" | "deadline" | "evidence" | "standards_change" | "followup" | "informational"
  severity: Severity;
  title: string;         // action-oriented, specific — never "issue detected"
  secondaryText: string; // entity/client + category context
  entityId?: string;
  matterId?: string;
  dueAt?: string;
  status: string;
  actionType: string;
  actionTarget: string;  // route
  requiredPermission: string;
  updatedAt: string;
}

export interface ActiveMatter {
  matterId: string;
  title: string;
  entityId: string;
  entityName: string;
  topic: string;
  workflowState: MatterStatus;
  nextAction: string;
  dueAt?: string;
  lastActivityAt: string;
  evidenceCount: number;
  unresolvedEvidenceCount: number;
  reviewState?: string;
  owner?: string;
  allowedActions: string[]; // server-authorized only — never inferred from status
}

export interface Deadline {
  deadlineId: string;
  title: string;
  entityId: string;
  jurisdiction?: string;
  type: string;
  dueAt: string;
  authoritativeTimezone: string;
  status: "OVERDUE" | "APPROACHING" | "SCHEDULED" | "COMPLETED";
  sourceOfDeadline: string;
  verificationState: string;
}

export interface ReviewQueueItem {
  reviewId: string;
  matterId: string;
  objectTypeOrTitle: string;
  requestedBy: string;
  requestedAt: string;
  dueAt: string;
  riskClassification: string;
  reviewState: string;
  allowedActions: string[];
}

export interface RecentWorkItem {
  objectId: string;
  objectType: "MATTER" | "WORKPAPER" | "EVIDENCE_PACK" | "REPORT" | "DRAFT" | "SAVED_ANSWER" | "REGULATORY_ANALYSIS";
  title: string;
  entityId?: string;
  fileType?: string;
  lastInteractionAt: string;
  allowedActions: string[];
}

// Backs the compact Evidence Exception Control (§9.3) — the spec names this
// component explicitly but the §13.2 excerpt handed down doesn't carry its
// shape, so this mirrors the same server-computed-summary pattern used
// elsewhere in the view model rather than deriving counts from activeMatters
// client-side.
export interface EvidenceExceptionSummary {
  missingCount: number;
  dueForReviewCount: number;
  conflictingAuthorityCount: number;
}

export interface AssuranceStatus {
  overallState: "ASSURANCE_ACTIVE" | "ASSURANCE_EXCEPTION" | "ASSURANCE_UNAVAILABLE";
  controlStates: { control: string; state: "OK" | "DEGRADED" | "UNKNOWN" }[];
  lastEvaluatedAt: string;
  policyVersion: string;
  exceptionIds: string[];
}

export interface CommandCenterViewModel {
  activeContext: ActiveContext;
  professionalSummary: ProfessionalSummary;
  attentionItems: AttentionItem[];   // max 4 rendered initially
  activeMatters: ActiveMatter[];
  deadlines: Deadline[];             // max 3 rendered initially
  reviewQueue: ReviewQueueItem[];    // renders only if user has review authority/assignment
  recentWork: RecentWorkItem[];      // max 5 rendered initially
  evidenceExceptionSummary?: EvidenceExceptionSummary; // present only when unresolved exceptions exist
  assuranceStatus: AssuranceStatus;
  contextToken: string; // binds payload to tenant/workspace/boundary/permission-set version
  partialFailures?: { module: string; reason: string }[];
}
