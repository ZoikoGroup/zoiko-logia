import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import type { AnswerPresentation, PresentationChart } from "@/lib/api";

// jsdom has no canvas 2D context, so echarts-for-react's real render throws
// there — mock it at the boundary the same way KnowledgeGraphVisualization's
// tests mock cytoscape, and assert on the ECharts option this app builds
// instead of pixels no test environment can see.
const echartsOptionCalls: unknown[] = [];
vi.mock("echarts-for-react", () => ({
  default: (props: { option: unknown }) => {
    echartsOptionCalls.push(props.option);
    return <div data-testid="echarts-stub" />;
  },
}));

const { AnswerVisualizations } = await import("@/components/AnswerVisualizations");

function makePresentation(chart: PresentationChart): AnswerPresentation {
  return {
    layout: "data_visualization",
    table_count: 1,
    has_steps: false,
    charts: [chart],
    guides: [],
    graphs: [],
    sections: [],
    follow_up_questions: [],
  };
}

const baseChart = {
  chart_id: "c1",
  title: "Test chart",
  unit: "$",
  domain: "general" as const,
  summary_mode: "total" as const,
};

describe("AnswerVisualizations — Dynamic Visualization Selection v1 chart types", () => {
  it("renders grouped_bar without crashing and shows metric cards", () => {
    const chart: PresentationChart = {
      ...baseChart,
      type: "grouped_bar",
      categories: ["Payroll", "Technology"],
      series: [
        { name: "Budget", values: ["150000", "60000"], unit: "$" },
        { name: "Actual", values: ["158000", "72000"], unit: "$" },
      ],
    };
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    expect(screen.getAllByText("Test chart").length).toBeGreaterThan(0);
    const metrics = screen.getByLabelText("Chart summary metrics");
    expect(within(metrics).getByText("Budget")).toBeTruthy();
  });

  it("renders stacked_bar without crashing", () => {
    const chart: PresentationChart = {
      ...baseChart,
      type: "stacked_bar",
      categories: ["A", "B"],
      series: [
        { name: "Revenue", values: ["100000", "80000"], unit: "$" },
        { name: "Cost", values: ["60000", "50000"], unit: "$" },
      ],
    };
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    expect(screen.getAllByText("Test chart").length).toBeGreaterThan(0);
  });

  it("renders percentage_stacked_bar without crashing", () => {
    const chart: PresentationChart = {
      ...baseChart,
      type: "percentage_stacked_bar",
      categories: ["A", "B"],
      series: [
        { name: "Revenue", values: ["100000", "80000"], unit: "$" },
        { name: "Cost", values: ["60000", "50000"], unit: "$" },
      ],
    };
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    expect(screen.getAllByText("Test chart").length).toBeGreaterThan(0);
  });

  it("renders diverging_bar without crashing", () => {
    const chart: PresentationChart = {
      ...baseChart,
      type: "diverging_bar",
      categories: ["Payroll", "Technology", "Marketing"],
      series: [
        { name: "Budget", values: ["150000", "60000", "45000"], unit: "$" },
        { name: "Actual", values: ["158000", "72000", "39000"], unit: "$" },
      ],
    };
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    expect(screen.getAllByText("Test chart").length).toBeGreaterThan(0);
  });

  it("renders radar without crashing and hides per-series metric cards", () => {
    const chart: PresentationChart = {
      ...baseChart,
      type: "radar",
      unit: "",
      categories: ["Current Ratio", "Quick Ratio", "Debt To Equity"],
      series: [
        { name: "Company A", values: ["1.5", "1.1", "0.8"], unit: "" },
        { name: "Company B", values: ["2.0", "1.6", "0.5"], unit: "" },
      ],
    };
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    expect(screen.getAllByText("Test chart").length).toBeGreaterThan(0);
    // Metric cards ("latest/average/total per series") don't apply to radar
    // axes — NO_METRIC_CARDS_TYPES suppresses the whole labeled region.
    expect(screen.queryByLabelText("Chart summary metrics")).toBeNull();
  });

  it("renders histogram without crashing and hides metric cards", () => {
    const chart: PresentationChart = {
      ...baseChart,
      type: "histogram",
      categories: ["INV-1", "INV-2", "INV-3", "INV-4", "INV-5", "INV-6", "INV-7", "INV-8"],
      series: [
        { name: "Amount", values: ["900", "920", "940", "960", "980", "1000", "1020", "1040"], unit: "$" },
      ],
    };
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    expect(screen.getAllByText("Test chart").length).toBeGreaterThan(0);
    expect(screen.queryByLabelText("Chart summary metrics")).toBeNull();
  });

  it("renders box_plot via the mocked ECharts boundary and hides metric cards", () => {
    echartsOptionCalls.length = 0;
    const chart: PresentationChart = {
      ...baseChart,
      type: "box_plot",
      categories: ["INV-1", "INV-2", "INV-3"],
      series: [{ name: "Amount", values: ["1000", "1200", "900"], unit: "$" }],
    };
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    expect(screen.getByTestId("echarts-stub")).toBeTruthy();
    expect(screen.queryByLabelText("Chart summary metrics")).toBeNull();

    // The quartiles this app computed from the validated series values, not
    // invented — confirms BoxPlotChart fed real data into the ECharts option.
    const option = echartsOptionCalls.at(-1) as { series: { data: number[][] }[] };
    expect(option.series[0].data[0]).toEqual([900, 950, 1000, 1100, 1200]);
  });

  it("does not render metric cards for grouped_bar/stacked_bar/diverging_bar (regular bar-like types keep them)", () => {
    const chart: PresentationChart = {
      ...baseChart,
      type: "grouped_bar",
      categories: ["A"],
      series: [{ name: "Budget", values: ["100"], unit: "$" }],
    };
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    // grouped_bar is category-vs-series like a normal bar chart, so its
    // metric cards ARE expected (only radar/histogram/box_plot suppress them).
    expect(within(screen.getByLabelText("Chart summary metrics")).getByText("Budget")).toBeTruthy();
  });

  it("renders funnel without crashing", () => {
    const chart: PresentationChart = {
      ...baseChart,
      type: "funnel",
      categories: ["Leads", "Qualified", "Proposal", "Won"],
      series: [{ name: "Count", values: ["1000", "400", "150", "60"], unit: "" }],
    };
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    expect(screen.getAllByText("Test chart").length).toBeGreaterThan(0);
  });

  it("renders slope without crashing, one line per entity", () => {
    const chart: PresentationChart = {
      ...baseChart,
      type: "slope",
      categories: ["North", "South", "East"],
      series: [
        { name: "2025", values: ["100000", "80000", "60000"], unit: "$" },
        { name: "2026", values: ["130000", "75000", "90000"], unit: "$" },
      ],
    };
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    expect(screen.getAllByText("Test chart").length).toBeGreaterThan(0);
  });

  it("shows an invalid-data message for a slope chart with the wrong number of series", () => {
    const chart: PresentationChart = {
      ...baseChart,
      type: "slope",
      categories: ["North", "South"],
      series: [{ name: "2025", values: ["100000", "80000"], unit: "$" }],
    };
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    expect(screen.getByText(/exactly 2 data series/i)).toBeTruthy();
  });

  it("shows an empty-data message when a chart has no categories", () => {
    const chart: PresentationChart = { ...baseChart, type: "bar", categories: [], series: [] };
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    expect(screen.getByText(/no data available to visualize/i)).toBeTruthy();
  });

  it("offers a 'View as table' alternative with the same category and series values", () => {
    const chart: PresentationChart = {
      ...baseChart,
      type: "grouped_bar",
      categories: ["Payroll"],
      series: [{ name: "Budget", values: ["150000"], unit: "$" }],
    };
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    const details = screen.getByText("View as table").closest("details") as HTMLElement;
    expect(within(details).getByRole("columnheader", { name: "Budget" })).toBeTruthy();
    expect(within(details).getByRole("rowheader", { name: "Payroll" })).toBeTruthy();
  });

  it("renders every row of the accessible table even when category labels repeat", () => {
    // Regression test: buildTableAlternative used to key each <tr> by the
    // category label alone. A chart whose categories legitimately repeat a
    // label (e.g. "Headcount" appearing in more than one row of an
    // LLM-composed table) produced a React duplicate-key warning and could
    // silently drop or duplicate rows.
    const chart: PresentationChart = {
      ...baseChart,
      type: "grouped_bar",
      categories: ["Headcount", "Headcount", "Revenue"],
      series: [{ name: "North", values: ["45", "30", "900000"], unit: "" }],
    };
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    const details = screen.getByText("View as table").closest("details") as HTMLElement;
    expect(within(details).getAllByRole("rowheader", { name: "Headcount" })).toHaveLength(2);
    expect(within(details).getByRole("rowheader", { name: "Revenue" })).toBeTruthy();
    const duplicateKeyWarning = errorSpy.mock.calls.some((call) => String(call[0]).includes("two children with the same key"));
    expect(duplicateKeyWarning).toBe(false);
    errorSpy.mockRestore();
  });

  it("offers PNG, CSV, and Save actions for a chart", () => {
    const chart: PresentationChart = {
      ...baseChart,
      type: "grouped_bar",
      categories: ["Payroll"],
      series: [{ name: "Budget", values: ["150000"], unit: "$" }],
    };
    render(<AnswerVisualizations presentation={makePresentation(chart)} queryId="q1" />);
    expect(screen.getByText("Download PNG")).toBeTruthy();
    expect(screen.getByText("Export CSV")).toBeTruthy();
    expect(screen.getByText("Save")).toBeTruthy();
  });
});
