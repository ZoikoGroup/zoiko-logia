import { describe, expect, it } from "vitest";
import { buildChartOption, type ChartSpec } from "@/components/AnswerRenderer";

type Labelled = { label?: { formatter?: (p: unknown) => string } };

describe("chart value labels", () => {
  it("states each pie slice's share to two decimals (QA case D05)", () => {
    const option = buildChartOption({ type: "pie", data: [{ name: "Q1", value: 2100 }] } as ChartSpec);
    const [series] = option.series as Labelled[];
    expect(series.label?.formatter?.({ name: "Q1", percent: 21 })).toBe("Q1: 21.00%");
  });

  it("prints bar values with thousands separators (QA case D01)", () => {
    const option = buildChartOption({ type: "bar", categories: ["Q4"], series: [{ name: "Revenue", data: [3100] }] } as ChartSpec);
    const [series] = option.series as Labelled[];
    expect(series.label?.formatter?.({ value: 3100 })).toBe("3,100");
    expect(series.label?.formatter?.({ value: 1234567.891 })).toBe("1,234,567.89");
  });
});
