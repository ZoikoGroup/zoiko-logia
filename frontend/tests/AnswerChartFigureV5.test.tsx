import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import type { AnswerPresentation, PresentationChart } from "@/lib/api";

const recordVisualizationEventCalls: unknown[] = [];
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    getAuthToken: () => "test-token",
    createSavedVisualization: vi.fn(async () => ({ id: "saved-1" })),
    recordVisualizationEvent: vi.fn(async (_token: string, payload: unknown) => {
      recordVisualizationEventCalls.push(payload);
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

const temporalChart: PresentationChart = {
  chart_id: "t1", title: "Quarterly revenue", unit: "$", domain: "accounting", summary_mode: "latest",
  type: "area",
  categories: ["Q1", "Q2", "Q3", "Q4"],
  series: [{ name: "Revenue", values: ["100000", "120000", "115000", "140000"], unit: "$" }],
  alternatives: ["line"],
  original_chart_type: "area",
  analytical_intent: "trend",
  selection_source: "deterministic_default",
  schema_version: "1.0",
};

const compositionChart: PresentationChart = {
  chart_id: "c1", title: "Tax breakdown", unit: "$", domain: "tax", summary_mode: "total",
  type: "donut",
  categories: ["Current tax", "Deferred tax", "Withholding tax"],
  series: [{ name: "Amount", values: ["80000", "20000", "12000"], unit: "$" }],
  alternatives: ["composition_bar"],
  original_chart_type: "donut",
  analytical_intent: "composition",
  selection_source: "deterministic_default",
  schema_version: "1.0",
};

const groupedCompositionChart: PresentationChart = {
  chart_id: "g1", title: "Revenue and cost composition", unit: "$", domain: "general", summary_mode: "total",
  type: "percentage_stacked_bar",
  categories: ["Widgets", "Gadgets", "Gizmos"],
  series: [
    { name: "Revenue", values: ["100000", "80000", "60000"], unit: "$" },
    { name: "Cost", values: ["60000", "50000", "40000"], unit: "$" },
  ],
  alternatives: ["stacked_bar"],
  original_chart_type: "percentage_stacked_bar",
  analytical_intent: "composition",
  selection_source: "deterministic_default",
  schema_version: "1.0",
};

describe("Dynamic Visualization Selection v5 — temporal (line ↔ area)", () => {
  it("offers line as an alternative to the area default and switches without a new fetch", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(<AnswerVisualizations presentation={makePresentation(temporalChart)} />);
    const select = screen.getByLabelText("View") as HTMLSelectElement;
    const optionLabels = Array.from(select.options).map((option) => option.textContent);
    expect(optionLabels).toEqual(["Area (recommended)", "Line"]);
    fireEvent.change(select, { target: { value: "line" } });
    expect(select.value).toBe("line");
    const askCalls = fetchSpy.mock.calls.filter(([url]) => String(url).includes("/orchestration/ask"));
    expect(askCalls).toHaveLength(0);
    fetchSpy.mockRestore();
  });

  it("preserves title and accessible summary across a line/area switch", () => {
    render(<AnswerVisualizations presentation={makePresentation(temporalChart)} />);
    const select = screen.getByLabelText("View") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "line" } });
    expect(screen.getAllByText("Quarterly revenue").length).toBeGreaterThan(0);
  });

  it("switching from area to line does not change the underlying series values shown in View as table", () => {
    render(<AnswerVisualizations presentation={makePresentation(temporalChart)} />);
    const select = screen.getByLabelText("View") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "line" } });
    const details = screen.getByText("View as table").closest("details") as HTMLElement;
    expect(within(details).getByText("$120,000.00")).toBeTruthy();
  });
});

describe("Dynamic Visualization Selection v5 — composition (donut ↔ composition_bar)", () => {
  it("offers composition_bar as an alternative to the donut default", () => {
    render(<AnswerVisualizations presentation={makePresentation(compositionChart)} />);
    const select = screen.getByLabelText("View") as HTMLSelectElement;
    const optionLabels = Array.from(select.options).map((option) => option.textContent);
    expect(optionLabels).toEqual(["Donut (recommended)", "Composition Bar"]);
  });

  it("renders composition_bar without crashing and keeps the table alternative intact", () => {
    render(<AnswerVisualizations presentation={makePresentation(compositionChart)} />);
    const select = screen.getByLabelText("View") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "composition_bar" } });
    expect(select.value).toBe("composition_bar");
    const details = screen.getByText("View as table").closest("details") as HTMLElement;
    expect(within(details).getByText("$80,000.00")).toBeTruthy();
  });

  it("switching back from composition_bar to donut works both directions", () => {
    render(<AnswerVisualizations presentation={makePresentation(compositionChart)} />);
    const select = screen.getByLabelText("View") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "composition_bar" } });
    fireEvent.change(select, { target: { value: "donut" } });
    expect(select.value).toBe("donut");
  });
});

describe("Dynamic Visualization Selection v5 — grouped composition (stacked_bar ↔ percentage_stacked_bar)", () => {
  it("still offers stacked_bar as an alternative after the family reclassification", () => {
    render(<AnswerVisualizations presentation={makePresentation(groupedCompositionChart)} />);
    const select = screen.getByLabelText("View") as HTMLSelectElement;
    const optionLabels = Array.from(select.options).map((option) => option.textContent);
    expect(optionLabels).toEqual(["Percentage Stacked Bar (recommended)", "Stacked Bar"]);
  });
});

describe("Dynamic Visualization Selection v5 — CSV export preserves raw values", () => {
  it("exports the original series values for percentage_stacked_bar, not display percentages", async () => {
    const { exportPresentationChartCsv } = await import("@/lib/export/exportPresentationChartCsv");
    const beforeCount = blobs.length;
    exportPresentationChartCsv(groupedCompositionChart);
    expect(blobs.length).toBe(beforeCount + 1);
    const text = await blobs[blobs.length - 1].text();
    expect(text).toContain("Revenue ($)");
    expect(text).toContain("Cost ($)");
    // Raw dollar values, never the 0-100 display percentages
    // buildPercentageStackedData computes for on-screen rendering only.
    expect(text).toContain("Widgets,100000,60000");
    expect(text).not.toMatch(/\d+%/);
  });
});

describe("Dynamic Visualization Selection v5 — telemetry carries chart_family", () => {
  it("includes chart_family on a temporal view-switch event", async () => {
    recordVisualizationEventCalls.length = 0;
    render(<AnswerVisualizations presentation={makePresentation({ ...temporalChart, chart_id: "t-telemetry" })} queryId="q1" conversationId="conv-1" />);
    const select = screen.getByLabelText("View") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "line" } });
    await vi.waitFor(() => expect(recordVisualizationEventCalls.length).toBeGreaterThan(0));
    const event = recordVisualizationEventCalls[0] as Record<string, unknown>;
    expect(event.chart_family).toBe("temporal_series");
  });

  it("includes chart_family on a composition save event", async () => {
    recordVisualizationEventCalls.length = 0;
    render(<AnswerVisualizations presentation={makePresentation({ ...compositionChart, chart_id: "c-telemetry" })} queryId="q1" />);
    fireEvent.click(screen.getByText("Save"));
    await vi.waitFor(() => {
      const events = (recordVisualizationEventCalls as Record<string, unknown>[]).filter((e) => e.event_name === "visualization_saved");
      expect(events).toHaveLength(1);
    });
    const saveEvent = (recordVisualizationEventCalls as Record<string, unknown>[]).find((e) => e.event_name === "visualization_saved");
    expect(saveEvent?.chart_family).toBe("single_total_composition");
    expect(saveEvent?.active_chart_type).toBe("donut");
    expect(saveEvent?.original_chart_type).toBe("donut");
    expect(saveEvent?.schema_version).toBe("1.0");
  });
});

describe("Dynamic Visualization Selection v5 — legacy payload compatibility", () => {
  it("renders a pre-v5 area chart payload (no alternatives) unchanged, with no View selector", () => {
    const legacyChart = {
      chart_id: "legacy-area", title: "Legacy revenue", unit: "$", domain: "general" as const, summary_mode: "latest" as const,
      type: "area" as const,
      categories: ["Q1", "Q2"],
      series: [{ name: "Revenue", values: ["100", "120"], unit: "$" }],
    };
    render(<AnswerVisualizations presentation={makePresentation(legacyChart as PresentationChart)} />);
    expect(screen.getAllByText("Legacy revenue").length).toBeGreaterThan(0);
    expect(screen.queryByLabelText("View")).toBeNull();
  });

  it("renders a pre-v5 donut chart payload (no alternatives) unchanged, with no View selector", () => {
    const legacyChart = {
      chart_id: "legacy-donut", title: "Legacy breakdown", unit: "$", domain: "general" as const, summary_mode: "total" as const,
      type: "donut" as const,
      categories: ["A", "B"],
      series: [{ name: "Amount", values: ["10", "20"], unit: "$" }],
    };
    render(<AnswerVisualizations presentation={makePresentation(legacyChart as PresentationChart)} />);
    expect(screen.getAllByText("Legacy breakdown").length).toBeGreaterThan(0);
    expect(screen.queryByLabelText("View")).toBeNull();
  });
});
