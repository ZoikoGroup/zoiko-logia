import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
const api = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api", () => ({ getAuthToken: () => "token", getGovernanceDashboard: api.get }));
vi.mock("next/link", () => ({ default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => <a href={href} {...rest}>{children}</a> }));
import { GovernanceDashboard } from "@/components/governance-dashboard/GovernanceDashboard";

const base = {
  governanceScope: { workspaceName: "Zoiko Finance", environment: "PRODUCTION", jurisdictionCodes: ["US"], assessmentWindow: { label: "Last 30 days" } },
  governanceSummary: { overallState: "no_open_exceptions", criticalExceptionCount: 0, highExceptionCount: 0, pendingDecisionCount: 0, blockedGateCount: 0, partialDataDomains: ["Jurisdiction & Provider Coverage"], lastEvaluatedAt: "2026-10-08T12:00:00Z" },
  domainStates: [
    { name: "AI Safety & Risk Controls", state: "no_open_exceptions", openExceptions: 0, href: "/ai-safety-dashboard" },
    { name: "Jurisdiction & Provider Coverage", state: "not_assessed", openExceptions: 0, href: "/jurisdiction-rollout" },
  ],
  exceptions: [], decisions: [], releaseReadiness: [],
  accountabilitySummary: { mandatoryReviews: 0, overdueReviews: 0, boundaryEscalations: 0 },
  sourceGovernanceSummary: { state: "no_open_exceptions", licenseStates: {}, expiringWithin30Days: 0, expired: 0 },
  auditIncidentSummary: { ledgerState: "verified", ledgerEventsChecked: 12, openIncidentCounts: { critical: 0, high: 0 }, escalationCounts: {} },
};

beforeEach(() => {
  api.get.mockReset();
});

describe("Governance Dashboard", () => {
  it("shows exceptions and decisions from the backend, not sample data", async () => {
    api.get.mockResolvedValue({
      ...base,
      governanceSummary: { ...base.governanceSummary, overallState: "attention_required", criticalExceptionCount: 1, pendingDecisionCount: 1 },
      domainStates: [{ name: "Audit & Incident Readiness", state: "attention_required", openExceptions: 1, href: "/incident-response" }],
      exceptions: [{ id: "inc-1", severity: "Critical", domain: "Audit & Incident Readiness", title: "Open incident: PII in an upload", detail: "PII_LEAK · OPEN", openedAt: null, href: "/incident-response" }],
      decisions: [{ id: "p1", kind: "PROMPT APPROVAL", severity: "MEDIUM", title: "Approve prompt tax_answer v2", createdAt: null, href: "/model-prompt-registry" }],
    });
    render(<GovernanceDashboard />);
    expect(await screen.findByText("Open incident: PII in an upload")).toBeInTheDocument();
    expect(screen.getByText("Approve prompt tax_answer v2")).toBeInTheDocument();
    expect(screen.getByText(/1 critical exception · 0 high exceptions · 1 decision pending/)).toBeInTheDocument();
    expect(screen.queryByText(/Post-composition validation gate failed open/)).not.toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith("token", { environment: "PRODUCTION", jurisdiction: "US", windowDays: 30 }, expect.anything());
  });

  it("never calls an area effective just because it has no exceptions", async () => {
    api.get.mockResolvedValue(base);
    render(<GovernanceDashboard />);
    expect((await screen.findAllByText("No open exceptions")).length).toBeGreaterThan(0);
    expect(screen.queryByText("Effective")).not.toBeInTheDocument();
    expect(screen.getAllByText("Not assessed").length).toBeGreaterThan(0);
    expect(screen.getByText(/Partial governance view: Jurisdiction & Provider Coverage/)).toBeInTheDocument();
  });

  it("shows the real audit ledger verification result", async () => {
    api.get.mockResolvedValue(base);
    const { unmount } = render(<GovernanceDashboard />);
    expect(await screen.findByText("Ledger chain verified")).toBeInTheDocument();
    expect(screen.getByText("12 audit events checked")).toBeInTheDocument();
    unmount();
    api.get.mockResolvedValue({ ...base, auditIncidentSummary: { ...base.auditIncidentSummary, ledgerState: "broken" } });
    render(<GovernanceDashboard />);
    expect(await screen.findByText("Ledger chain broken")).toBeInTheDocument();
  });

  it("explains a 403 for roles without access", async () => {
    api.get.mockRejectedValue(Object.assign(new Error("forbidden"), { status: 403 }));
    render(<GovernanceDashboard />);
    expect(await screen.findByText("The Governance Dashboard is not available for your role.")).toBeInTheDocument();
  });
});
