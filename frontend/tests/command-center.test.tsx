import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
const api = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api", () => ({ getAuthToken: () => "token", getCommandCenter: api.get }));
vi.mock("@/components/shell/RoleProvider", () => ({ useRole: () => ({ role: "Admin", roleReady: true, setRole: () => {} }) }));
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ user: null, profile: { full_name: "Naresh Maruthi" } }) }));
vi.mock("next/link", () => ({ default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => <a href={href} {...rest}>{children}</a> }));
import { CommandCenter } from "@/components/command-center/CommandCenter";

const base = {
  contextToken: "t", activeContext: { workspaceName: "Zoiko Finance", jurisdictionCode: "US", frameworkCode: "US-GAAP", periodLabel: "FY2026" },
  professionalSummary: { attentionCount: 0, reviewCount: 0, deadlineCount: 0 },
  attentionItems: [], activeMatters: [], deadlines: [], reviewQueue: [], recentWork: [],
  assuranceStatus: { overallState: "unknown", controls: { boundary_enforcement: "ok", citation_validation: "unavailable" }, policyVersion: "not-assessed" },
  moduleFreshness: { attentionItems: { state: "current" }, activeMatters: { state: "current" }, deadlines: { state: "current" }, reviewQueue: { state: "current" }, recentWork: { state: "current" } },
};

beforeEach(() => {
  api.get.mockReset();
});

describe("Command Center", () => {
  it("shows the records the backend returned, not sample data", async () => {
    api.get.mockResolvedValue({
      ...base,
      professionalSummary: { attentionCount: 1, reviewCount: 1, deadlineCount: 0 },
      attentionItems: [{ id: "e1", kind: "escalation", level: "high", title: "Escalation: Lease classification", context: "Is this lease on balance sheet?", dueAt: null, action: "Open escalation", href: "/escalation-queue" }],
      reviewQueue: [{ id: "r1", title: "What is the VAT late payment penalty?", riskLevel: "HIGH", reason: "", source: "user_feedback", status: "open", createdAt: null, href: "/review-tasks" }],
      recentWork: [{ id: "d1", kind: "draft", title: "Q2 compliance summary", subtitle: "Draft report · Draft", at: null, href: "/drafts-reports" }],
    });
    render(<CommandCenter />);
    expect(await screen.findByText("Escalation: Lease classification")).toBeInTheDocument();
    expect(screen.getByText("What is the VAT late payment penalty?")).toBeInTheDocument();
    expect(screen.getByText("Q2 compliance summary")).toBeInTheDocument();
    expect(screen.getByText("Zoiko Finance")).toBeInTheDocument();
    expect(screen.getByText(/, Naresh\./)).toBeInTheDocument();
    expect(screen.queryByText("IFRS 15 matter requires human review")).not.toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith("token", { jurisdiction: "US", framework: "US-GAAP", period: "FY2026" }, expect.anything());
  });

  it("says a panel is empty or restricted instead of inventing items", async () => {
    api.get.mockResolvedValue({ ...base, moduleFreshness: { ...base.moduleFreshness, reviewQueue: { state: "restricted" } } });
    render(<CommandCenter />);
    expect(await screen.findByText("Nothing needs your attention right now.")).toBeInTheDocument();
    expect(screen.getByText("Your role cannot see this panel.")).toBeInTheDocument();
    expect(screen.getByText("Assurance not fully assessed")).toBeInTheDocument();
  });

  it("reports a load failure", async () => {
    api.get.mockRejectedValue(new Error("down"));
    render(<CommandCenter />);
    expect(await screen.findByText("Could not load the Command Center from the server.")).toBeInTheDocument();
  });
});
