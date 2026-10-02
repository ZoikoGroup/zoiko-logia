// @vitest-environment node
// ECharts' server-side SVG renderer needs no DOM; jsdom's missing canvas only
// adds noise. cssVar() falls back to the default palette without a window.
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import * as echarts from "echarts";
import { describe, expect, it } from "vitest";
import type { VisualizationSpec } from "@/lib/api";
import { buildExtraChartOption, extraChartKind } from "@/components/visualization/charts/extraCharts";

// Specs shaped exactly as the backend builds them (chart_tables.py and
// orchestrator.py), rendered through real ECharts server-side.
function spec(overrides: Partial<VisualizationSpec>): VisualizationSpec {
  return {
    version: "1.0", id: "viz", type: "TABLE", family: "STATISTICAL", renderer: "TABLE_ADAPTER",
    fallback_order: [], data: [], nodes: [], edges: [], interactive: false, cells: [], scatter: [],
    donut: [], candlestick: [], series: [], columns: [], rows: [], sources: [],
    ...overrides,
  } as VisualizationSpec;
}

const CASES: Array<[string, VisualizationSpec, string[]]> = [
  ["pareto", spec({
    capability_id: "spend_category_analysis", columns: ["Category", "Value", "Cumulative %"],
    rows: [
      { Category: "Payroll", Value: "180000", "Cumulative %": "64.3" },
      { Category: "Rent", Value: "55000", "Cumulative %": "83.9" },
      { Category: "IT", Value: "25000", "Cumulative %": "92.9" },
      { Category: "Travel", Value: "12000", "Cumulative %": "97.1" },
      { Category: "Other", Value: "8000", "Cumulative %": "100.0" },
    ],
  }), ["Payroll", "Cumulative %"]],
  ["funnel", spec({
    capability_id: "funnel_chart", columns: ["Stage", "Value"],
    rows: [
      { Stage: "Invoices issued", Value: "500" }, { Stage: "Reminders sent", Value: "320" },
      { Stage: "Disputes resolved", Value: "150" }, { Stage: "Paid", Value: "120" },
    ],
  }), ["Invoices issued", "Paid"]],
  ["stream", spec({
    capability_id: "stacked_area_chart", columns: ["Period", "Payroll", "Rent", "IT"],
    rows: [
      { Period: "2022", Payroll: "10", Rent: "5", IT: "2" },
      { Period: "2023", Payroll: "12", Rent: "6", IT: "3" },
      { Period: "2024", Payroll: "15", Rent: "6", IT: "5" },
    ],
  }), ["Payroll", "2023"]],
  ["bubble", spec({
    capability_id: "bubble_chart", columns: ["Item", "revenue", "margin", "volume"],
    rows: [
      { Item: "Product A", revenue: "100", margin: "20", volume: "50" },
      { Item: "Product B", revenue: "80", margin: "35", volume: "20" },
      { Item: "Product C", revenue: "60", margin: "15", volume: "70" },
    ],
  }), ["Product A", "revenue", "margin"]],
  ["parallel", spec({
    capability_id: "scenario_comparison", columns: ["Item", "margin", "growth", "debt", "liquidity"],
    rows: [
      { Item: "Acme", margin: "12", growth: "8", debt: "30", liquidity: "1.5" },
      { Item: "Beta", margin: "9", growth: "15", debt: "45", liquidity: "1.1" },
    ],
  }), ["Acme", "liquidity"]],
  ["sankey", spec({
    capability_id: "flow_of_funds", columns: ["From", "To", "Amount"],
    rows: [
      { From: "Revenue", To: "Operating Cash", Amount: "900" },
      { From: "Operating Cash", To: "Payroll", Amount: "400" },
      { From: "Operating Cash", To: "Tax", Amount: "150" },
      { From: "Operating Cash", To: "Retained", Amount: "350" },
    ],
  }), ["Revenue", "Operating Cash", "Retained"]],
  ["calendar", spec({
    capability_id: "calendar_heatmap", columns: ["Date", "Value"],
    rows: [
      { Date: "2026-01-05", Value: "12" }, { Date: "2026-01-06", Value: "30" },
      { Date: "2026-01-07", Value: "8" }, { Date: "2026-02-12", Value: "22" },
    ],
  }), ["Jan"]],
  ["sunburst", spec({
    type: "DONUT", renderer: "ECHARTS", capability_id: "sunburst_chart",
    donut: [
      { label: "Payroll / Sales", value: 20, is_estimated: false }, { label: "Payroll / Ops", value: 25, is_estimated: false },
      { label: "Rent / HQ", value: 20, is_estimated: false }, { label: "Rent / Branch", value: 10, is_estimated: false },
      { label: "IT", value: 25, is_estimated: false },
    ],
  }), ["Payroll", "Branch", "IT"]],
  ["bullet", spec({
    type: "GAUGE", renderer: "ECHARTS", capability_id: "bullet_chart",
    label: "revenue", value: 8_200_000, target: 10_000_000, target_label: "Target",
  }), ["revenue", "Target"]],
];

describe("typed-data ECharts charts", () => {
  it.each(CASES)("%s renders every supplied label", (name, viz, labels) => {
    expect(extraChartKind(viz)).toBe(name);
    const option = buildExtraChartOption(viz);
    expect(option).not.toBeNull();

    const chart = echarts.init(null, null, { renderer: "svg", ssr: true, width: 760, height: 360 });
    chart.setOption({ animation: false, ...option! });
    const svg = chart.renderToSVGString();
    chart.dispose();

    for (const label of labels) expect(svg).toContain(label);
    const outDir = process.env.EXTRA_CHART_SVG_DIR;
    if (outDir) writeFileSync(join(outDir, `${name}.svg`), svg);
  });

  it("leaves every other spec to the existing builders", () => {
    expect(extraChartKind(spec({ capability_id: "table_data_grid" }))).toBeNull();
    // A Pareto shown in another view is no longer drawn as a Pareto.
    expect(extraChartKind(spec({ capability_id: "spend_category_analysis", type: "BAR" }))).toBeNull();
    expect(buildExtraChartOption(spec({ type: "DONUT", capability_id: "pie_chart" }))).toBeNull();
  });
});
