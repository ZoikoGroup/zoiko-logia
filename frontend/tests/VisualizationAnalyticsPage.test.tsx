import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type {
  RecommendationQualitySummaryResponse, ReplacementMatrixResponse, ChartTypePerformanceResponse,
  WeightAdjustmentProposal, RankingConfiguration,
} from "@/lib/api";

const approveCalls: string[] = [];

function makeMetric(rate: number, sampleSize: number, numerator?: number) {
  return {
    rate, numerator: numerator ?? Math.round(rate * sampleSize), sample_size: sampleSize,
    evidence_status: sampleSize <= 9 ? "insufficient_evidence" : sampleSize <= 49 ? "directional_signal" : "eligible_for_review",
  } as const;
}

const summaryResponse: RecommendationQualitySummaryResponse = {
  rows: [{
    group_key: {},
    total_selections: 120,
    recommendation_retention_rate: makeMetric(0.72, 120),
    alternative_views_shown_rate: makeMetric(0.9, 120),
    alternative_switch_rate: makeMetric(0.28, 120),
    png_export_rate: makeMetric(0.1, 120),
    csv_export_rate: makeMetric(0.05, 120),
    visualization_save_rate: makeMetric(0.15, 120),
    render_failure_rate: makeMetric(0.02, 120),
    fallback_rate: makeMetric(0.01, 5),
  }],
  date_from: null, date_to: null, group_by: [],
};

const matrixResponse: ReplacementMatrixResponse = {
  cells: [
    { original_chart_type: "donut", active_chart_type: "composition_bar", count: 12, rate: 0.6, sample_size: 20, evidence_status: "directional_signal" },
  ],
  date_from: null, date_to: null,
};

const performanceResponse: ChartTypePerformanceResponse = {
  rows: [
    {
      group_key: {}, chart_type: "bar", total_selections: 60,
      switch_rate: makeMetric(0.5, 60), fallback_rate: makeMetric(0.05, 60), render_failure_rate: makeMetric(0.01, 60),
      unusually_high_switch_rate: true, unusually_high_fallback_rate: false, unusually_high_render_failure_rate: false,
    },
    {
      group_key: {}, chart_type: "grouped_bar", total_selections: 60,
      switch_rate: makeMetric(0.1, 60), fallback_rate: makeMetric(0.01, 60), render_failure_rate: makeMetric(0.0, 60),
      unusually_high_switch_rate: false, unusually_high_fallback_rate: false, unusually_high_render_failure_rate: false,
    },
  ],
  date_from: null, date_to: null, group_by: [],
};

const proposalsResponse: WeightAdjustmentProposal[] = [
  {
    affected_analytical_intent: "comparison", affected_chart_family: null,
    current_chart_preference: "bar", observed_replacement: "grouped_bar",
    sample_size: 60, retention_or_switch_rate: 0.5,
    proposed_weight_adjustment: { analytical_intent_fit: 0.02 }, review_required: true,
  },
];

const configurationsResponse: RankingConfiguration[] = [
  {
    id: "cfg-approved", ranking_version: "1.0.0", effective_from: "2026-01-01T00:00:00Z",
    weights: { analytical_intent_fit: 0.28, complexity_penalty: -0.1 },
    status: "approved", created_by: "user-a", approved_by: "user-b", approved_at: "2026-01-02T00:00:00Z",
    created_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "cfg-draft", ranking_version: "1.1.0-draft", effective_from: "2026-02-01T00:00:00Z",
    weights: { analytical_intent_fit: 0.3, complexity_penalty: -0.1 },
    status: "draft", created_by: "user-a", approved_by: null, approved_at: null,
    created_at: "2026-02-01T00:00:00Z",
  },
];

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    getAuthToken: () => "test-token",
    getRecommendationQualitySummary: vi.fn(async () => summaryResponse),
    getReplacementMatrix: vi.fn(async () => matrixResponse),
    getChartTypePerformance: vi.fn(async () => performanceResponse),
    getWeightProposals: vi.fn(async () => proposalsResponse),
    listRankingConfigurations: vi.fn(async () => configurationsResponse),
    approveRankingConfiguration: vi.fn(async (_token: string, id: string) => {
      approveCalls.push(id);
      return { ...configurationsResponse[1], status: "approved" as const };
    }),
  };
});

const { default: VisualizationAnalyticsPage } = await import("@/app/visualization-analytics/page");

describe("Visualization Analytics dashboard", () => {
  it("renders total selections and every rate with its sample size", async () => {
    render(<VisualizationAnalyticsPage />);
    await waitFor(() => expect(screen.getByText("120")).toBeTruthy());
    expect(screen.getByText("72.0%")).toBeTruthy();
    expect(screen.getAllByText("n=120").length).toBeGreaterThan(0);
  });

  it("marks a low-sample metric as insufficient evidence", async () => {
    render(<VisualizationAnalyticsPage />);
    await waitFor(() => expect(screen.getByText("120")).toBeTruthy());
    // fallback_rate has sample_size=5 in the fixture — below the
    // insufficient-evidence threshold.
    expect(screen.getAllByText("insufficient evidence").length).toBeGreaterThan(0);
  });

  it("shows the replacement matrix", async () => {
    render(<VisualizationAnalyticsPage />);
    await waitFor(() => expect(screen.getByText("donut")).toBeTruthy());
    expect(screen.getByText("composition_bar")).toBeTruthy();
    expect(screen.getByText("12")).toBeTruthy();
  });

  it("flags the chart type with an unusually high switch rate", async () => {
    render(<VisualizationAnalyticsPage />);
    await waitFor(() => expect(screen.getAllByText("bar").length).toBeGreaterThan(0));
    expect(screen.getAllByText("unusually high").length).toBeGreaterThan(0);
    expect(screen.getByText("1 chart type(s) flagged for review above.")).toBeTruthy();
  });

  it("shows recommendation-analysis findings marked review required", async () => {
    render(<VisualizationAnalyticsPage />);
    await waitFor(() => expect(screen.getByText(/comparison/)).toBeTruthy());
    expect(screen.getAllByText("review required").length).toBeGreaterThan(0);
  });

  it("never renders user-level identifiers (actor_id, conversation_id, query_id)", async () => {
    const { container } = render(<VisualizationAnalyticsPage />);
    await waitFor(() => expect(screen.getByText("120")).toBeTruthy());
    const html = container.innerHTML;
    expect(html).not.toContain("actor_id");
    expect(html).not.toContain("conversation_id");
    expect(html).not.toContain("query_id");
  });

  it("only shows an Approve action for draft configurations, not approved ones", async () => {
    render(<VisualizationAnalyticsPage />);
    await waitFor(() => expect(screen.getByText("1.0.0")).toBeTruthy());
    const approveButtons = screen.getAllByText("Approve");
    expect(approveButtons).toHaveLength(1);
  });

  it("approving a draft calls the API and reloads the configuration list", async () => {
    render(<VisualizationAnalyticsPage />);
    await waitFor(() => expect(screen.getByText("1.1.0-draft")).toBeTruthy());
    fireEvent.click(screen.getByText("Approve"));
    await waitFor(() => expect(approveCalls).toContain("cfg-draft"));
  });

  it("shows a weight-difference comparison once two configurations are selected", async () => {
    render(<VisualizationAnalyticsPage />);
    await waitFor(() => expect(screen.getByText("Compare configurations")).toBeTruthy());
    const [baselineSelect, proposedSelect] = screen.getAllByRole("combobox").slice(-2);
    fireEvent.change(baselineSelect, { target: { value: "cfg-approved" } });
    fireEvent.change(proposedSelect, { target: { value: "cfg-draft" } });
    await waitFor(() => expect(screen.getByText("analytical_intent_fit")).toBeTruthy());
    expect(screen.getByText("+0.020")).toBeTruthy();
  });

  it("shows a friendly error instead of crashing when the API call fails (e.g. non-admin caller)", async () => {
    const api = await import("@/lib/api");
    vi.mocked(api.getRecommendationQualitySummary).mockRejectedValueOnce(new Error("403"));
    render(<VisualizationAnalyticsPage />);
    await waitFor(() => expect(screen.getByText(/Admin access/i)).toBeTruthy());
  });
});
