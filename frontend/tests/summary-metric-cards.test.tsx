import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { SummaryMetricCards } from "@/components/visualization/charts/SummaryMetricCards";
import type { VisualizationSpec } from "@/lib/api";

function spec(values: Record<string, unknown>): VisualizationSpec {
  return { type: "BAR", series: [], unit: undefined, ...values } as unknown as VisualizationSpec;
}

describe("SummaryMetricCards", () => {
  it("shows a waterfall's start and its end result, not its last step", () => {
    // QA D03: "Latest −300 Income tax expense" stood over a bridge ending at 900.
    const data = [["Revenue", 10000], ["Cost of goods sold", -6200], ["Expenses", -2100], ["Depreciation", -400],
      ["Interest", -100], ["Income tax expense", -300]].map(([x, y]) => ({ x, y }));
    render(<SummaryMetricCards viz={spec({ variant: "WATERFALL_CHART", data })} />);
    expect(screen.getByText("Start")).toBeTruthy();
    expect(screen.getByText("End result")).toBeTruthy();
    expect(screen.getByText("900")).toBeTruthy();
    expect(screen.queryByText("-300")).toBeNull();
  });

  it("keeps first and latest for an ordinary series", () => {
    const data = [{ x: "Q1", y: 2100 }, { x: "Q4", y: 3100 }];
    render(<SummaryMetricCards viz={spec({ data })} />);
    expect(screen.getByText("First")).toBeTruthy();
    expect(screen.getByText("Latest")).toBeTruthy();
  });
});
