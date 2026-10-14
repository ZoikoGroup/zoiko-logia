// Shapes returned by GET /command-center and GET /command-center/workspace
// (backend/app/domains/command_center/service.py). Every value is counted live
// from the tenant's records; nothing here is sample data.

export type OverviewPermissions = {
  review: boolean;
  reviewResolve: boolean;
  safety: boolean;
  safetyManage: boolean;
  support: boolean;
  source: boolean;
  sourceManage: boolean;
  evaluation: boolean;
};

export type AttentionItem = {
  id: string;
  level: "high" | "attention";
  title: string;
  context: string;
  due: string;
  action: string;
  href: string;
};

export type DeadlineItem = {
  id: string;
  title: string;
  context: string;
  date: string;
  dueAt?: string;
  state: "critical" | "approaching" | "scheduled";
  href: string;
};

export type ReviewQueueItem = {
  id: string;
  title: string;
  risk: string;
  reason: string;
  createdAt: string | null;
  age: string;
  href: string;
};

export type WorkItem = {
  id: string;
  kind: "saved_answer" | "draft" | "document" | "artifact" | "review";
  title: string;
  context: string;
  verb: string;
  href: string;
  at: string | null;
  age: string;
};

export type ActiveMatter = { id: string; name: string; status: string; createdAt: string | null; age: string };

export type CommandCenterViewModel = {
  contextToken: string;
  activeContext: {
    workspaceName: string;
    jurisdictionCode: string;
    frameworkCode: string;
    periodLabel: string;
    roleId: string;
  };
  user: { displayName: string; role: string };
  workspaceName: string;
  permissions: OverviewPermissions;
  summary: {
    attentionCount: number;
    reviewCount: number;
    upcomingDeadlineCount: number;
    overdueCount: number;
    deadlineHorizonDays: number;
  };
  attentionItems: AttentionItem[];
  activeMatters: ActiveMatter[];
  activeMatterCount: number;
  deadlines: DeadlineItem[];
  reviewQueue: { open: number; items: ReviewQueueItem[] } | null;
  evidence: { proposed: number; unreviewed: number; withdrawn: number; restrictedLicence: number; inUse: number } | null;
  recentWork: WorkItem[];
  assurance: {
    overallState: "ok" | "attention";
    controls: Record<string, "ok" | "attention" | "stale">;
    policyVersion: string;
    lastAuditEventAt: string | null;
    lastAuditEventAge: string;
  };
  generatedAt: string;
};

export type WorkspaceTask = {
  id: string;
  title: string;
  status: string;
  tone: "bad" | "warn" | "info";
  href: string;
  age: string;
};

export type MyWorkspaceViewModel = {
  user: { displayName: string; fullName: string; email: string; role: string };
  workspaceName: string;
  counts: { savedAnswers: number; drafts: number; documents: number; generatedFiles: number; reviewsResolved: number };
  queues: { reviews: number; escalations: number };
  recentActivity: WorkItem[];
  pendingTasks: WorkspaceTask[];
  generatedAt: string;
};
