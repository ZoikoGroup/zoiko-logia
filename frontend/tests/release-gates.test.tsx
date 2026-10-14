import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api", () => ({ ApiError: class extends Error {}, getAuthToken: () => "token", getReleaseReadiness: api.get }));
vi.mock("@/components/governance/PageShell", () => ({ PageShell: ({ children }: { children: React.ReactNode }) => <main>{children}</main> }));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));
import ReleaseGatesPage from "@/app/release-gates/page";

beforeEach(() => {
  api.get.mockReset();
});

describe("Release Gates", () => {
  it("shows measured gate states instead of hard-coded passes", async () => {
    api.get.mockResolvedValue([
        { gate: "Evaluation", state: "blocked", reason: "No evaluation run has been recorded." },
        { gate: "Audit ledger", state: "passed", reason: "Hash chain intact." },
        { gate: "Rollback point", state: "not_assessed", reason: "Canary and rollback verification are not built yet." },
      ]);
    render(<ReleaseGatesPage />);
    expect(await screen.findByText("Release blocked by 1 gate.")).toBeInTheDocument();
    expect(screen.getByText("No evaluation run has been recorded.")).toBeInTheDocument();
    expect(screen.getByText("Not assessed")).toBeInTheDocument();
    expect(screen.queryByText("Rights & licensing sign-off")).not.toBeInTheDocument();
  });
});
