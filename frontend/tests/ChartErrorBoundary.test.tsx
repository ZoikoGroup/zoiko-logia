import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

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

const { ChartErrorBoundary } = await import("@/components/ChartErrorBoundary");

function Bomb(): never {
  throw new Error("simulated render crash with a secret stack trace detail");
}

describe("ChartErrorBoundary", () => {
  it("renders the fallback UI instead of crashing the rest of the page", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ChartErrorBoundary title="Revenue chart">
        <Bomb />
      </ChartErrorBoundary>
    );
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByText("Revenue chart")).toBeTruthy();
    spy.mockRestore();
  });

  it("emits visualization_render_failed with only chart metadata, never the error message or stack", async () => {
    recordVisualizationEventCalls.length = 0;
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ChartErrorBoundary
        title="Revenue chart"
        telemetry={{
          conversationId: "conv-1", queryId: "q-1", analyticalIntent: "comparison",
          originalChartType: "grouped_bar", activeChartType: "dumbbell", selectionSource: "alternative_switch",
          renderer: "recharts", schemaVersion: "1.0",
        }}
      >
        <Bomb />
      </ChartErrorBoundary>
    );
    spy.mockRestore();

    await vi.waitFor(() => expect(recordVisualizationEventCalls.length).toBe(1));
    const payload = recordVisualizationEventCalls[0] as Record<string, unknown>;
    expect(payload.event_name).toBe("visualization_render_failed");
    expect(payload.active_chart_type).toBe("dumbbell");
    expect(payload.original_chart_type).toBe("grouped_bar");

    const serialized = JSON.stringify(payload);
    expect(serialized).not.toContain("simulated render crash");
    expect(serialized).not.toContain("secret stack trace");
    expect(serialized).not.toContain("Bomb");
    // No key on the payload carries the error/component stack at all.
    expect(Object.keys(payload)).not.toContain("error");
    expect(Object.keys(payload)).not.toContain("stack");
    expect(Object.keys(payload)).not.toContain("componentStack");
  });

  it("renders children normally when there is no error", () => {
    render(<ChartErrorBoundary title="Revenue chart"><div>real chart</div></ChartErrorBoundary>);
    expect(screen.getByText("real chart")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
