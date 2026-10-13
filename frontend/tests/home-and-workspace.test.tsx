import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CommandCenterViewModel } from "@/lib/command-center-types";

const api = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api", () => ({ ApiError: class extends Error {}, getAuthToken: () => "token", getCommandCenter: api.get }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => <a href={href} {...rest}>{children}</a>,
}));
import { CommandCenter } from "@/components/command-center/CommandCenter";
import MyWorkspacePage from "@/app/my-workspace/page";
import { timeAgo } from "@/hooks/useCommandCenter";

const NOW = Date.now();
const iso = (minutesAgo: number) => new Date(NOW - minutesAgo * 60000).toISOString();

const model: CommandCenterViewModel = {
  user: { firstName: "Asha", fullName: "Asha Rao", email: "asha@example.com", role: "Admin" },
  workspace: { name: "Acme Ltd", tenantId: "t1" },
  generatedAt: iso(0),
  counts: { questionsLast7Days: 3, savedAnswers: 1, drafts: 1, attention: 1, reviews: 1, deadlines: 1, activeMatters: 0 },
  attentionItems: [{
    id: "incident:1", severity: "critical", domain: "Security incidents", title: "Prompt bypass attempt (open)",
    ownerRole: "Security lead", dueAt: null, openedAt: iso(60), drilldownTarget: "/incident-response",
    resolvedBy: "Resolving the underlying record",
  }],
  reviewQueue: [{ id: "review:1", type: "Answer review", title: "Is this deductible?", submittedAt: iso(30),
    drilldownTarget: "/review-tasks", blockedReason: null }],
  deadlines: [{ id: "licence:1", title: "“FRS 102” v2 expires soon", dueAt: new Date(NOW + 86400000).toISOString(),
    overdue: false, href: "/source-licensing" }],
  activeMatters: [],
  recentWork: [{ id: "question:q1", kind: "Kriton question", title: "What is the VAT rate?", at: iso(18), href: "/ask-kriton" }],
  breakGlass: [],
  assurance: { overallState: "critical", blockedGates: 2 },
};

beforeEach(() => {
  api.get.mockReset();
});

describe("Command Center (home)", () => {
  it("greets the real user with their live items, no sample data", async () => {
    api.get.mockResolvedValue(model);
    render(<CommandCenter />);
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent(/, Asha\.$/);
    expect(screen.getByText("Prompt bypass attempt (open)")).toBeInTheDocument();
    expect(screen.getByText("What is the VAT rate?")).toBeInTheDocument();
    expect(screen.getByText(/You are not a member of any engagement yet/)).toBeInTheDocument();
    expect(screen.getByText(/2 release gates blocked/)).toBeInTheDocument();
    expect(screen.queryByText(/Lennox|Zoiko Sema|Zoiko Electronics/)).not.toBeInTheDocument();
  });

  it("says when nothing needs attention", async () => {
    api.get.mockResolvedValue({ ...model, attentionItems: [], reviewQueue: [], deadlines: [],
      counts: { ...model.counts, attention: 0, reviews: 0, deadlines: 0 } });
    render(<CommandCenter />);
    expect(await screen.findByText("Nothing needs your attention right now.")).toBeInTheDocument();
  });
});

describe("My Workspace", () => {
  it("shows the user's own profile, activity and decisions", async () => {
    api.get.mockResolvedValue(model);
    render(<MyWorkspacePage />);
    expect(await screen.findByText("asha@example.com")).toBeInTheDocument();
    expect(screen.getByText("Is this deductible?")).toBeInTheDocument();
    expect(screen.getByText("What is the VAT rate?")).toBeInTheDocument();
    expect(screen.queryByText(/Atlas Financial|Meridian Health/)).not.toBeInTheDocument();
  });
});

describe("timeAgo", () => {
  it("formats recent times in plain words", () => {
    expect(timeAgo(new Date(NOW - 30_000).toISOString(), NOW)).toBe("just now");
    expect(timeAgo(new Date(NOW - 18 * 60000).toISOString(), NOW)).toBe("18 min ago");
    expect(timeAgo(new Date(NOW - 3 * 3600000).toISOString(), NOW)).toBe("3 h ago");
    expect(timeAgo(new Date(NOW - 2 * 86400000).toISOString(), NOW)).toBe("2 days ago");
    expect(timeAgo(null)).toBe("");
  });
});
