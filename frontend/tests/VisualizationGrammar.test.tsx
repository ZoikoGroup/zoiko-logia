import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AnswerPresentation, PresentationChart } from "@/lib/api";

const optionCalls: Array<Record<string, unknown>> = [];
vi.mock("echarts-for-react", () => ({
  default: (props: { option: Record<string, unknown> }) => {
    optionCalls.push(props.option);
    return <div data-testid="grammar-chart" />;
  },
}));

const { AnswerVisualizations } = await import("@/components/AnswerVisualizations");

function presentation(chart: PresentationChart): AnswerPresentation {
  return { layout: "data_visualization", table_count: 1, has_steps: false, charts: [chart], guides: [], graphs: [], sections: [], follow_up_questions: [] };
}

const chart: PresentationChart = {
  chart_id: "grammar-1", type: "bar", title: "Revenue and margin",
  alternatives: ["grouped_bar"],
  categories: ["North", "South", "West"], unit: "", domain: "general", summary_mode: "total",
  series: [
    { name: "Revenue", values: ["1000", "1200", "900"], unit: "USD" },
    { name: "Margin", values: ["20", "22", "18"], unit: "%" },
  ],
  grammar: {
    version: "1.0", renderer: "echarts", composition: "layer", fallback_chart_type: "bar",
    layers: [
      { mark: "bar", series_index: 0, axis: "primary" },
      { mark: "line", series_index: 1, axis: "secondary" },
    ],
  },
};

describe("governed visualization grammar", () => {
  beforeEach(() => optionCalls.splice(0));

  it("renders validated layers through ECharts and keeps the accessible table", () => {
    render(<AnswerVisualizations presentation={presentation(chart)} />);
    expect(screen.getByTestId("grammar-chart")).toBeInTheDocument();
    const option = optionCalls.at(-1) as { series: Array<{ type: string; yAxisIndex: number }> };
    expect(option.series.map((series) => series.type)).toEqual(["bar", "line"]);
    expect(option.series[1].yAxisIndex).toBe(1);
    expect(screen.getByText("View as table")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Layered Chart (recommended)" })).toBeInTheDocument();
  });

  it("does not execute or interpret labels as code", () => {
    const hostile = { ...chart, categories: ["<script>alert(1)</script>", "South", "West"] };
    render(<AnswerVisualizations presentation={presentation(hostile)} />);
    expect(document.querySelector("script")).toBeNull();
    expect(screen.getByText("<script>alert(1)</script>")).toBeInTheDocument();
  });
});
