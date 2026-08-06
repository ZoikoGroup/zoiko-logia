import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { AnswerPresentation, PresentationChart } from "@/lib/api";

const echartsOptionCalls: unknown[] = [];
vi.mock("echarts-for-react", () => ({
  default: (props: { option: unknown }) => {
    echartsOptionCalls.push(props.option);
    return <div data-testid="echarts-stub" />;
  },
}));

let pngShouldSucceed = true;
vi.mock("@/lib/export/exportSvgElementPng", () => ({
  exportSvgElementPng: vi.fn(async () => pngShouldSucceed),
}));

let csvShouldThrow = false;
vi.mock("@/lib/export/exportPresentationChartCsv", () => ({
  exportPresentationChartCsv: vi.fn(() => {
    if (csvShouldThrow) throw new Error("simulated csv failure");
  }),
}));

let saveShouldSucceed = true;
const recordVisualizationEventCalls: unknown[] = [];
let telemetryShouldFail = false;

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    getAuthToken: () => "test-token",
    createSavedVisualization: vi.fn(async () => {
      if (!saveShouldSucceed) throw new Error("simulated save failure");
      return { id: "saved-1" };
    }),
    recordVisualizationEvent: vi.fn(async (_token: string, payload: unknown) => {
      recordVisualizationEventCalls.push(payload);
      if (telemetryShouldFail) throw new Error("simulated telemetry outage");
    }),
  };
});

const { AnswerVisualizations } = await import("@/components/AnswerVisualizations");

function makePresentation(chart: PresentationChart): AnswerPresentation {
  return {
    layout: "data_visualization", table_count: 1, has_steps: false,
    charts: [chart], guides: [], graphs: [], sections: [], follow_up_questions: [],
  };
}

function makeChart(overrides: Partial<PresentationChart> = {}): PresentationChart {
  return {
    chart_id: `c-${Math.random().toString(36).slice(2)}`, title: "Department comparison", unit: "$",
    domain: "general", summary_mode: "total", type: "grouped_bar",
    categories: ["Payroll", "Technology"],
    series: [
      { name: "Budget", values: ["150000", "60000"], unit: "$" },
      { name: "Actual", values: ["158000", "72000"], unit: "$" },
    ],
    alternatives: ["dumbbell", "diverging_bar"],
    original_chart_type: "grouped_bar",
    analytical_intent: "comparison",
    selection_source: "deterministic_default",
    schema_version: "1.0",
    ...overrides,
  };
}

beforeEach(() => {
  pngShouldSucceed = true;
  csvShouldThrow = false;
  saveShouldSucceed = true;
  telemetryShouldFail = false;
  recordVisualizationEventCalls.length = 0;
});

describe("Dynamic Visualization Selection v4 — telemetry emission", () => {
  it("fires alternative_view_selected once after a successful switch", async () => {
    const chart = makeChart();
    render(<AnswerVisualizations presentation={makePresentation(chart)} queryId="q-switch-1" conversationId="conv-1" />);
    const select = screen.getByLabelText("View") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "dumbbell" } });

    await vi.waitFor(() => expect(recordVisualizationEventCalls.length).toBeGreaterThan(0));
    const events = recordVisualizationEventCalls as Record<string, unknown>[];
    const switchEvents = events.filter((e) => e.event_name === "alternative_view_selected");
    expect(switchEvents).toHaveLength(1);
    expect(switchEvents[0].active_chart_type).toBe("dumbbell");
    expect(switchEvents[0].selection_source).toBe("alternative_switch");
    expect(switchEvents[0].conversation_id).toBe("conv-1");
  });

  it("does not re-fire when the same value is re-selected (dedup / no-op guard)", async () => {
    const chart = makeChart();
    render(<AnswerVisualizations presentation={makePresentation(chart)} queryId="q-switch-2" conversationId="conv-1" />);
    const select = screen.getByLabelText("View") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "grouped_bar" } }); // already the active value
    await new Promise((resolve) => setTimeout(resolve, 10));
    const switchEvents = (recordVisualizationEventCalls as Record<string, unknown>[]).filter((e) => e.event_name === "alternative_view_selected");
    expect(switchEvents).toHaveLength(0);
  });

  it("PNG export telemetry fires only after a successful export", async () => {
    pngShouldSucceed = true;
    const chart = makeChart({ chart_id: "png-success" });
    render(<AnswerVisualizations presentation={makePresentation(chart)} queryId="q-png-1" />);
    fireEvent.click(screen.getByText("Download PNG"));
    await vi.waitFor(() => {
      const events = (recordVisualizationEventCalls as Record<string, unknown>[]).filter((e) => e.event_name === "visualization_exported_png");
      expect(events).toHaveLength(1);
    });
  });

  it("PNG export failure reports no telemetry", async () => {
    pngShouldSucceed = false;
    const chart = makeChart({ chart_id: "png-fail" });
    render(<AnswerVisualizations presentation={makePresentation(chart)} queryId="q-png-2" />);
    fireEvent.click(screen.getByText("Download PNG"));
    await vi.waitFor(() => expect(screen.getByText(/failed/i)).toBeTruthy());
    const events = (recordVisualizationEventCalls as Record<string, unknown>[]).filter((e) => e.event_name === "visualization_exported_png");
    expect(events).toHaveLength(0);
  });

  it("CSV export telemetry fires only after a successful export", async () => {
    csvShouldThrow = false;
    const chart = makeChart({ chart_id: "csv-success" });
    render(<AnswerVisualizations presentation={makePresentation(chart)} queryId="q-csv-1" />);
    fireEvent.click(screen.getByText("Export CSV"));
    await vi.waitFor(() => {
      const events = (recordVisualizationEventCalls as Record<string, unknown>[]).filter((e) => e.event_name === "visualization_exported_csv");
      expect(events).toHaveLength(1);
    });
  });

  it("CSV export failure reports no telemetry", async () => {
    csvShouldThrow = true;
    const chart = makeChart({ chart_id: "csv-fail" });
    render(<AnswerVisualizations presentation={makePresentation(chart)} queryId="q-csv-2" />);
    fireEvent.click(screen.getByText("Export CSV"));
    await vi.waitFor(() => expect(screen.getByText(/failed/i)).toBeTruthy());
    const events = (recordVisualizationEventCalls as Record<string, unknown>[]).filter((e) => e.event_name === "visualization_exported_csv");
    expect(events).toHaveLength(0);
  });

  it("Save telemetry fires only after a successful save", async () => {
    saveShouldSucceed = true;
    const chart = makeChart({ chart_id: "save-success" });
    render(<AnswerVisualizations presentation={makePresentation(chart)} queryId="q-save-1" />);
    fireEvent.click(screen.getByText("Save"));
    await vi.waitFor(() => {
      const events = (recordVisualizationEventCalls as Record<string, unknown>[]).filter((e) => e.event_name === "visualization_saved");
      expect(events).toHaveLength(1);
    });
  });

  it("Save failure reports no telemetry", async () => {
    saveShouldSucceed = false;
    const chart = makeChart({ chart_id: "save-fail" });
    render(<AnswerVisualizations presentation={makePresentation(chart)} queryId="q-save-2" />);
    fireEvent.click(screen.getByText("Save"));
    await vi.waitFor(() => expect(screen.getByText(/failed/i)).toBeTruthy());
    const events = (recordVisualizationEventCalls as Record<string, unknown>[]).filter((e) => e.event_name === "visualization_saved");
    expect(events).toHaveLength(0);
  });

  it("a failing telemetry endpoint never blocks the save workflow itself", async () => {
    telemetryShouldFail = true;
    saveShouldSucceed = true;
    const chart = makeChart({ chart_id: "save-telemetry-down" });
    render(<AnswerVisualizations presentation={makePresentation(chart)} queryId="q-save-3" />);
    fireEvent.click(screen.getByText("Save"));
    // The save itself still reports success in the UI even though the
    // telemetry call (fired after) rejects.
    await vi.waitFor(() => expect(screen.getByText("Done")).toBeTruthy());
  });

  it("a failing telemetry endpoint never blocks a view switch", async () => {
    telemetryShouldFail = true;
    const chart = makeChart({ chart_id: "switch-telemetry-down" });
    render(<AnswerVisualizations presentation={makePresentation(chart)} queryId="q-switch-3" />);
    const select = screen.getByLabelText("View") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "diverging_bar" } });
    expect(select.value).toBe("diverging_bar");
  });

  it("telemetry payloads never contain query text, chart title, categories, or series values", async () => {
    const chart = makeChart({ chart_id: "privacy-check", title: "Super Secret Department Comparison" });
    render(<AnswerVisualizations presentation={makePresentation(chart)} queryId="q-privacy-1" conversationId="conv-privacy" />);
    const select = screen.getByLabelText("View") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "dumbbell" } });
    await vi.waitFor(() => expect(recordVisualizationEventCalls.length).toBeGreaterThan(0));

    for (const payload of recordVisualizationEventCalls) {
      const keys = Object.keys(payload as object);
      expect(keys).not.toContain("title");
      expect(keys).not.toContain("categories");
      expect(keys).not.toContain("series");
      expect(keys).not.toContain("query");
      expect(keys).not.toContain("answer");
      const serialized = JSON.stringify(payload);
      expect(serialized).not.toContain("Super Secret");
      expect(serialized).not.toContain("Payroll");
      expect(serialized).not.toContain("150000");
    }
  });
});
