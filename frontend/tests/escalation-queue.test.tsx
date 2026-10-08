import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
const api = vi.hoisted(() => ({ list: vi.fn(), stats: vi.fn(), overrides: vi.fn(), act: vi.fn(), create: vi.fn() }));
vi.mock("@/lib/safety-api", () => ({
  getEscalations: api.list, getEscalationStats: api.stats, getSafetyOverrides: api.overrides,
  actOnEscalation: api.act, createSafetyOverride: api.create,
}));
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ user: { id: "u-1", email: "naresh@example.com" }, profile: { full_name: "Naresh Maruthi", role: "Admin" } }) }));
vi.mock("@/components/governance/PageHeader", () => ({ PageHeader: ({ title }: { title: string }) => <h1>{title}</h1> }));
import EscalationQueuePage from "@/app/escalation-queue/page";

beforeEach(() => {
  api.list.mockReset().mockResolvedValue([]);
  api.stats.mockReset().mockResolvedValue({ total: 0, pending: 0, under_review: 0, resolved: 0, refused: 0, escalated: 0, over_sla: 0 });
  api.overrides.mockReset().mockResolvedValue([]);
});

describe("escalation queue", () => {
  it("shows who is acting instead of an editable actor box", async () => {
    render(<EscalationQueuePage />);
    expect(await screen.findByText("No active escalation cases found.")).toBeInTheDocument();
    expect(screen.getByText("Naresh Maruthi")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("user_admin")).not.toBeInTheDocument();
    expect(api.list).toHaveBeenCalledWith(true);
  });

  it("reports a load failure instead of an empty queue", async () => {
    api.list.mockRejectedValue(new Error("Missing permission: safety.read"));
    render(<EscalationQueuePage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Missing permission: safety.read");
    expect(screen.queryByText("No active escalation cases found.")).not.toBeInTheDocument();
  });
});
