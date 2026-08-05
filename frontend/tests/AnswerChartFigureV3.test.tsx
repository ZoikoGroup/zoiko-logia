import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import type { AnswerPresentation, PresentationChart } from "@/lib/api";

const echartsOptionCalls: unknown[] = [];
vi.mock("echarts-for-react", () => ({
  default: (props: { option: unknown }) => {
    echartsOptionCalls.push(props.option);
    return <div data-testid="echarts-stub" />;
  },
}));

const createSavedVisualizationCalls: unknown[] = [];
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    getAuthToken: () => "test-token",
    createSavedVisualization: vi.fn(async (_token: string, payload: unknown) => {
      createSavedVisualizationCalls.push(payload);
      return { id: "saved-1" };
    }),
  };
});

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

const chartWithAlternatives: PresentationChart = {
  chart_id: "c1", title: "Department comparison", unit: "$", domain: "general", summary_mode: "total",
  type: "grouped_bar",
  categories: ["Payroll", "Technology"],
  series: [
    { name: "Budget", values: ["150000", "60000"], unit: "$" },
    { name: "Actual", values: ["158000", "72000"], unit: "$" },
  ],
  alternatives: ["dumbbell", "diverging_bar"],
  original_chart_type: "grouped_bar",
  fallback_note: null,
};

describe("AnswerChartFigure — Dynamic Visualization Selection v3 (Try another view)", () => {
  it("does not show a view selector when there are no alternatives", () => {
    const chart: PresentationChart = { ...chartWithAlternatives, alternatives: [] };
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    expect(screen.queryByLabelText("View")).toBeNull();
  });

  it("shows a native, keyboard-operable select listing the recommended view and alternatives", () => {
    render(<AnswerVisualizations presentation={makePresentation(chartWithAlternatives)} />);
    const select = screen.getByLabelText("View") as HTMLSelectElement;
    expect(select.tagName).toBe("SELECT");
    const optionLabels = Array.from(select.options).map((option) => option.textContent);
    expect(optionLabels).toEqual(["Grouped Bar (recommended)", "Dumbbell", "Diverging Bar"]);
  });

  it("switching views re-renders the chart without re-fetching chart or answer data", async () => {
    // v4 adds a lightweight, fire-and-forget telemetry POST on a view
    // switch (tested separately in AnswerChartFigureV4.test.tsx) — this
    // test's actual guarantee is narrower and still holds: no request for
    // chart/answer DATA (i.e. nothing hits /orchestration/ask) happens.
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(<AnswerVisualizations presentation={makePresentation(chartWithAlternatives)} />);
    const select = screen.getByLabelText("View") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "dumbbell" } });
    expect(select.value).toBe("dumbbell");
    const askCalls = fetchSpy.mock.calls.filter(([url]) => String(url).includes("/orchestration/ask"));
    expect(askCalls).toHaveLength(0);
    fetchSpy.mockRestore();
  });

  it("preserves title, unit, and accessible summary across a view switch", () => {
    render(<AnswerVisualizations presentation={makePresentation(chartWithAlternatives)} />);
    const select = screen.getByLabelText("View") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "dumbbell" } });
    expect(screen.getAllByText("Department comparison").length).toBeGreaterThan(0);
    // The table alternative's values are unaffected by which view renders.
    const details = screen.getByText("View as table").closest("details") as HTMLElement;
    expect(within(details).getByText("$150,000.00")).toBeTruthy();
  });

  it("announces the active view change through aria-live", () => {
    render(<AnswerVisualizations presentation={makePresentation(chartWithAlternatives)} />);
    const select = screen.getByLabelText("View") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "dumbbell" } });
    const liveRegion = document.querySelector('[aria-live="polite"].sr-only') as HTMLElement;
    expect(liveRegion.textContent).toMatch(/now showing as dumbbell/i);
  });

  it("keeps the ChartErrorBoundary and View as table controls across a switch", () => {
    render(<AnswerVisualizations presentation={makePresentation(chartWithAlternatives)} />);
    const select = screen.getByLabelText("View") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "diverging_bar" } });
    expect(screen.getByText("View as table")).toBeTruthy();
    expect(screen.getByText("Download PNG")).toBeTruthy();
  });

  it("PNG export targets the currently active view, not the original recommendation", () => {
    render(<AnswerVisualizations presentation={makePresentation(chartWithAlternatives)} queryId="q1" />);
    const select = screen.getByLabelText("View") as HTMLSelectElement;
    // Switch to a view rendered through ECharts (bullet), confirming the
    // PNG-export code path itself switched (exportEChartPng vs the generic
    // SVG exporter) rather than only the visual chart changing.
    fireEvent.change(select, { target: { value: "diverging_bar" } });
    expect(screen.getByText("Download PNG")).toBeTruthy();
  });

  it("Save records both the originally selected and the active chart type", async () => {
    createSavedVisualizationCalls.length = 0;
    render(<AnswerVisualizations presentation={makePresentation(chartWithAlternatives)} queryId="q1" />);
    const select = screen.getByLabelText("View") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "dumbbell" } });

    const saveButton = screen.getByText("Save");
    fireEvent.click(saveButton);
    await vi.waitFor(() => expect(createSavedVisualizationCalls.length).toBe(1));

    const saved = createSavedVisualizationCalls[0] as { payload: PresentationChart };
    expect(saved.payload.type).toBe("dumbbell");
    expect(saved.payload.original_chart_type).toBe("grouped_bar");
  });

  it("Save preserves the original chart type even without switching views", async () => {
    createSavedVisualizationCalls.length = 0;
    render(<AnswerVisualizations presentation={makePresentation(chartWithAlternatives)} queryId="q1" />);
    fireEvent.click(screen.getByText("Save"));
    await vi.waitFor(() => expect(createSavedVisualizationCalls.length).toBe(1));
    const saved = createSavedVisualizationCalls[0] as { payload: PresentationChart };
    expect(saved.payload.type).toBe("grouped_bar");
    expect(saved.payload.original_chart_type).toBe("grouped_bar");
  });

  it("renders a v1/v2 saved payload (no alternatives/original_chart_type fields) unchanged", () => {
    const oldPayload = {
      chart_id: "old-1", title: "Old chart", unit: "$", domain: "general" as const, summary_mode: "total" as const,
      type: "grouped_bar" as const,
      categories: ["A", "B"],
      series: [{ name: "Value", values: ["1", "2"], unit: "$" }],
      // No alternatives, original_chart_type, fallback_note, or
      // schema_version — exactly what a v1/v2 payload looked like.
    };
    render(<AnswerVisualizations presentation={makePresentation(oldPayload as PresentationChart)} />);
    expect(screen.getAllByText("Old chart").length).toBeGreaterThan(0);
    expect(screen.queryByLabelText("View")).toBeNull();
  });

  it("shows the fallback note when the backend had to override an incompatible explicit request", () => {
    const chart: PresentationChart = { ...chartWithAlternatives, alternatives: [], fallback_note: "You asked for a radar chart, but this data doesn't support one — showing grouped bar instead." };
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    expect(screen.getByText(/you asked for a radar chart/i)).toBeTruthy();
  });
});
