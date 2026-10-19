import type { ComponentType } from "react";
import {
  LayoutGrid, ShieldCheck, Briefcase, MessageSquare, Bookmark, FileText, GraduationCap,
  FolderKanban, ClipboardCheck, Paperclip, BarChart3, CalendarClock,
  Database, Layers, Network, Globe2,
  ShieldAlert, Scale, CheckSquare, Cpu,
  AlertTriangle, History, Siren, ScrollText, LifeBuoy,
  Bell, Building2, Plug, Activity,
  Lock, Users, Building, GitBranch, Settings, CreditCard, Bot,
} from "lucide-react";
import { RoleCode } from "./roles";
import { ADVISOR } from "./advisor";

export type NavL3Tab = { label: string; slug: string };
export type NavL2Item = {
  label: string;
  slug: string;
  allowedRoles: RoleCode[];
  icon: ComponentType<{ size?: number }>;
  tabs?: NavL3Tab[];
};
export type NavL1Section = { id: string; label: string; allowedRoles: RoleCode[]; items: NavL2Item[] };

// Real backend roles (what /auth/me profile.role returns once provisioned)
// are role-gated here exactly as backend app/domains/identity/permissions.py
// ROLE_PERMISSIONS gates the endpoints — so a section a real role can't reach
// on the API is also hidden from its nav, and vice versa. This must track that
// matrix; per-role one-to-many mapping:
//   Admin            → everything (provision default)
//   Governance Ops Lead → all permissions (full read/write)
//   Source Admin     → source.read/manage
//   Syllabus Admin   → no permission in ROLE_PERMISSIONS yet, so it gets only
//                      the base sections below — NOT Source & Knowledge
//                      Governance. See issue: nav must not outrun the matrix.
//   Jurisdiction Lead  → source.read (rollout readiness views)
//   Risk Admin       → model.manage (risk/eval/model registry)
//   System Auditor   → source.read + support.read (read-only)
const ALL_BACKEND: RoleCode[] = [
  "Admin",
  "Governance Ops Lead",
  "System Auditor",
  "Source Admin",
  "Syllabus Admin",
  "Jurisdiction Lead",
  "Risk Admin",
  // Review queue only (backend: review.read + review.resolve). Listed here so
  // the base sections render for it; section gating below opens Accounting
  // Workflows to it, where item gating leaves just Review Tasks.
  "SME Reviewer",
];

const ALL: RoleCode[] = [
  "CFO",
  "Controller",
  "Audit Partner",
  "Tax Director",
  "Finance Manager",
  "Business Owner",
  "Learner",
  "AI Governance Lead",
  ...ALL_BACKEND,
];

const ALL_EXCEPT_LEARNER: RoleCode[] = ALL.filter((r) => r !== "Learner");

const FINANCE_ROLES: RoleCode[] = ["CFO", "Controller", "Tax Director", "Finance Manager", "Business Owner"];
const ACCOUNTING_WORKFLOWS: RoleCode[] = [...FINANCE_ROLES, "Audit Partner", "Admin"];
const SOURCE_KNOWLEDGE_GOVERNANCE: RoleCode[] = [
  "Audit Partner", "AI Governance Lead", "Admin",
  "Source Admin", "Governance Ops Lead", "Jurisdiction Lead", "System Auditor",
];
const AI_GOVERNANCE: RoleCode[] = ["AI Governance Lead", "Admin", "Risk Admin", "Governance Ops Lead"];
const REVIEW_ESCALATION_AUDIT: RoleCode[] = [
  "Audit Partner", "AI Governance Lead", "Admin",
  "Governance Ops Lead", "System Auditor",
];
const OPERATIONS: RoleCode[] = ["AI Governance Lead", "Admin"];
const ADMINISTRATION: RoleCode[] = ["Admin"];

export const NAV_SECTIONS: NavL1Section[] = [
  {
    id: "overview",
    label: "Overview",
    allowedRoles: ALL,
    items: [
      { label: "Command Center", slug: "", allowedRoles: ALL, icon: LayoutGrid },
      { label: "Governance Dashboard", slug: "overview/governance", allowedRoles: ALL_EXCEPT_LEARNER, icon: ShieldCheck },
      { label: "My Workspace", slug: "my-workspace", allowedRoles: ALL, icon: Briefcase },
    ],
  },
  {
    id: "kriton-workspace",
    label: "Kriton Workspace",
    allowedRoles: ALL,
    items: [
      { label: ADVISOR.navLabel, slug: "ask-kriton", allowedRoles: ALL, icon: MessageSquare },
      { label: "Saved Answers", slug: "saved-answers", allowedRoles: ALL_EXCEPT_LEARNER, icon: Bookmark },
      { label: "Drafts & Reports", slug: "drafts-reports", allowedRoles: ALL_EXCEPT_LEARNER, icon: FileText },
      { label: "Learning & Practice", slug: "learning-practice", allowedRoles: ALL, icon: GraduationCap },
    ],
  },
  {
    id: "accounting-workflows",
    label: "Accounting Workflows",
    // Sections filter before items, so a role that can open any item here
    // must be on the section too — otherwise Review Tasks never renders for
    // the SME Reviewer.
    allowedRoles: [...ACCOUNTING_WORKFLOWS, "SME Reviewer"],
    items: [
      { label: "Workpapers", slug: "workpapers", allowedRoles: ACCOUNTING_WORKFLOWS, icon: FolderKanban },
      { label: "Review Tasks", slug: "review-tasks", allowedRoles: [...ACCOUNTING_WORKFLOWS, "SME Reviewer"], icon: ClipboardCheck },
      { label: "Evidence Packs", slug: "evidence-packs", allowedRoles: ACCOUNTING_WORKFLOWS, icon: Paperclip },
      { label: "Reports & Insights", slug: "reports-insights", allowedRoles: ACCOUNTING_WORKFLOWS, icon: BarChart3 },
      { label: "Compliance Calendar", slug: "compliance-calendar", allowedRoles: ACCOUNTING_WORKFLOWS, icon: CalendarClock },
    ],
  },
  {
    id: "source-knowledge-governance",
    label: "Source & Knowledge Governance",
    allowedRoles: SOURCE_KNOWLEDGE_GOVERNANCE,
    items: [
      {
        label: "Source Library",
        slug: "source-library",
        allowedRoles: SOURCE_KNOWLEDGE_GOVERNANCE,
        icon: Database,
        tabs: [
          { label: "Standards", slug: "standards" },
          { label: "Tax", slug: "tax" },
          { label: "Audit", slug: "audit" },
          { label: "Payroll/Compliance", slug: "payroll-compliance" },
          { label: "Internal Policies", slug: "internal-policies" },
          { label: "Education Content", slug: "education-content" },
          { label: "Licensing & Approval", slug: "licensing" },
        ],
      },
      { label: "Source Bundles", slug: "source-bundles", allowedRoles: SOURCE_KNOWLEDGE_GOVERNANCE, icon: Layers },
      {
        label: "Accounting Ontology",
        slug: "accounting-ontology",
        allowedRoles: SOURCE_KNOWLEDGE_GOVERNANCE,
        icon: Network,
        tabs: [
          { label: "Topic map", slug: "topics" },
          { label: "Syllabus coverage", slug: "syllabus" },
        ],
      },
      { label: "Jurisdiction Rollout", slug: "jurisdiction-rollout", allowedRoles: SOURCE_KNOWLEDGE_GOVERNANCE, icon: Globe2 },
    ],
  },
  {
    id: "ai-governance",
    label: "AI Governance",
    allowedRoles: AI_GOVERNANCE,
    items: [
      { label: "AI Safety Dashboard", slug: "ai-safety-dashboard", allowedRoles: AI_GOVERNANCE, icon: ShieldAlert },
      {
        label: "Risk Policy",
        slug: "risk-policy",
        allowedRoles: AI_GOVERNANCE,
        icon: Scale,
        tabs: [
          { label: "Classification", slug: "classification" },
          { label: "Professional boundaries", slug: "boundaries" },
        ],
      },
      { label: "Evaluation Gates", slug: "evaluation-gates", allowedRoles: AI_GOVERNANCE, icon: CheckSquare },
      {
        label: "Model & Prompt Registry",
        slug: "model-prompt-registry",
        allowedRoles: AI_GOVERNANCE,
        icon: Cpu,
        tabs: [
          { label: "Models", slug: "models" },
          { label: "Prompts", slug: "prompts" },
          { label: "System Instructions", slug: "system-instructions" },
          { label: "Evaluation Status", slug: "evaluation-status" },
          { label: "Change History", slug: "change-history" },
        ],
      },
    ],
  },
  {
    id: "review-escalation-audit",
    label: "Review, Escalation & Audit",
    allowedRoles: REVIEW_ESCALATION_AUDIT,
    items: [
      { label: "Escalation Queue", slug: "escalation-queue", allowedRoles: REVIEW_ESCALATION_AUDIT, icon: AlertTriangle },
      { label: "Audit Replay", slug: "audit-replay", allowedRoles: REVIEW_ESCALATION_AUDIT, icon: History },
      { label: "Incident Response", slug: "incident-response", allowedRoles: REVIEW_ESCALATION_AUDIT, icon: Siren },
      { label: "Support Tickets", slug: "support-tickets", allowedRoles: REVIEW_ESCALATION_AUDIT, icon: LifeBuoy },
      { label: "Audit Logs", slug: "audit-logs", allowedRoles: REVIEW_ESCALATION_AUDIT, icon: ScrollText },
    ],
  },
  {
    id: "operations",
    label: "Operations",
    allowedRoles: OPERATIONS,
    items: [
      { label: "Alerts Center", slug: "alerts-center", allowedRoles: OPERATIONS, icon: Bell },
      { label: "Provider Register", slug: "provider-register", allowedRoles: OPERATIONS, icon: Building2 },
      { label: "Integrations", slug: "integrations", allowedRoles: OPERATIONS, icon: Plug },
      { label: "Status & Health", slug: "status-health", allowedRoles: OPERATIONS, icon: Activity },
    ],
  },
  {
    id: "administration",
    label: "Administration",
    // Every real role can request break-glass access, so the section admits
    // them all; item gating keeps everything else Admin-only.
    allowedRoles: ALL_BACKEND,
    items: [
      { label: "Roles & Permissions", slug: "roles-permissions", allowedRoles: ADMINISTRATION, icon: Lock },
      { label: "Users & Teams", slug: "users-teams", allowedRoles: ADMINISTRATION, icon: Users },
      { label: "Service Accounts", slug: "service-accounts", allowedRoles: ADMINISTRATION, icon: Bot },
      { label: "Break-glass Access", slug: "break-glass", allowedRoles: ALL_BACKEND, icon: Siren },
      { label: "Entities/Clients", slug: "entities-clients", allowedRoles: ADMINISTRATION, icon: Building },
      { label: "Release Gates", slug: "release-gates", allowedRoles: ADMINISTRATION, icon: GitBranch },
      { label: "Tenant Settings", slug: "tenant-settings", allowedRoles: ADMINISTRATION, icon: Settings },
      { label: "Billing & Usage", slug: "billing-usage", allowedRoles: ADMINISTRATION, icon: CreditCard },
    ],
  },
];

export function isVisible(allowedRoles: RoleCode[], role: RoleCode): boolean {
  return allowedRoles.includes(role);
}

/** Whether a role may open this path. The nav item with the longest matching
 * href decides (so "/source-library/tax" follows Source Library); a path no
 * nav item covers (account, settings, notifications…) is open to everyone
 * signed in. Hiding a nav entry alone left the page one typed URL away. */
export function canAccessPath(pathname: string, role: RoleCode): boolean {
  let match: { section: NavL1Section; item: NavL2Item; length: number } | null = null;
  for (const section of NAV_SECTIONS) {
    for (const item of section.items) {
      const href = navHref(item.slug);
      if (href === "/") continue; // "/" is every role's Command Center (RoleHome redirects Learners)
      if ((pathname === href || pathname.startsWith(`${href}/`)) && (!match || href.length > match.length)) {
        match = { section, item, length: href.length };
      }
    }
  }
  if (!match) return true;
  return isVisible(match.section.allowedRoles, role) && isVisible(match.item.allowedRoles, role);
}

export function navHref(slug: string): string {
  return slug ? `/${slug}` : "/";
}
