import { describe, expect, it } from "vitest";
import type { VisualizationSpec } from "@/lib/api";
import { validViewAlternatives } from "@/components/visualization/charts/engineRouting";

describe("valid chart views preserve the dataset and axis meaning", () => {
  const spec = (axis: string, labels = ["2025-01", "2025-02", "2025-03"]) => ({
    type: "BAR", encoding: { x: { type: axis } },
    data: labels.map((x, i) => ({ x, y: i + 1 })),
  }) as unknown as VisualizationSpec;

  it("offers a line only for an ordered temporal series", () => {
    const source = spec("temporal");
    const before = JSON.stringify(source);
    expect(validViewAlternatives(source)).toEqual(["LINE"]);
    const switched = { ...source, type: "LINE" };
    expect(switched.data).toBe(source.data);
    expect(JSON.stringify(source)).toBe(before);
  });
  it("does not connect accounting categories or unordered/duplicate dates", () => {
    expect(validViewAlternatives(spec("nominal"))).toEqual([]);
    expect(validViewAlternatives({ ...spec("temporal"), variant: "WATERFALL_CHART" })).toEqual([]);
    expect(validViewAlternatives(spec("temporal", ["2025-02", "2025-01", "2025-03"]))).toEqual([]);
    expect(validViewAlternatives(spec("temporal", ["2025-01", "2025-01", "2025-03"]))).toEqual([]);
    expect(validViewAlternatives(spec("temporal", ["2025-01", "2025-02"]))).toEqual([]);
  });
});
