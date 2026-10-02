import { cssVar } from "@/lib/css-var";
import type { VisualizationSpec } from "@/lib/api";
import { chartPalette } from "./palette";

/**
 * ECharts options for the charts drawn over data the user typed: Pareto,
 * funnel, streamgraph, bubble, parallel coordinates, Sankey and calendar
 * heatmap (all carried as TABLE rows — backend app/orchestration/
 * chart_tables.py), plus the sunburst (DONUT slices) and bullet chart (the
 * GAUGE's actual-versus-target pair).
 *
 * Keyed on capability_id AND the carrier type, so a spec shown in another
 * view is never drawn as one of these by mistake. Every figure comes from the
 * spec as sent; the only arithmetic is a Pareto's running share, which the
 * backend already puts in the table.
 */
export type ExtraChartKind =
  | "pareto" | "funnel" | "stream" | "bubble" | "parallel" | "sankey" | "calendar" | "sunburst" | "bullet";

const KINDS: Record<string, { kind: ExtraChartKind; carrier: VisualizationSpec["type"] }> = {
  spend_category_analysis: { kind: "pareto", carrier: "TABLE" },
  funnel_chart: { kind: "funnel", carrier: "TABLE" },
  stacked_area_chart: { kind: "stream", carrier: "TABLE" },
  bubble_chart: { kind: "bubble", carrier: "TABLE" },
  scenario_comparison: { kind: "parallel", carrier: "TABLE" },
  flow_of_funds: { kind: "sankey", carrier: "TABLE" },
  calendar_heatmap: { kind: "calendar", carrier: "TABLE" },
  sunburst_chart: { kind: "sunburst", carrier: "DONUT" },
  bullet_chart: { kind: "bullet", carrier: "GAUGE" },
};

export function extraChartKind(viz: VisualizationSpec): ExtraChartKind | null {
  const entry = KINDS[viz.capability_id ?? ""];
  return entry && entry.carrier === viz.type ? entry.kind : null;
}

function num(value: string | undefined): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function tokens() {
  return {
    ink: cssVar("--ink", "#17211f"),
    muted: cssVar("--muted", "#667673"),
    line: cssVar("--line", "#eef3f2"),
    panel: cssVar("--panel", "#ffffff"),
    soft: cssVar("--soft", "#f7faf8"),
    colors: chartPalette(),
  };
}

function valueColumns(viz: VisualizationSpec): string[] {
  return viz.columns.slice(1);
}

/** An axis range around every supplied value, with room at both ends so no
 * point sits on (or is clipped by) the frame. */
function paddedRange(values: number[], share = 0.15): { min: number; max: number } {
  const low = Math.min(...values);
  const high = Math.max(...values);
  const pad = (high - low || Math.abs(high) || 1) * share;
  return { min: low >= 0 && low - pad < 0 ? 0 : low - pad, max: high + pad };
}

// The padded ends are not figures anyone supplied, so they carry no label.
const INNER_LABELS = { showMinLabel: false, showMaxLabel: false };

function paretoOption(viz: VisualizationSpec) {
  const { muted, line, colors } = tokens();
  const [key] = viz.columns;
  return {
    color: colors,
    tooltip: { trigger: "axis" },
    legend: { bottom: 0, textStyle: { color: muted } },
    grid: { left: 8, right: 16, top: 24, bottom: 48, containLabel: true },
    xAxis: { type: "category", data: viz.rows.map((r) => r[key]), axisLabel: { color: muted, rotate: viz.rows.length > 5 ? 30 : 0 } },
    yAxis: [
      { type: "value", axisLabel: { color: muted }, splitLine: { lineStyle: { color: line } } },
      { type: "value", min: 0, max: 100, axisLabel: { color: muted, formatter: "{value}%" }, splitLine: { show: false } },
    ],
    series: [
      { name: "Value", type: "bar", data: viz.rows.map((r) => num(r.Value)) },
      { name: "Cumulative %", type: "line", yAxisIndex: 1, symbol: "circle", data: viz.rows.map((r) => num(r["Cumulative %"])) },
    ],
  };
}

function funnelOption(viz: VisualizationSpec) {
  const { ink, panel, colors } = tokens();
  const [key, valueKey] = viz.columns;
  return {
    color: colors,
    tooltip: { trigger: "item", formatter: "{b}: {c}" },
    series: [{
      type: "funnel", sort: "none", gap: 2, left: "10%", width: "80%", top: 8, bottom: 8,
      label: { show: true, position: "inside", color: panel, formatter: "{b}\n{c}" },
      labelLine: { show: false },
      itemStyle: { borderColor: panel, borderWidth: 1 },
      emphasis: { label: { color: ink } },
      data: viz.rows.map((r) => ({ name: r[key], value: num(r[valueKey]) })),
    }],
  };
}

function streamOption(viz: VisualizationSpec) {
  const { muted, line, colors } = tokens();
  const [key] = viz.columns;
  const periods = viz.rows.map((r) => r[key]);
  const series = valueColumns(viz);
  return {
    color: colors,
    tooltip: { trigger: "axis", axisPointer: { type: "line", lineStyle: { color: line } } },
    legend: { bottom: 0, data: series, textStyle: { color: muted } },
    singleAxis: {
      type: "value", min: 0, max: Math.max(periods.length - 1, 1), interval: 1, top: 16, bottom: 56,
      axisLabel: { color: muted, formatter: (i: number) => periods[i] ?? "" },
      splitLine: { show: true, lineStyle: { color: line } },
    },
    series: [{
      type: "themeRiver",
      emphasis: { focus: "series" },
      label: { show: false },
      data: viz.rows.flatMap((r, i) => series.map((name) => [i, num(r[name]), name])),
    }],
  };
}

function bubbleOption(viz: VisualizationSpec) {
  const { muted, line, colors } = tokens();
  const [key, xKey, yKey, sizeKey] = viz.columns;
  const sizes = viz.rows.map((r) => num(r[sizeKey]));
  const low = Math.min(...sizes);
  const high = Math.max(...sizes);
  const radius = (value: number) => (high > low ? 12 + ((value - low) / (high - low)) * 40 : 30);
  return {
    color: colors,
    tooltip: {
      trigger: "item",
      formatter: (p: { data: { name: string; value: number[] } }) =>
        `${p.data.name}<br/>${xKey}: ${p.data.value[0]}<br/>${yKey}: ${p.data.value[1]}<br/>${sizeKey}: ${p.data.value[2]}`,
    },
    legend: { bottom: 0, textStyle: { color: muted } },
    // containLabel leaves out the rotated y-axis name, so the left margin
    // makes room for it.
    grid: { left: 48, right: 24, top: 24, bottom: 72, containLabel: true },
    xAxis: {
      type: "value", name: xKey, nameLocation: "middle", nameGap: 28, ...paddedRange(viz.rows.map((r) => num(r[xKey]))),
      axisLabel: { color: muted, ...INNER_LABELS }, nameTextStyle: { color: muted }, splitLine: { lineStyle: { color: line } },
    },
    yAxis: {
      type: "value", name: yKey, nameLocation: "middle", nameGap: 36, ...paddedRange(viz.rows.map((r) => num(r[yKey]))),
      axisLabel: { color: muted, ...INNER_LABELS }, nameTextStyle: { color: muted }, splitLine: { lineStyle: { color: line } },
    },
    series: viz.rows.map((r) => ({
      name: r[key], type: "scatter", symbolSize: radius(num(r[sizeKey])),
      itemStyle: { opacity: 0.75 },
      data: [{ name: r[key], value: [num(r[xKey]), num(r[yKey]), num(r[sizeKey])] }],
    })),
  };
}

function parallelOption(viz: VisualizationSpec) {
  const { muted, line, colors } = tokens();
  const [key] = viz.columns;
  const metrics = valueColumns(viz);
  return {
    color: colors,
    tooltip: { trigger: "item" },
    legend: { bottom: 0, textStyle: { color: muted } },
    parallel: { left: 48, right: 64, top: 32, bottom: 56 },
    // Each axis spans every item's value; left to ECharts, an axis fitted
    // only the first series and clipped the rest.
    parallelAxis: metrics.map((name, dim) => ({
      dim, name, ...paddedRange(viz.rows.map((r) => num(r[name])), 0.1),
      nameTextStyle: { color: muted }, axisLabel: { color: muted, ...INNER_LABELS }, axisLine: { lineStyle: { color: line } },
    })),
    series: viz.rows.map((r) => ({
      name: r[key], type: "parallel", lineStyle: { width: 2 },
      data: [metrics.map((m) => num(r[m]))],
    })),
  };
}

function sankeyOption(viz: VisualizationSpec) {
  const { ink, colors } = tokens();
  const names = Array.from(new Set(viz.rows.flatMap((r) => [r.From, r.To])));
  return {
    color: colors,
    tooltip: { trigger: "item" },
    series: [{
      type: "sankey", left: 8, right: 96, top: 16, bottom: 16, nodeGap: 12,
      emphasis: { focus: "adjacency" },
      label: { color: ink },
      lineStyle: { color: "gradient", opacity: 0.4 },
      data: names.map((name) => ({ name })),
      links: viz.rows.map((r) => ({ source: r.From, target: r.To, value: num(r.Amount) })),
    }],
  };
}

function calendarOption(viz: VisualizationSpec) {
  const { muted, line, soft, colors } = tokens();
  const [key, valueKey] = viz.columns;
  const dates = viz.rows.map((r) => r[key]).sort();
  const values = viz.rows.map((r) => num(r[valueKey]));
  // Whole months from the first supplied day to the last, so every week gets
  // its own column instead of a handful of days stretching across the frame.
  const [lastYear, lastMonth] = dates[dates.length - 1].split("-").map(Number);
  const monthEnd = new Date(Date.UTC(lastYear, lastMonth, 0)).toISOString().slice(0, 10);
  const rangeStart = `${dates[0].slice(0, 8)}01`;
  const weeks = Math.ceil((Date.parse(monthEnd) - Date.parse(rangeStart)) / (7 * 86_400_000)) + 1;
  // Square-ish cells for a few months; a long range shares the width.
  const cellWidth: number | "auto" = weeks <= 26 ? 22 : "auto";
  return {
    tooltip: { formatter: (p: { data: [string, number] }) => `${p.data[0]}: ${p.data[1]}` },
    visualMap: {
      min: Math.min(...values), max: Math.max(...values), calculable: true, orient: "horizontal", left: "center", bottom: 0,
      inRange: { color: [soft, colors[0]] }, textStyle: { color: muted },
    },
    calendar: {
      range: [rangeStart, monthEnd], top: 40, left: 56, right: cellWidth === "auto" ? 16 : undefined, cellSize: [cellWidth, 20],
      itemStyle: { borderColor: line }, splitLine: { lineStyle: { color: line } },
      dayLabel: { color: muted }, monthLabel: { color: muted }, yearLabel: { color: muted },
    },
    series: [{ type: "heatmap", coordinateSystem: "calendar", data: viz.rows.map((r) => [r[key], num(r[valueKey])]) }],
  };
}

type SunburstNode = { name: string; value?: number; children?: SunburstNode[] };

function sunburstOption(viz: VisualizationSpec) {
  const { panel, colors } = tokens();
  // "Payroll / Sales" nests under "Payroll"; a label without " / " is a
  // top-level slice on its own.
  const roots: SunburstNode[] = [];
  for (const slice of viz.donut) {
    const [parent, ...rest] = slice.label.split(" / ");
    if (!rest.length) {
      roots.push({ name: parent, value: slice.value });
      continue;
    }
    let node = roots.find((r) => r.name === parent && r.children);
    if (!node) {
      node = { name: parent, children: [] };
      roots.push(node);
    }
    node.children!.push({ name: rest.join(" / "), value: slice.value });
  }
  return {
    color: colors,
    tooltip: { trigger: "item", formatter: (p: { name: string; value: number }) => `${p.name}: ${p.value}%` },
    series: [{
      type: "sunburst", radius: ["12%", "90%"], sort: undefined,
      itemStyle: { borderColor: panel, borderWidth: 2 },
      label: { rotate: "radial", color: panel },
      data: roots,
    }],
  };
}

function bulletOption(viz: VisualizationSpec) {
  const { ink, muted, line } = tokens();
  const [brand] = chartPalette();
  const good = cssVar("--good", "#0f7b46");
  const bad = cssVar("--bad", "#b42318");
  const value = viz.value ?? 0;
  const target = viz.target ?? 0;
  const ratio = target > 0 ? value / target : 0;
  const unit = viz.unit === "%" ? "%" : viz.unit ? ` ${viz.unit}` : "";
  const barColor = ratio >= 1 ? good : ratio >= 0.9 ? brand : bad;
  const label = viz.label ?? "Actual";
  return {
    tooltip: {
      formatter: () =>
        `${label}: ${value.toLocaleString()}${unit}<br/>${viz.target_label ?? "Target"}: ${target.toLocaleString()}${unit}<br/>` +
        `${(ratio * 100).toFixed(1)}% of target`,
    },
    grid: { left: 8, right: 32, top: 48, bottom: 48, containLabel: true },
    xAxis: { type: "value", min: 0, max: Math.max(value, target) * 1.1 || 1, axisLabel: { color: muted }, splitLine: { lineStyle: { color: line } } },
    yAxis: { type: "category", data: [label], axisLabel: { color: ink } },
    series: [{
      type: "bar", barWidth: 28, data: [value], itemStyle: { color: barColor },
      label: { show: true, position: "right", color: ink, formatter: () => `${value.toLocaleString()}${unit}` },
      markLine: {
        symbol: "none", silent: true,
        lineStyle: { color: ink, width: 3, type: "solid" },
        label: { color: ink, formatter: `${viz.target_label ?? "Target"}: ${target.toLocaleString()}${unit}` },
        data: [{ xAxis: target }],
      },
    }],
  };
}

const BUILDERS: Record<ExtraChartKind, (viz: VisualizationSpec) => Record<string, unknown>> = {
  pareto: paretoOption,
  funnel: funnelOption,
  stream: streamOption,
  bubble: bubbleOption,
  parallel: parallelOption,
  sankey: sankeyOption,
  calendar: calendarOption,
  sunburst: sunburstOption,
  bullet: bulletOption,
};

/** The option for one of these charts, or null for every other spec. */
export function buildExtraChartOption(viz: VisualizationSpec): Record<string, unknown> | null {
  const kind = extraChartKind(viz);
  return kind ? BUILDERS[kind](viz) : null;
}
