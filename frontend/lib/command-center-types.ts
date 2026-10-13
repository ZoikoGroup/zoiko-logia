/** GET /command-center — the signed-in user's own home view (backend
 * app/domains/command_center/home.py). Used by the Command Center (home page)
 * and My Workspace. Empty collections mean there is genuinely nothing yet. */

import type { DomainState, GovernanceAlert, GovernanceDecision } from "@/lib/governance-dashboard-types";

export type RecentWorkItem = { id: string; kind: string; title: string; at: string | null; href: string };
export type Deadline = { id: string; title: string; dueAt: string; overdue: boolean; href: string };
export type Matter = { id: string; name: string; status: string; myRole: string; createdAt: string | null };
export type MyBreakGlass = { id: string; status: string; permissions: string[]; expiresAt: string | null };

export type CommandCenterViewModel = {
  user: { firstName: string; fullName: string; email: string; role: string };
  workspace: { name: string; tenantId: string };
  generatedAt: string;
  counts: {
    questionsLast7Days: number;
    savedAnswers: number;
    drafts: number;
    attention: number;
    reviews: number;
    deadlines: number;
    activeMatters: number;
  };
  attentionItems: GovernanceAlert[];
  reviewQueue: GovernanceDecision[];
  deadlines: Deadline[];
  activeMatters: Matter[];
  recentWork: RecentWorkItem[];
  breakGlass: MyBreakGlass[];
  /** Null for Learners, who have no governance view. */
  assurance: { overallState: DomainState; blockedGates: number } | null;
};
