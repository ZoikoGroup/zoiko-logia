import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { GovernanceDashboardViewModel } from "@/lib/governance-dashboard-types";

const api = vi.hoisted(() => {
  class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  }
  return { ApiError, get: vi.fn() };
});
vi.mock("@/lib/api", () => ({ ApiError: api.ApiError, getAuthToken: () => "token", getGovernanceDashboard: api.get }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => <a href={href} {...rest}>{children}</a>,
}));
import { GovernanceDashboard } from "@/components/governance-dashboard/GovernanceDashboard";

const model: GovernanceDashboardViewModel = {
  governanceScope: {
    tenantId: "t1", workspaceName: "Acme Ltd", environment: "PRODUCTION", roleId: "Admin",
    assessmentWindow: { start: "2026-09-13T00:00:00Z", end: "2026-10-13T00:00:00Z", label: "Last 30 days" },
  },
  governanceSummary: {
    overallState: "critical", criticalExceptionCount: 1, highExceptionCount: 1, pendingDecisionCount: 1,
    blockedGateCount: 2, notAssessedDomains: ["Jurisdiction pack readiness"], lastEvaluatedAt: "2026-10-13T09:00:00Z",
  },
  domainStates: [
    { key: "incidents", label: "Security incidents", state: "critical", headline: "1 open incident(s)",
      metrics: [{ label: "Critical", value: 1 }], drilldownTarget: "/incident-response", reason: null },
    { key: "jurisdiction_readiness", label: "Jurisdiction pack readiness", state: "not_assessed", headline: "Not assessed",
      metrics: [], drilldownTarget: "/jurisdiction-rollout", reason: "Jurisdiction packs and their launch gate are not built yet." },
  ],
  exceptions: [
    { id: "incident:inc-1", severity: "critical", domain: "Security incidents", title: "Prompt bypass attempt (open)",
      ownerRole: "Security lead", dueAt: null, openedAt: "2026-10-12T10:00:00Z", drilldownTarget: "/incident-response",
      resolvedBy: "Resolving the underlying record" },
  ],
  decisions: [
    { id: "source:v1", type: "Source approval", title: "Approve “FRS 102” v2", submittedAt: "2026-10-10T10:00:00Z",
      drilldownTarget: "/source-library", blockedReason: "You submitted this — a second approver is required" },
  ],
  releaseReadiness: [
    { gate: "Evaluation", state: "blocked", reason: "No evaluation run has been recorded." },
    { gate: "Jurisdiction pack", state: "not_assessed", reason: "Jurisdiction packs and their launch gate are not built yet." },
  ],
};

// Block body on purpose: vitest runs a function returned from beforeEach as a
// teardown hook, and mockReset() returns the mock itself.
beforeEach(() => {
  api.get.mockReset();
});

describe("Governance Dashboard", () => {
  it("renders the live assessment, not sample data", async () => {
    api.get.mockResolvedValue(model);
    render(<GovernanceDashboard />);
    expect(await screen.findByText("Prompt bypass attempt (open)")).toBeInTheDocument();
    expect(screen.getByText(/Owner: Security lead/)).toBeInTheDocument();
    expect(screen.getByText("Approve “FRS 102” v2")).toBeInTheDocument();
    expect(screen.getByText(/second approver is required/)).toBeInTheDocument();
    expect(screen.getAllByText(/launch gate are not built yet/).length).toBeGreaterThan(0);
    expect(screen.getByText("No evaluation run has been recorded.")).toBeInTheDocument();
    // The old hard-coded content must be gone.
    expect(screen.queryByText(/failed open for 12 minutes/)).not.toBeInTheDocument();
    expect(screen.queryByText(/ws_uk_advisory/)).not.toBeInTheDocument();
  });

  it("explains a role without access instead of showing anything", async () => {
    api.get.mockRejectedValue(new api.ApiError(403, "forbidden"));
    render(<GovernanceDashboard />);
    expect(await screen.findByRole("alert")).toHaveTextContent("isn't available for your role");
  });

  it("shows an empty-alerts state honestly", async () => {
    api.get.mockResolvedValue({ ...model, exceptions: [] });
    render(<GovernanceDashboard />);
    expect(await screen.findByText("No active alerts.")).toBeInTheDocument();
  });
});
