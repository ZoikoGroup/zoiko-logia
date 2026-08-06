import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { RankingExperiment, RankingConfiguration, ExperimentResultsResponse } from "@/lib/api";

const approveCalls: string[] = [];
const activateCalls: string[] = [];
const rollbackCalls: { id: string; reason: string }[] = [];
const pauseCalls: { id: string; reason: string }[] = [];

function makeMetric(rate: number, sampleSize: number) {
  return {
    rate, numerator: Math.round(rate * sampleSize), sample_size: sampleSize,
    evidence_status: sampleSize <= 9 ? "insufficient_evidence" : sampleSize <= 49 ? "directional_signal" : "eligible_for_review",
    confidence_interval_low: Math.max(0, rate - 0.1), confidence_interval_high: Math.min(1, rate + 0.1),
  } as const;
}

function makeGroupMetrics(group: "control" | "variant", rankingVersion: string, selections: number) {
  return {
    group, ranking_version: rankingVersion, selections,
    recommendation_retention_rate: makeMetric(0.7, selections),
    alternative_views_shown_rate: makeMetric(0.9, selections),
    alternative_switch_rate: makeMetric(0.2, selections),
    png_export_rate: makeMetric(0.1, selections),
    csv_export_rate: makeMetric(0.05, selections),
    visualization_save_rate: makeMetric(0.15, selections),
    render_failure_rate: makeMetric(0.01, selections),
    fallback_rate: makeMetric(0.02, selections),
  };
}

const draftExperiment: RankingExperiment = {
  id: "exp-draft", name: "Draft Experiment", description: "Testing a new weight set",
  status: "draft", control_ranking_version: "1.0.0", variant_ranking_version: "1.1.0",
  control_allocation_percent: 50, variant_allocation_percent: 50, targeting_rules: {},
  primary_metrics: ["recommendation_retention_rate"], secondary_metrics: [], guardrail_metrics: ["render_failure_rate"],
  minimum_sample_size: 100, start_at: null, end_at: null, created_by: "user-a", approved_by: null,
  status_reason: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};

const approvedExperiment: RankingExperiment = {
  ...draftExperiment, id: "exp-approved", name: "Approved Experiment", status: "approved", approved_by: "user-b",
};

const activeExperiment: RankingExperiment = {
  ...draftExperiment, id: "exp-active", name: "Active Experiment", status: "active", approved_by: "user-b",
};

const pausedExperiment: RankingExperiment = {
  ...draftExperiment, id: "exp-paused", name: "Paused Experiment", status: "paused", approved_by: "user-b",
  status_reason: "guardrail: variant render_failure_rate exceeds the guardrail threshold relative to control",
};

const configurations: RankingConfiguration[] = [
  {
    id: "cfg-control", ranking_version: "1.0.0", effective_from: "2026-01-01T00:00:00Z",
    weights: { analytical_intent_fit: 0.28, complexity_penalty: -0.1 },
    status: "approved", created_by: "user-a", approved_by: "user-b", approved_at: "2026-01-02T00:00:00Z",
    created_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "cfg-variant", ranking_version: "1.1.0", effective_from: "2026-01-01T00:00:00Z",
    weights: { analytical_intent_fit: 0.35, complexity_penalty: -0.1 },
    status: "approved", created_by: "user-a", approved_by: "user-b", approved_at: "2026-01-02T00:00:00Z",
    created_at: "2026-01-01T00:00:00Z",
  },
];

const defaultResults: ExperimentResultsResponse = {
  experiment_id: "exp-active", status: "active", result_status: "experiment_running",
  minimum_sample_size: 100,
  control: makeGroupMetrics("control", "1.0.0", 40),
  variant: makeGroupMetrics("variant", "1.1.0", 40),
  guardrail_findings: [],
};

let experimentsToReturn: RankingExperiment[] = [];
let resultsToReturn: ExperimentResultsResponse = defaultResults;

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    getAuthToken: () => "test-token",
    listExperiments: vi.fn(async () => experimentsToReturn),
    listRankingConfigurations: vi.fn(async () => configurations),
    getExperimentResults: vi.fn(async () => resultsToReturn),
    approveExperiment: vi.fn(async (_token: string, id: string) => {
      approveCalls.push(id);
      return { ...draftExperiment, status: "approved" as const };
    }),
    activateExperiment: vi.fn(async (_token: string, id: string) => {
      activateCalls.push(id);
      return { ...approvedExperiment, status: "active" as const };
    }),
    pauseExperiment: vi.fn(async (_token: string, id: string, reason: string) => {
      pauseCalls.push({ id, reason });
      return { ...activeExperiment, status: "paused" as const, status_reason: reason };
    }),
    completeExperiment: vi.fn(async () => ({ ...activeExperiment, status: "completed" as const })),
    rollbackExperiment: vi.fn(async (_token: string, id: string, reason: string) => {
      rollbackCalls.push({ id, reason });
      return { ...activeExperiment, status: "rolled_back" as const, status_reason: reason };
    }),
  };
});

const { default: RankingExperimentsPage } = await import("@/app/ranking-experiments/page");

describe("Ranking Experiments management view", () => {
  it("lists experiments with status pills", async () => {
    experimentsToReturn = [draftExperiment, activeExperiment];
    render(<RankingExperimentsPage />);
    await waitFor(() => expect(screen.getByText("Draft Experiment")).toBeTruthy());
    expect(screen.getByText("Active Experiment")).toBeTruthy();
    expect(screen.getByText("draft")).toBeTruthy();
    expect(screen.getByText("active")).toBeTruthy();
  });

  it("shows experiment details when selected", async () => {
    experimentsToReturn = [activeExperiment];
    render(<RankingExperimentsPage />);
    await waitFor(() => expect(screen.getByText("Active Experiment")).toBeTruthy());
    fireEvent.click(screen.getByText("Active Experiment"));
    await waitFor(() => expect(screen.getAllByText("1.0.0").length).toBeGreaterThan(0));
    expect(screen.getAllByText("1.1.0").length).toBeGreaterThan(0);
    expect(screen.getByText(/50% control \/ 50% variant/)).toBeTruthy();
  });

  it("shows the pause/rollback reason when present", async () => {
    experimentsToReturn = [pausedExperiment];
    render(<RankingExperimentsPage />);
    await waitFor(() => expect(screen.getByText("Paused Experiment")).toBeTruthy());
    fireEvent.click(screen.getByText("Paused Experiment"));
    await waitFor(() => expect(screen.getByText(/guardrail: variant render_failure_rate/)).toBeTruthy());
  });

  it("approve button calls the API for a draft experiment", async () => {
    approveCalls.length = 0;
    experimentsToReturn = [draftExperiment];
    render(<RankingExperimentsPage />);
    await waitFor(() => expect(screen.getByText("Draft Experiment")).toBeTruthy());
    fireEvent.click(screen.getByText("Draft Experiment"));
    await waitFor(() => expect(screen.getByText("Approve")).toBeTruthy());
    fireEvent.click(screen.getByText("Approve"));
    await waitFor(() => expect(approveCalls).toContain("exp-draft"));
  });

  it("shows a review screen with weight differences before activation, requiring a separate confirmation step", async () => {
    activateCalls.length = 0;
    experimentsToReturn = [approvedExperiment];
    render(<RankingExperimentsPage />);
    await waitFor(() => expect(screen.getByText("Approved Experiment")).toBeTruthy());
    fireEvent.click(screen.getByText("Approved Experiment"));
    await waitFor(() => expect(screen.getByText("Review before activation")).toBeTruthy());
    // The changed weight dimension is visible with both values.
    expect(screen.getByText("analytical_intent_fit")).toBeTruthy();
    expect(screen.getByText("0.280")).toBeTruthy();
    expect(screen.getByText("0.350")).toBeTruthy();
    // Clicking "Activate…" does not itself call the API yet.
    fireEvent.click(screen.getByText("Activate…"));
    expect(activateCalls).toHaveLength(0);
    expect(screen.getByText("Confirm activation")).toBeTruthy();
    fireEvent.click(screen.getByText("Confirm activation"));
    await waitFor(() => expect(activateCalls).toContain("exp-approved"));
  });

  it("requires a non-empty reason before the rollback confirmation step is reachable", async () => {
    experimentsToReturn = [activeExperiment];
    render(<RankingExperimentsPage />);
    await waitFor(() => expect(screen.getByText("Active Experiment")).toBeTruthy());
    fireEvent.click(screen.getByText("Active Experiment"));
    await waitFor(() => expect(screen.getByText("Rollback…")).toBeTruthy());
    expect(screen.getByText("Rollback…").closest("button")).toBeDisabled();
  });

  it("rollback requires a typed reason and a separate confirmation step", async () => {
    rollbackCalls.length = 0;
    experimentsToReturn = [activeExperiment];
    render(<RankingExperimentsPage />);
    await waitFor(() => expect(screen.getByText("Active Experiment")).toBeTruthy());
    fireEvent.click(screen.getByText("Active Experiment"));
    await waitFor(() => expect(screen.getByPlaceholderText("Rollback reason…")).toBeTruthy());
    fireEvent.change(screen.getByPlaceholderText("Rollback reason…"), { target: { value: "regression observed" } });
    fireEvent.click(screen.getByText("Rollback…"));
    expect(rollbackCalls).toHaveLength(0);
    await waitFor(() => expect(screen.getByText("Confirm rollback")).toBeTruthy());
    fireEvent.click(screen.getByText("Confirm rollback"));
    await waitFor(() => expect(rollbackCalls).toEqual([{ id: "exp-active", reason: "regression observed" }]));
  });

  it("pause requires a typed reason before the button is enabled", async () => {
    pauseCalls.length = 0;
    experimentsToReturn = [activeExperiment];
    render(<RankingExperimentsPage />);
    await waitFor(() => expect(screen.getByText("Active Experiment")).toBeTruthy());
    fireEvent.click(screen.getByText("Active Experiment"));
    await waitFor(() => expect(screen.getByPlaceholderText("Pause reason…")).toBeTruthy());
    const pauseButton = screen.getByText("Pause").closest("button") as HTMLButtonElement;
    expect(pauseButton).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText("Pause reason…"), { target: { value: "manual check" } });
    expect(pauseButton).not.toBeDisabled();
    fireEvent.click(pauseButton);
    await waitFor(() => expect(pauseCalls).toEqual([{ id: "exp-active", reason: "manual check" }]));
  });

  it("labels results with the closed result-status vocabulary", async () => {
    experimentsToReturn = [activeExperiment];
    resultsToReturn = { ...defaultResults, result_status: "guardrail_failed", guardrail_findings: ["variant render_failure_rate exceeds the guardrail threshold relative to control"] };
    render(<RankingExperimentsPage />);
    await waitFor(() => expect(screen.getByText("Active Experiment")).toBeTruthy());
    fireEvent.click(screen.getByText("Active Experiment"));
    await waitFor(() => expect(screen.getByText("Guardrail failed")).toBeTruthy());
    expect(screen.getByText(/variant render_failure_rate exceeds/)).toBeTruthy();
  });

  it("shows control and variant sample sizes and rates, never raw user-level identifiers", async () => {
    experimentsToReturn = [activeExperiment];
    resultsToReturn = defaultResults;
    const { container } = render(<RankingExperimentsPage />);
    await waitFor(() => expect(screen.getByText("Active Experiment")).toBeTruthy());
    fireEvent.click(screen.getByText("Active Experiment"));
    await waitFor(() => expect(screen.getByText(/Control · 1.0.0 · 40 selections/)).toBeTruthy());
    expect(screen.getByText(/Variant · 1.1.0 · 40 selections/)).toBeTruthy();
    const html = container.innerHTML;
    expect(html).not.toContain("actor_id");
    expect(html).not.toContain("conversation_id");
    expect(html).not.toContain("query_id");
  });

  it("shows a friendly error instead of crashing when the API call fails (e.g. non-admin caller)", async () => {
    const api = await import("@/lib/api");
    vi.mocked(api.listExperiments).mockRejectedValueOnce(new Error("403"));
    render(<RankingExperimentsPage />);
    await waitFor(() => expect(screen.getByText(/Admin access/i)).toBeTruthy());
  });
});
