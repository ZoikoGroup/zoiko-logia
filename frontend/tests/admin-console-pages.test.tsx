import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Each page loads through useLiveData; feed real-shaped responses per key so
// the tests check what the pages render, and that no sample records appear.
const live = vi.hoisted(() => ({ byKey: {} as Record<string, unknown> }));
vi.mock("@/components/overview/useLiveData", () => ({
  useLiveData: (key: string) => ({ data: live.byKey[key] ?? null, error: "", loading: false, signedOut: false, reload: () => {} }),
}));
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ profile: { id: "me", role: "Admin" } }) }));
vi.mock("@/components/governance/LiveSourceStatus", () => ({ LiveSourceStatus: () => null }));
vi.mock("next/link", () => ({ default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a> }));

import RolesPermissionsPage from "@/app/roles-permissions/page";
import UsersTeamsPage from "@/app/users-teams/page";
import ServiceAccountsPage from "@/app/service-accounts/page";
import BreakGlassPage from "@/app/break-glass/page";
import EntitiesClientsPage from "@/app/entities-clients/page";
import ReleaseGatesPage from "@/app/release-gates/page";
import TenantSettingsPage from "@/app/tenant-settings/page";

const NOW = "2026-10-15T10:00:00Z";
const check = (label: string, status: "pass" | "open" | "fail", note = "") => ({ label, status, note });

describe("Administration console pages", () => {
  it("Roles & Permissions shows the enforced registry, real conflicts and failing policy tests", () => {
    live.byKey = { "roles-console": {
      roles: [
        { name: "Admin", purpose: "Tenant administrator", scope: "Tenant", permissions: ["review.resolve", "audit.correct"], people: 2,
          serviceAccounts: 0, privileged: true, stepUp: ["review.resolve"], boundary: "Everything", assignableToServiceAccounts: false,
          sodConflicts: [{ permissions: ["review.resolve", "audit.correct"], reason: "Resolves and corrects" }], reviewInterval: 30 },
        { name: "Learner", purpose: "Learns", scope: "Tenant", permissions: [], people: 1, serviceAccounts: 0, privileged: false,
          stepUp: [], boundary: "No governance permissions", assignableToServiceAccounts: true, sodConflicts: [], reviewInterval: 90 },
      ],
      permissions: [{ key: "review.resolve", label: "Resolve review cases", stepUp: true }, { key: "audit.correct", label: "Correct the audit ledger", stepUp: true }],
      sodRules: [{ permissions: ["review.resolve", "audit.correct"], reason: "Resolves and corrects", roles: ["Admin"] }],
      policyTests: [{ label: "MFA required for privileged actions", passed: false, detail: "Not required" }],
      unrecognisedRoles: [],
      summary: { roles: 2, privilegedRoles: 1, identities: 3, people: 3, serviceAccounts: 0, sodConflicts: 1, peopleWithConflicts: 2,
        reviewsDue: 2, reviewsCompleted: 0, activeBreakGlass: 0, testsPassed: 0, testsTotal: 1 },
      events: [], generatedAt: NOW,
    } };
    render(<RolesPermissionsPage />);
    expect(screen.getAllByText("Admin").length).toBeGreaterThan(0);
    expect(screen.getByText(/Access governance hold: 1 policy check failing/)).toBeInTheDocument();
    expect(screen.getAllByText("Conflict").length).toBeGreaterThan(0);
    expect(screen.queryByText(/Platform Super Admin|Accounting Preparer/)).not.toBeInTheDocument();
  });

  it("Users & Teams shows offboarding blockers instead of sample members", () => {
    live.byKey = { "users-overview": {
      members: [{
        id: "u1", name: "Sam Reed", email: "sam@acme.test", role: "SME Reviewer", privileged: true, teams: [], status: "offboarding",
        isActive: false, identity: "mfa", providers: ["email"], lastSignInAt: NOW, invitedAt: null, createdAt: NOW,
        reviewDueAt: NOW, reviewOverdue: false, lastReview: null, blockers: [{ kind: "credential", label: "Owns service account erp-sync" }],
        offboardingGates: [check("Interactive sessions revoked", "pass"), check("Delegated credentials revoked", "open")],
      }],
      teams: [], priorities: [{ kind: "offboarding", userId: "u1", title: "Offboarding · Sam Reed", detail: "1 item(s) still owned or held" }],
      controls: [check("Identity proofing & MFA", "pass")],
      summary: { activeMembers: 0, openInvitations: 0, staleInvitations: 0, activeTeams: 0, ownedTeams: 0, reviewsDue: 0,
        reviewsDueSoon: 0, offboardingCases: 1, inactive: 1 },
      authStatusAvailable: true, generatedAt: NOW,
    } };
    render(<UsersTeamsPage />);
    expect(screen.getByText("OFFBOARDING · COMPLETION BLOCKED")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Complete offboarding" })).toBeDisabled();
    expect(screen.queryByText(/Avery Morgan|northstar/)).not.toBeInTheDocument();
  });

  it("Service Accounts quarantines an account whose owner left", () => {
    live.byKey = { "service-accounts-overview": {
      accounts: [{
        id: "sa1", name: "erp-sync", description: "Ledger import", role: "System Auditor", permissions: ["source.read"], ownerId: "u1",
        owner: "Sam Reed", ownerActive: false, createdBy: "Ada", createdAt: NOW, isActive: true, state: "quarantined", risk: "critical",
        liveKeys: 1, expiringKeys: 0, nextExpiry: NOW, lastUsedAt: null, checks: [check("Named accountable owner", "fail", "Sam Reed is deactivated")],
        checksPassed: 0, sodConflicts: [], keys: [],
      }],
      summary: { accounts: 1, liveKeys: 1, renewals: 0, scopeExceptions: 0, ownershipReviews: 1, quarantined: 1, states: { quarantined: 1 } },
      generatedAt: NOW,
    } };
    render(<ServiceAccountsPage />);
    expect(screen.getByText("QUARANTINED MACHINE IDENTITY")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Issue API key|Rotate: issue new key/ })).toBeDisabled();
    expect(screen.queryByText(/kriton-retrieval-prod|source-ingest-nightly/)).not.toBeInTheDocument();
  });

  it("Break-glass blocks a pending grant until a different Admin approves", () => {
    live.byKey = { "break-glass": {
      permissions: ["source.read"], grants: [{
        id: "g1", user_id: "me", user_name: "Ada Admin", permissions: ["audit.correct"], reason: "Fix ledger entry", duration_minutes: 30,
        status: "requested", requested_at: NOW, approved_by: null, activated_at: null, expires_at: null, ended_at: null,
        reviewed_by: null, reviewed_at: null, review_notes: null, needs_review: false,
      }],
    } };
    render(<BreakGlassPage />);
    expect(screen.getByText("GRANT BLOCKED · INDEPENDENT APPROVAL PENDING")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve grant" })).toBeDisabled();
    expect(screen.queryByText(/Morgan Chen|INC-2026/)).not.toBeInTheDocument();
  });

  it("Entities/Clients lists real engagements and keeps the legal-entity hold", () => {
    live.byKey = { entities: {
      engagements: [{ id: "e1", name: "FY26 statutory audit", status: "active", rightsVersion: "1", createdAt: NOW, activeMembers: 1, revokedMembers: 0,
        members: [{ userId: "u1", name: "Rui Risk", role: "member", status: "active", grantedAt: NOW, revokedAt: null, operations: ["ask"] }] }],
      summary: { engagements: 1, active: 1, members: 1, revoked: 0, withoutMembers: 0 },
      legalEntityRegister: { available: false, reason: "Blocked pending Data Protection Impact Assessment and Legal/Compliance sign-off." },
      generatedAt: NOW,
    } };
    render(<EntitiesClientsPage />);
    expect(screen.getAllByText("FY26 statutory audit").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "+ Add legal entity" })).toBeDisabled();
    expect(screen.queryByText(/Meridian|Northstar Services/)).not.toBeInTheDocument();
  });

  it("Release Gates holds a release with a failed measured gate", () => {
    const gates = Array.from({ length: 10 }, (_, i) => ({ key: `g${i}`, number: i + 1, label: `Gate ${i + 1}`, description: "", derived: i === 6,
      status: i === 6 ? "fail" : i < 6 ? "pass" : "open", note: i === 6 ? "citation precision below threshold" : "" }));
    live.byKey = { "release-register": {
      releases: [{ id: "r1", ref: "REL-001", name: "Agent orchestrator", version: "2.6.0", component: "AI Orchestration", changeRef: "PR #46",
        description: "", risk: "high", ownerId: null, owner: null, status: "on_hold", stage: "Staging → Production", gates, passed: 6, failed: 1,
        pending: 3, rollout: [], createdBy: "Ada", createdById: "u2", createdAt: NOW, approvedBy: null, approvedAt: null,
        deployedAt: null, rolledBackAt: null, history: [] }],
      summary: { records: 1, onHold: 1, validating: 0, awaitingApproval: 0, approved: 0, deployed: 0, rolledBack: 0 },
      readiness: [{ gate: "Evaluation", state: "blocked", reason: "No evaluation run has been recorded." }],
      components: ["AI Orchestration"], generatedAt: NOW,
    } };
    render(<ReleaseGatesPage />);
    expect(screen.getByText("PRODUCTION PROMOTION RESTRICTED")).toBeInTheDocument();
    expect(screen.getByText("citation precision below threshold")).toBeInTheDocument();
    expect(screen.getByText("No evaluation run has been recorded.")).toBeInTheDocument();
    expect(screen.queryByText(/Kriton Agent Orchestrator|REL-026/)).not.toBeInTheDocument();
  });

  it("Tenant Settings shows authorities and lets a tenant only stage a stricter value", () => {
    live.byKey = { "tenant-settings": {
      tenant: { name: "Acme", id: "t1-uuid-0000", policyVersion: "v1", evaluatedAt: NOW, region: "AWS eu-west-2" },
      controls: [
        { id: "TS-003", key: "mfa_required_privileged", name: "MFA for privileged actions", domain: "Identity & SSO", authority: "tenant_scoped",
          state: "review_due", risk: "high", value: "Not required", deploymentValue: "Not required", tenantValue: null, rawEffective: false,
          kind: "bool", unit: "", description: "Applies to admin endpoints.", rule: "May only be made stricter", tightened: false,
          changedAt: null, changeAuthority: "Admin (maker-checker)", pendingRequest: null, history: [] },
        { id: "TS-001", key: null, name: "Tenant isolation baseline", domain: "Privacy & Residency", authority: "global_locked",
          state: "enforced", risk: "critical", value: "Row-level security", deploymentValue: "", tenantValue: null, rawEffective: null,
          kind: null, unit: "", description: "", rule: "Fixed in code", tightened: false, changedAt: null, changeAuthority: "Platform", pendingRequest: null, history: [] },
      ],
      requests: [], hierarchy: [{ level: 1, title: "Global safety and tenant isolation", detail: "" }],
      summary: { effectiveControls: 1, totalControls: 2, stagedRequests: 0, prohibitedOverrides: 0, reviewsDue: 0, tightened: 0, activeExceptions: 0 },
      activity: [], generatedAt: NOW,
    } };
    render(<TenantSettingsPage />);
    expect(screen.getAllByText("MFA for privileged actions").length).toBeGreaterThan(0);
    expect(screen.getByText("Request a stricter value")).toBeInTheDocument();
    expect(screen.getAllByText("Global locked").length).toBeGreaterThan(0);
    expect(screen.queryByText(/Cedar Advisory|T-DEMO-018/)).not.toBeInTheDocument();
  });
});
