import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const live = vi.hoisted(() => ({ data: null as unknown, calls: 0 }));
const auth = vi.hoisted(() => ({ profile: null as unknown }));
vi.mock("@/components/overview/useLiveData", () => ({
  useLiveData: () => { live.calls += 1; return { data: live.data, error: "", loading: false, signedOut: false, reload: () => {} }; },
}));
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ profile: auth.profile, profileLoading: false }) }));
vi.mock("@/components/governance/LiveSourceStatus", () => ({ LiveSourceStatus: () => null }));

import SuperAdminPage from "@/app/super-admin/page";

const VIEW = {
  generatedAt: "2026-10-15T12:00:00Z",
  summary: {
    criticalIncidents: 1, openIncidents: 2, unassignedIncidents: 1, releaseHolds: 0, openReleases: 0,
    decisions: 2, decisionsByPriority: { Critical: 1, Medium: 1 }, isolation: "pass", availabilityPct: null,
    objectivePct: 99.5, privilegedRequests: 1, privilegedAwaitingApproval: 1, controlExceptions: 2,
  },
  decisions: [
    { id: "g1", ref: "BG-ABC123", priority: "Critical", title: "Emergency access request · 60 min", area: "Privileged access",
      owner: "Security approver", tenant: "Globex", since: "2026-10-15T11:00:00Z", state: "Awaiting independent approval" },
    { id: "d1", ref: "BIL-DEF456", priority: "Medium", title: "Usage charge under dispute · 2026-10", area: "Billing assurance",
      owner: "Billing assurance", tenant: "Acme", since: "2026-10-14T12:00:00Z", state: "Open dispute" },
  ],
  controls: [
    { key: "isolation", label: "Tenant isolation", state: "pass", detail: "Row-level security enforced on every tenant table" },
    { key: "resilience", label: "Operational resilience", state: "unknown", detail: "No health samples in the last 15 minutes" },
  ],
  health: { services: [], sampled: false, availabilityPct: null, objectivePct: 99.5, p95LatencyMs: null, degraded: 0, measured: 0, coreDown: [] },
  evaluation: { state: "unknown", latest: null, metrics: [], recent: { completed: 0, failed: 0 } },
  releases: { open: 0, held: 0, items: [] },
  tenants: { total: 2, withUsers: 2, active30d: 1, users: 3, withApprovedPlan: 0 },
  commercial: { month: "2026-10", invoiced: {}, collected: {}, receivable: { USD: 1200000 }, unpaidStatements: 1, openDisputes: 1, pendingCredits: 0 },
  privileged: { awaitingApproval: 1, active: 0, awaitingReview: 0, activeGrants: [] },
  audit: { events24h: 40, exportsPending: 0, deniedAttempts30d: 3 },
};

describe("Super Admin Command Center", () => {
  it("refuses anyone without the platform role, without calling the API", () => {
    auth.profile = { role: "Admin", platform_role: null };
    live.calls = 0;
    render(<SuperAdminPage />);
    expect(screen.getByText("Platform Super Admin access required")).toBeInTheDocument();
    expect(live.calls).toBe(0);
  });

  it("shows platform metadata, ranked decisions and honest unknowns", () => {
    auth.profile = { role: "Learner", platform_role: "super_admin" };
    live.data = VIEW;
    render(<SuperAdminPage />);
    expect(screen.getByText("Super Admin Command Center")).toBeInTheDocument();
    expect(screen.getByText(/Attention required · 2 control exceptions/)).toBeInTheDocument();
    expect(screen.getByText("Emergency access request · 60 min")).toBeInTheDocument();
    expect(screen.getByText("Globex")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getAllByText("Unknown").length).toBeGreaterThan(0);
    expect(screen.getByText("$12,000")).toBeInTheDocument();
  });
});
