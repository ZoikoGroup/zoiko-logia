import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import type { AnswerPresentation, PresentationChart } from "@/lib/api";
import { exportPresentationWaterfallCsv } from "@/lib/export/exportPresentationWaterfallCsv";

// jsdom has no canvas 2D context, so echarts-for-react's real render throws
// there — mock it at the boundary (same pattern as AnswerVisualizations.test.tsx's
// box_plot test) and assert on the ECharts option this app builds.
const echartsOptionCalls: unknown[] = [];
vi.mock("echarts-for-react", () => ({
  default: (props: { option: unknown }) => {
    echartsOptionCalls.push(props.option);
    return <div data-testid="echarts-stub" />;
  },
}));

const blobs: Blob[] = [];
URL.createObjectURL = vi.fn((blob: Blob) => { blobs.push(blob); return `blob:mock-${blobs.length}`; });
URL.revokeObjectURL = vi.fn();

const { AnswerVisualizations } = await import("@/components/AnswerVisualizations");

function makePresentation(chart: PresentationChart): AnswerPresentation {
  return {
    layout: "data_visualization", table_count: 1, has_steps: false,
    charts: [chart], guides: [], graphs: [], sections: [], follow_up_questions: [],
  };
}

const baseChart = {
  chart_id: "c1", title: "Test chart", unit: "$", domain: "general" as const, summary_mode: "total" as const,
};

describe("AnswerChartFigure — Dynamic Visualization Selection v2 chart types", () => {
  it("renders scatter without crashing", () => {
    const chart: PresentationChart = {
      ...baseChart, type: "scatter",
      categories: ["A", "B", "C", "D", "E"],
      series: [
        { name: "Revenue", values: ["100", "200", "150", "300", "250"], unit: "$" },
        { name: "Headcount", values: ["10", "20", "15", "30", "25"], unit: "" },
      ],
    };
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    expect(screen.getAllByText("Test chart").length).toBeGreaterThan(0);
  });

  it("renders bubble without crashing and shows a size explanation", () => {
    const chart: PresentationChart = {
      ...baseChart, type: "bubble",
      categories: ["A", "B", "C", "D", "E"],
      series: [
        { name: "Revenue", values: ["100", "200", "150", "300", "250"], unit: "$" },
        { name: "Headcount", values: ["10", "20", "15", "30", "25"], unit: "" },
        { name: "Market Cap", values: ["1000", "2000", "1500", "3000", "2500"], unit: "$" },
      ],
    };
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    expect(screen.getByText(/bubble size represents/i)).toBeTruthy();
    // "Market Cap" legitimately appears twice — the size caption and the
    // table alternative's column header — so assert on the count, not a
    // single unique match.
    expect(screen.getAllByText("Market Cap").length).toBeGreaterThan(1);
  });

  it("shows an invalid-data message when bubble is missing its size series", () => {
    const chart: PresentationChart = {
      ...baseChart, type: "bubble",
      categories: ["A", "B"],
      series: [
        { name: "Revenue", values: ["100", "200"], unit: "$" },
        { name: "Headcount", values: ["10", "20"], unit: "" },
      ],
    };
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    expect(screen.getByText(/exactly 3 data series/i)).toBeTruthy();
  });

  it("renders dumbbell without crashing", () => {
    const chart: PresentationChart = {
      ...baseChart, type: "dumbbell",
      categories: ["Payroll", "Technology", "Marketing"],
      series: [
        { name: "Baseline", values: ["150000", "60000", "45000"], unit: "$" },
        { name: "Current", values: ["158000", "72000", "39000"], unit: "$" },
      ],
    };
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    expect(screen.getAllByText("Test chart").length).toBeGreaterThan(0);
  });

  it("renders lollipop sorted descending by value", () => {
    const chart: PresentationChart = {
      ...baseChart, type: "lollipop",
      categories: ["Payroll", "Technology", "Marketing"],
      series: [{ name: "Spend", values: ["45000", "158000", "72000"], unit: "$" }],
    };
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    const details = screen.getByText("View as table").closest("details") as HTMLElement;
    const rowHeaders = within(details).getAllByRole("rowheader").map((el) => el.textContent);
    // The table alternative keeps the original (unsorted) source order —
    // only the chart's own internal data feed is sorted for display.
    expect(rowHeaders).toEqual(["Payroll", "Technology", "Marketing"]);
  });

  it("renders heatmap through the mocked ECharts boundary", () => {
    echartsOptionCalls.length = 0;
    const chart: PresentationChart = {
      ...baseChart, type: "heatmap",
      categories: ["Payroll", "Technology"],
      series: [
        { name: "Q1", values: ["100", "60"], unit: "$" },
        { name: "Q2", values: ["110", "65"], unit: "$" },
      ],
    };
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    expect(screen.getByTestId("echarts-stub")).toBeTruthy();
    const option = echartsOptionCalls.at(-1) as { series: { type: string; data: [number, number, number][] }[] };
    expect(option.series[0].type).toBe("heatmap");
    expect(option.series[0].data).toHaveLength(4);
  });

  it("renders correlation_matrix with coefficient values in the accessible table", () => {
    echartsOptionCalls.length = 0;
    const chart: PresentationChart = {
      ...baseChart, type: "correlation_matrix", unit: "",
      categories: ["Revenue", "Headcount"],
      series: [
        { name: "Revenue", values: ["1.00", "0.87"], unit: "" },
        { name: "Headcount", values: ["0.87", "1.00"], unit: "" },
      ],
    };
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    expect(screen.getByTestId("echarts-stub")).toBeTruthy();
    const details = screen.getByText("View as table").closest("details") as HTMLElement;
    // Both variables (as row and column headers) and the coefficients
    // themselves are present in the accessible table alternative, and
    // never formatted as currency — a coefficient is always unitless
    // regardless of what the original correlated measures were in.
    expect(within(details).getByRole("columnheader", { name: "Revenue" })).toBeTruthy();
    expect(within(details).getByRole("columnheader", { name: "Headcount" })).toBeTruthy();
    expect(within(details).getAllByText("0.87").length).toBeGreaterThan(0);
    expect(within(details).queryByText("$0.87")).toBeNull();
  });

  it("renders bullet distinguishing actual and target through the mocked ECharts boundary", () => {
    echartsOptionCalls.length = 0;
    const chart: PresentationChart = {
      ...baseChart, type: "bullet",
      categories: ["Payroll", "Technology"],
      series: [
        { name: "Actual", values: ["158000", "72000"], unit: "$" },
        { name: "Budget", values: ["150000", "60000"], unit: "$" },
      ],
    };
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    const option = echartsOptionCalls.at(-1) as { series: { type: string; symbol?: string }[] };
    // Actual is a bar, target a distinctly-shaped marker — not color alone.
    expect(option.series[0].type).toBe("bar");
    expect(option.series[1].type).toBe("scatter");
    expect(option.series[1].symbol).toBe("rect");
  });

  it("renders waterfall through the mocked ECharts boundary with reconciling steps", () => {
    echartsOptionCalls.length = 0;
    const chart: PresentationChart = {
      ...baseChart, type: "waterfall",
      categories: ["Revenue", "COGS", "Marketing", "Net Income"],
      series: [{ name: "Amount", values: ["500000", "-320000", "-50000", "130000"], unit: "$" }],
    };
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    const option = echartsOptionCalls.at(-1) as { series: { name: string; data: number[] }[] };
    const byName = Object.fromEntries(option.series.map((s) => [s.name, s.data]));
    expect(byName["Start / total"]).toEqual([500000, 0, 0, 130000]);
    expect(byName["Decrease"]).toEqual([0, 320000, 50000, 0]);
  });

  it("offers PNG, CSV, and Save actions for every v2 chart type", () => {
    // Each type needs a structurally valid series count or it hits the
    // invalid-data branch instead (which intentionally omits these actions
    // — see the bubble invalid-data test above).
    const seriesCountByType: Record<string, number> = {
      scatter: 2, bubble: 3, dumbbell: 2, lollipop: 1, heatmap: 2, correlation_matrix: 3, bullet: 2, waterfall: 1,
    };
    for (const [type, seriesCount] of Object.entries(seriesCountByType)) {
      const chart: PresentationChart = {
        ...baseChart, chart_id: type, type: type as PresentationChart["type"],
        categories: ["A", "B"],
        series: Array.from({ length: seriesCount }, (_, index) => ({
          name: `Series ${index + 1}`, values: ["1", "2"], unit: "$",
        })),
      };
      const { unmount } = render(<AnswerVisualizations presentation={makePresentation(chart)} queryId="q1" />);
      expect(screen.getByText("Download PNG")).toBeTruthy();
      expect(screen.getByText("Export CSV")).toBeTruthy();
      expect(screen.getByText("Save")).toBeTruthy();
      unmount();
    }
  });
});

describe("exportPresentationWaterfallCsv", () => {
  it("includes step, raw change, running total, and step type columns", async () => {
    blobs.length = 0;
    const chart: PresentationChart = {
      ...baseChart, type: "waterfall",
      categories: ["Revenue", "COGS", "Marketing", "Net Income"],
      series: [{ name: "Amount", values: ["500000", "-320000", "-50000", "130000"], unit: "$" }],
    };
    exportPresentationWaterfallCsv(chart);
    expect(blobs).toHaveLength(1);
    const text = await blobs[0].text();
    expect(text).toContain("Step");
    expect(text).toContain("Raw change");
    expect(text).toContain("Running total");
    expect(text).toContain("Step type");
    expect(text).toContain("start");
    expect(text).toContain("decrease");
    expect(text).toContain("total");
    // Running total after COGS: 500000 - 320000 = 180000.
    expect(text).toContain("180000");
  });
});
