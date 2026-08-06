import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { AnswerPresentation, PresentationChart } from "@/lib/api";

vi.mock("echarts-for-react", () => ({
  default: () => <div data-testid="echarts-stub" />,
}));

const recordVisualizationEventCalls: unknown[] = [];
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    getAuthToken: () => "test-token",
    recordVisualizationEvent: vi.fn(async (_token: string, payload: unknown) => {
      recordVisualizationEventCalls.push(payload);
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
    selection_source: "personalized",
    schema_version: "1.0",
    ...overrides,
  };
}

beforeEach(() => {
  recordVisualizationEventCalls.length = 0;
});

describe("Dynamic Visualization Selection v10 — personalization label", () => {
  it("shows the label when personalization actually affected the selection", () => {
    const chart = makeChart({ personalization_enabled: true, personalization_affected_selection: true });
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    expect(screen.getByText("Recommended based on your visualization preferences")).toBeTruthy();
  });

  it("does not show the label when personalization is enabled but did not change the selection", () => {
    const chart = makeChart({ personalization_enabled: true, personalization_affected_selection: false, selection_source: "deterministic_default" });
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    expect(screen.queryByText("Recommended based on your visualization preferences")).toBeNull();
  });

  it("does not show the label for an explicit user request even if personalization is enabled", () => {
    const chart = makeChart({ personalization_enabled: true, personalization_affected_selection: false, selection_source: "explicit_user_request" });
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    expect(screen.queryByText("Recommended based on your visualization preferences")).toBeNull();
  });

  it("hides the label after the user manually switches to a different view", () => {
    const chart = makeChart({ personalization_enabled: true, personalization_affected_selection: true });
    render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    expect(screen.getByText("Recommended based on your visualization preferences")).toBeTruthy();
    const select = screen.getByLabelText("View") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "dumbbell" } });
    expect(screen.queryByText("Recommended based on your visualization preferences")).toBeNull();
  });

  it("never renders the raw personalization model version or confidence band as visible identifiers of prohibited content", () => {
    const chart = makeChart({
      personalization_enabled: true, personalization_affected_selection: true,
      personalization_model_version: "personalization-1.0", personalization_confidence_band: "high",
    });
    const { container } = render(<AnswerVisualizations presentation={makePresentation(chart)} />);
    // The label itself is fine to show; raw diagnostic fields must not leak into the DOM.
    expect(container.innerHTML).not.toContain("personalization-1.0");
  });
});

describe("Dynamic Visualization Selection v10 — table-opened telemetry", () => {
  it("fires table_view_opened when the accessible table is expanded", async () => {
    const chart = makeChart();
    render(<AnswerVisualizations presentation={makePresentation(chart)} queryId="q-table-1" conversationId="conv-1" />);
    fireEvent.click(screen.getByText("View as table"));
    await vi.waitFor(() => {
      const events = (recordVisualizationEventCalls as Record<string, unknown>[]).filter((e) => e.event_name === "table_view_opened");
      expect(events).toHaveLength(1);
    });
  });

  it("does not fire again when the table is collapsed", async () => {
    const chart = makeChart();
    render(<AnswerVisualizations presentation={makePresentation(chart)} queryId="q-table-2" conversationId="conv-1" />);
    fireEvent.click(screen.getByText("View as table")); // open
    await vi.waitFor(() => {
      const opened = (recordVisualizationEventCalls as Record<string, unknown>[]).filter((e) => e.event_name === "table_view_opened");
      expect(opened).toHaveLength(1);
    });
    fireEvent.click(screen.getByText("View as table")); // close
    await new Promise((resolve) => setTimeout(resolve, 10));
    const opened = (recordVisualizationEventCalls as Record<string, unknown>[]).filter((e) => e.event_name === "table_view_opened");
    expect(opened).toHaveLength(1);
  });
});
