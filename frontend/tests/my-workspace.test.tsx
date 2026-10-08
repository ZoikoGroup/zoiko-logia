import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
const api = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/my-workspace-api", () => ({ getMyWorkspace: api.get }));
vi.mock("@/components/governance/PageHeader", () => ({ PageHeader: ({ title }: { title: string }) => <h1>{title}</h1> }));
vi.mock("next/link", () => ({ default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => <a href={href} {...rest}>{children}</a> }));
import MyWorkspacePage from "@/app/my-workspace/page";

beforeEach(() => {
  api.get.mockReset();
});

describe("My Workspace", () => {
  it("lists the user's real activity and tasks, not sample items", async () => {
    api.get.mockResolvedValue({
      generatedAt: "2026-10-08T12:00:00Z",
      recentActivity: [{ id: "draft:d1", kind: "draft", label: "Edited draft: Board memo (Draft)", at: null, href: "/drafts-reports" }],
      pendingTasks: [{ id: "review:rc1", kind: "review", label: "Review answer: VAT on vouchers?", status: "Open", tone: "bad", dueAt: null, href: "/review-tasks" }],
    });
    render(<MyWorkspacePage />);
    expect(await screen.findByText("Edited draft: Board memo (Draft)")).toBeInTheDocument();
    expect(screen.getByText("Review answer: VAT on vouchers?").closest("a")).toHaveAttribute("href", "/review-tasks");
    expect(screen.queryByText(/Meridian Health Group/)).not.toBeInTheDocument();
  });

  it("says when there is nothing yet", async () => {
    api.get.mockResolvedValue({ generatedAt: "", recentActivity: [], pendingTasks: [] });
    render(<MyWorkspacePage />);
    expect(await screen.findByText("Nothing is waiting on you.")).toBeInTheDocument();
    expect(screen.getByText(/No activity yet/)).toBeInTheDocument();
  });

  it("reports a load failure", async () => {
    api.get.mockRejectedValue(new Error("500"));
    render(<MyWorkspacePage />);
    expect(await screen.findByText("Could not load your workspace from the server.")).toBeInTheDocument();
  });
});
