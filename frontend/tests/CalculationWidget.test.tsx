import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { CalculationWidget as CalculationWidgetData } from "@/lib/api";
import { buildWaterfallOption } from "@/components/CalculationWidget";

// jsdom has no canvas 2D context, so echarts-for-react's real render throws
// there — same boundary-mock pattern as AnswerVisualizations.test.tsx's
// box_plot test. Asserts on the ECharts option this app builds, not pixels.
const echartsOptionCalls: unknown[] = [];
vi.mock("echarts-for-react", () => ({
  default: (props: { option: { series: { name: string; data: number[] }[] } }) => {
    echartsOptionCalls.push(props.option);
    return <div data-testid="echarts-stub" />;
  },
}));

const { CalculationWidget } = await import("@/components/CalculationWidget");

describe("buildWaterfallOption", () => {
  it("computes running-total bases so relative deltas float at the right height (gross profit: Revenue - COGS = Gross profit)", () => {
    // Matches backend/app/domains/calculation/widget.py's _comparison_widget
    // convention: first point absolute, last point's y is the real computed
    // total, middle points already negated by the frontend to mean "subtract".
    const chartData = [
      { x: "Revenue", y: 500000 },
      { x: "COGS", y: 320000 },
      { x: "Gross profit", y: 180000 },
    ];
    const option = buildWaterfallOption(chartData);
    const seriesByName = Object.fromEntries(option.series.map((s) => [s.name, s.data]));

    expect(seriesByName["Start / total"]).toEqual([500000, 0, 180000]);
    // COGS is a decrease: base sits at the post-subtraction level (180000),
    // and the visible red segment spans up to the pre-subtraction level.
    expect(seriesByName["Base"]).toEqual([0, 180000, 0]);
    expect(seriesByName["Decrease"]).toEqual([0, 320000, 0]);
    expect(seriesByName["Increase"]).toEqual([0, 0, 0]);
  });

  it("handles a three-input bridge (operating profit: Revenue - COGS - OpEx)", () => {
    const chartData = [
      { x: "Revenue", y: 500000 },
      { x: "COGS", y: 320000 },
      { x: "OpEx", y: 90000 },
      { x: "Operating profit", y: 90000 },
    ];
    const option = buildWaterfallOption(chartData);
    const seriesByName = Object.fromEntries(option.series.map((s) => [s.name, s.data]));

    expect(seriesByName["Start / total"]).toEqual([500000, 0, 0, 90000]);
    // Running total after COGS: 500000 - 320000 = 180000; after OpEx: 90000.
    expect(seriesByName["Base"]).toEqual([0, 180000, 90000, 0]);
    expect(seriesByName["Decrease"]).toEqual([0, 320000, 90000, 0]);
  });
});

describe("CalculationWidget waterfall rendering", () => {
  const widget: CalculationWidgetData = {
    formula_id: "accounting.gross_profit.v1", formula_name: "Gross profit", formula_display: "GP = Revenue - COGS",
    methodology_reference: "ref", inputs: [], output_label: "Gross profit", output_value: "180000", output_unit: "USD",
    chart_type: "waterfall", chart_label: "Revenue to gross-profit bridge", chart_x_label: "", chart_y_label: "Amount ($)",
    chart_points: [
      { x: "Revenue", y: "500000" },
      { x: "COGS", y: "320000" },
      { x: "Gross profit", y: "180000" },
    ],
    calculation_id: "calc-waterfall-1",
  };

  it("renders through the ECharts boundary, not the removed Plotly path", () => {
    echartsOptionCalls.length = 0;
    render(<CalculationWidget data={widget} />);
    expect(screen.getByTestId("echarts-stub")).toBeTruthy();
    const option = echartsOptionCalls.at(-1) as { series: { name: string }[] };
    expect(option.series.map((s) => s.name)).toEqual(["Base", "Start / total", "Increase", "Decrease"]);
  });
});
