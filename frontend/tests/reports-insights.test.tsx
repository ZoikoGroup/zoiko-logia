import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
const api = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/insights-api", () => ({ getInsights: api.get }));
vi.mock("@/components/governance/PageShell", () => ({ PageShell: ({ children }: { children: React.ReactNode }) => <main>{children}</main> }));
import ReportsInsightsPage from "@/app/reports-insights/page";

const report = {
  windowDays: 7, since: "2026-10-07T12:00:00Z", generatedAt: "2026-10-14T12:00:00Z", totalQuestions: 12,
  questionsPerDay: [{ date: "2026-10-10", count: 5 }, { date: "2026-10-13", count: 7 }],
  outcomes: [{ label: "answered", count: 9 }, { label: "refused", count: 3 }],
  routes: [{ label: "LLM", count: 9 }], riskLevels: [{ label: "LOW", count: 10 }, { label: "HIGH", count: 2 }],
  latency: { averageMs: 20854, maxMs: 70375, measured: 12 },
  answers: { answersSampled: 4, topics: [{ label: "tax", count: 3 }], sourceSites: [{ label: "gov.uk", count: 2 }] },
  reviews: { byStatus: { open: 2, resolved: 1 }, bySource: { escalation: 3 }, total: 3 },
  feedback: { up: 4, down: 1 },
  workspace: { savedAnswers: 6, draftsByStatus: { Draft: 2, Final: 1 }, cpdMinutes: 90, cpdEntries: 2 },
  unavailable: [],
};

beforeEach(() => {
  api.get.mockReset().mockResolvedValue(report);
});

describe("Reports & Insights", () => {
  it("shows real totals, not the old sample numbers", async () => {
    render(<ReportsInsightsPage />);
    expect(await screen.findByText("Questions asked")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("75%")).toBeInTheDocument();            // 9 of 12 answered
    expect(screen.getByText("20.9s")).toBeInTheDocument();
    expect(screen.getByText("4 / 1")).toBeInTheDocument();
    expect(screen.getByText("1.5h")).toBeInTheDocument();
    expect(screen.queryByText("Q2 compliance summary")).not.toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith(30, expect.anything());
  });

  it("fills every day of the range and offers a table view", async () => {
    api.get.mockResolvedValue(report);
    render(<ReportsInsightsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Last 7 days" }));
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith(7, expect.anything()));
    fireEvent.click(await screen.findByRole("button", { name: "Show table" }));
    const rows = within(screen.getByRole("table")).getAllByRole("row");
    expect(rows).toHaveLength(1 + 7);                                // header + one row per day, zeros included
  });

  it("names a section the backend could not read", async () => {
    api.get.mockResolvedValue({ ...report, feedback: null, unavailable: ["feedback"] });
    render(<ReportsInsightsPage />);
    expect(await screen.findByText(/could not be read in time: feedback/)).toBeInTheDocument();
  });

  it("reports a load failure", async () => {
    api.get.mockRejectedValue(new Error("500"));
    render(<ReportsInsightsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load insights from the server.");
  });
});
