import { describe, expect, it } from "vitest";
import type { VisualizationSpec } from "@/lib/api";
import { checkChartValidity, normalizeVisualizationSpec } from "@/components/visualization/charts/chartValidity";

function runtimeSpec(values: Record<string, unknown>): VisualizationSpec {
  return values as unknown as VisualizationSpec;
}

describe("checkChartValidity", () => {
  it("accepts a legacy single-series line payload without the newer series field", () => {
    const viz = runtimeSpec({
      type: "LINE",
      data: [{ x: "2025-01", y: 1 }, { x: "2025-02", y: 2 }],
    });

    expect(checkChartValidity(viz)).toBe("OK");
  });

  it("reports an empty legacy line payload instead of throwing", () => {
    expect(checkChartValidity(runtimeSpec({ type: "LINE" }))).toBe("EMPTY");
  });

  it("normalizes every collection consumed by downstream renderers", () => {
    const normalized = normalizeVisualizationSpec(runtimeSpec({ type: "LINE" }));

    expect(normalized).toMatchObject({
      fallback_order: [], data: [], nodes: [], edges: [], cells: [], scatter: [],
      donut: [], candlestick: [], series: [], columns: [], rows: [], sources: [],
    });
  });

  it("validates a current multi-series line payload", () => {
    const points = [{ x: "2025-01", y: 1 }, { x: "2025-02", y: 2 }];
    const viz = runtimeSpec({
      type: "LINE",
      series: [{ name: "UK", data: points }, { name: "US", data: points }],
    });

    expect(checkChartValidity(viz)).toBe("OK");
  });

  it.each(["BAR", "HISTOGRAM", "SCATTER", "HEATMAP", "DONUT", "CANDLESTICK", "GROUPED_BAR", "TABLE", "EVIDENCE_GRAPH", "PROCESS_FLOW"])(
    "does not throw when a legacy %s payload omits its collection fields",
    (type) => {
      expect(() => checkChartValidity(runtimeSpec({ type }))).not.toThrow();
    },
  );
});
