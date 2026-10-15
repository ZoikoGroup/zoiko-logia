import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
const live = vi.hoisted(() => ({ data: null as unknown, signedOut: false }));
vi.mock("@/components/overview/useLiveData", () => ({ useLiveData: () => ({ ...live, error: "", loading: false, reload: vi.fn() }) }));
vi.mock("@/components/layout/AppHeader", () => ({ BrandMark: () => <span>K</span> }));
import MyWorkspacePage from "@/app/my-workspace/page";
import { GovernanceDashboard } from "@/components/governance-dashboard/GovernanceDashboard";
import { CommandCenter } from "@/components/command-center/CommandCenter";

describe("Overview reference layouts", () => {
  it("filters pending work and resumes the actual saved research", () => {
    live.data = { workspaceName: "Actual Company", user: { displayName: "A" }, counts: { documents: 2, drafts: 1, savedAnswers: 1, generatedFiles: 0, reviewsResolved: 3 }, queues: { reviews: 4, escalations: 1 }, recentActivity: [{ id: "research", kind: "saved_answer", title: "My saved lease research", context: "IFRS", age: "2h ago", verb: "Saved", href: "/saved-answers?answer=research" }], pendingTasks: [{ id: "draft", title: "Finish budget", tone: "info", status: "Draft", age: "1h ago", href: "/drafts-reports" }, { id: "review", title: "Review lease", tone: "bad", status: "Overdue", age: "2h ago", href: "/review-tasks" }], generatedAt: "2026-10-15T10:00:00Z" };
    render(<MyWorkspacePage />);
    expect(screen.getByText("Actual Company")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Most recent saved research/ })).toHaveAttribute("href", "/saved-answers?answer=research");
    const table = document.querySelector("table")!;
    expect(table.textContent).toContain("Finish budget");
    fireEvent.click(screen.getByRole("button", { name: "Needs attention" }));
    expect(table.textContent).not.toContain("Finish budget");
    expect(table.textContent).toContain("Review lease");
    expect(screen.getByText(/Personal due dates are not supplied/)).toBeInTheDocument();
  });
  it("shows real governance exceptions and marks missing evidence", () => {
    live.data = { scope: { workspaceName: "Tenant A", jurisdictions: ["US"], windowDays: 30, policyVersion: "p1", evidenceFreshness: "degraded", auditLedger: { eventsInWindow: 8, lastEventAge: "1h ago" } }, summary: { pendingDecisionCount: 2, blockedGateCount: 1, criticalExceptionCount: 1, highExceptionCount: 0 }, staleDomains: ["Sources"], domains: [], decisions: [], exceptions: [{ id: "e1", title: "Actual failed gate", detail: "Grounding failed", domain: "Evaluation", severity: "Critical", href: "/evaluation-gates" }], panels: { sources: { state: "stale", lines: [] }, audit: { state: "current", lines: [] } }, generatedAt: "2026-10-15T10:00:00Z" };
    render(<GovernanceDashboard />);
    expect(screen.getByText("Actual failed gate")).toBeInTheDocument();
    expect(screen.getByText(/Evidence is stale or unavailable/)).toHaveTextContent("Sources");
    expect(screen.getByRole("link", { name: "Inspect" })).toHaveAttribute("href", "/evaluation-gates");
  });
  it("does not invent review or source totals for roles without access", () => {
    live.data = { workspaceName: "Tenant B", permissions: { review: false, source: false }, summary: { attentionCount: 0, overdueCount: 0, upcomingDeadlineCount: 0, deadlineHorizonDays: 14 }, reviewQueue: null, evidence: null, deadlines: [], recentWork: [], attentionItems: [], assurance: { overallState: "ok", controls: {}, policyVersion: "p1", lastAuditEventAge: "never" }, generatedAt: "2026-10-15T10:00:00Z" };
    render(<CommandCenter />);
    expect(screen.getAllByText("—")).toHaveLength(2);
    expect(screen.queryByRole("link", { name: "Review Exceptions" })).not.toBeInTheDocument();
    expect(screen.queryByText("Your review queue is empty.")).not.toBeInTheDocument();
    expect(screen.getByText("Source data is not available for your role.")).toBeInTheDocument();
  });
});
