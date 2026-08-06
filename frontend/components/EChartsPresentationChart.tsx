"use client";

import type { RefObject } from "react";
import ReactECharts from "echarts-for-react";
import type { PresentationChart } from "@/lib/api";

const GRAMMAR_COLORS = ["#7c8cff", "#65d6cf", "#f5b942", "#ef7f8d"];

function buildGrammarOption(chart: PresentationChart) {
  const grammar = chart.grammar;
  if (!grammar || grammar.layers.length === 0 || grammar.layers.some((layer) => !chart.series[layer.series_index])) return null;
  if (grammar.composition === "facet") {
    const count = grammar.layers.length;
    const columns = Math.min(grammar.facet_columns ?? 2, count);
    const rows = Math.ceil(count / columns);
    const gap = 3;
    const width = (94 - gap * (columns - 1)) / columns;
    const height = (88 - gap * (rows - 1)) / rows;
    return {
      tooltip: { trigger: "axis" },
      title: grammar.layers.map((layer, index) => ({
        text: chart.series[layer.series_index].name, textStyle: { fontSize: 11 },
        left: `${3 + (index % columns) * (width + gap)}%`,
        top: `${Math.floor(index / columns) * (height + gap)}%`,
      })),
      grid: grammar.layers.map((_, index) => ({
        left: `${3 + (index % columns) * (width + gap)}%`,
        top: `${5 + Math.floor(index / columns) * (height + gap)}%`, width: `${width - 3}%`, height: `${height - 10}%`, containLabel: true,
      })),
      xAxis: grammar.layers.map((_, index) => ({ type: "category", gridIndex: index, data: chart.categories, axisLabel: { fontSize: 9 } })),
      yAxis: grammar.layers.map((_, index) => ({ type: "value", gridIndex: index, axisLabel: { fontSize: 9 } })),
      series: grammar.layers.map((layer, index) => ({
        name: chart.series[layer.series_index].name,
        type: layer.mark === "point" ? "scatter" : layer.mark,
        xAxisIndex: index, yAxisIndex: index,
        data: chart.series[layer.series_index].values.map(Number),
        itemStyle: { color: GRAMMAR_COLORS[index % GRAMMAR_COLORS.length] },
        lineStyle: { color: GRAMMAR_COLORS[index % GRAMMAR_COLORS.length] },
        areaStyle: layer.mark === "area" ? { opacity: 0.2 } : undefined,
      })),
    };
  }
  const hasSecondary = grammar.layers.some((layer) => layer.axis === "secondary");
  return {
    tooltip: { trigger: "axis" }, legend: { bottom: 0 },
    grid: { left: 70, right: hasSecondary ? 70 : 25, top: 20, bottom: 55 },
    xAxis: { type: "category", data: chart.categories, axisLabel: { fontSize: 10 } },
    yAxis: [
      { type: "value", position: "left" },
      ...(hasSecondary ? [{ type: "value", position: "right" }] : []),
    ],
    series: grammar.layers.map((layer, index) => ({
      name: chart.series[layer.series_index].name,
      type: layer.mark === "point" ? "scatter" : layer.mark,
      yAxisIndex: layer.axis === "secondary" ? 1 : 0,
      stack: layer.stack ?? undefined,
      data: chart.series[layer.series_index].values.map(Number),
      itemStyle: { color: GRAMMAR_COLORS[index % GRAMMAR_COLORS.length] },
      lineStyle: { color: GRAMMAR_COLORS[index % GRAMMAR_COLORS.length], width: 3 },
      areaStyle: layer.mark === "area" ? { opacity: 0.2 } : undefined,
    })),
  };
}

/** heatmap, correlation_matrix, bullet, and the PresentationChart-native
 * waterfall all need ECharts (Recharts has no heatmap/bullet primitive) —
 * consolidated here rather than in BoxPlotChart.tsx to keep that file's
 * existing, already-tested box_plot path untouched. */

function buildHeatmapOption(chart: PresentationChart) {
  const seriesNames = chart.series.map((series) => series.name);
  const cells: [number, number, number][] = [];
  chart.categories.forEach((_, rowIndex) => {
    chart.series.forEach((series, colIndex) => {
      cells.push([colIndex, rowIndex, Number(series.values[rowIndex])]);
    });
  });
  const values = cells.map((cell) => cell[2]);
  return {
    tooltip: {
      position: "top",
      formatter: (params: { value: [number, number, number] }) =>
        `${chart.categories[params.value[1]]} × ${seriesNames[params.value[0]]}: ${params.value[2]}`,
    },
    grid: { left: 110, right: 20, top: 20, bottom: 70 },
    xAxis: { type: "category", data: seriesNames, splitArea: { show: true }, axisLabel: { fontSize: 10, rotate: 30 } },
    yAxis: { type: "category", data: chart.categories, splitArea: { show: true }, axisLabel: { fontSize: 10 } },
    visualMap: {
      min: values.length ? Math.min(...values) : 0,
      max: values.length ? Math.max(...values) : 1,
      calculable: true, orient: "horizontal", left: "center", bottom: 0,
      inRange: { color: ["#eef6ff", "var(--brand)"] },
      textStyle: { color: "#94a3b8" },
    },
    series: [{ type: "heatmap", data: cells, label: { show: true, fontSize: 9, color: "#1f2937" } }],
  };
}

function buildCorrelationMatrixOption(chart: PresentationChart) {
  // Backend already emits categories = series names = the correlated
  // measures, and each series' values are that row's coefficients — see
  // presentation.py's correlation_matrix branch / compute_correlation_matrix.
  const labels = chart.categories;
  const cells: [number, number, number][] = [];
  chart.series.forEach((series, rowIndex) => {
    series.values.forEach((value, colIndex) => {
      cells.push([colIndex, rowIndex, Number(value)]);
    });
  });
  return {
    tooltip: {
      position: "top",
      formatter: (params: { value: [number, number, number] }) =>
        `${labels[params.value[1]]} × ${labels[params.value[0]]}: ${params.value[2].toFixed(2)}`,
    },
    grid: { left: 110, right: 20, top: 20, bottom: 70 },
    xAxis: { type: "category", data: labels, splitArea: { show: true }, axisLabel: { fontSize: 10, rotate: 30 } },
    yAxis: { type: "category", data: labels, splitArea: { show: true }, axisLabel: { fontSize: 10 } },
    visualMap: {
      min: -1, max: 1, calculable: true, orient: "horizontal", left: "center", bottom: 0,
      inRange: { color: ["#ef7f8d", "#f8fafc", "#65d6cf"] },
      textStyle: { color: "#94a3b8" },
    },
    series: [{
      type: "heatmap", data: cells,
      label: { show: true, fontSize: 9, color: "#1f2937", formatter: (p: { value: [number, number, number] }) => p.value[2].toFixed(2) },
    }],
  };
}

function buildBulletOption(chart: PresentationChart) {
  const actual = chart.series[0];
  const target = chart.series[1];
  const targetPoints = (target?.values ?? []).map((value, index) => [Number(value), index]);
  return {
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    grid: { left: 110, right: 30, top: 20, bottom: 40 },
    legend: { data: [actual?.name ?? "Actual", target?.name ?? "Target"], bottom: 0, textStyle: { color: "#94a3b8", fontSize: 11 } },
    xAxis: { type: "value", axisLabel: { fontSize: 11 } },
    yAxis: { type: "category", data: chart.categories, axisLabel: { fontSize: 11 } },
    series: [
      {
        name: actual?.name ?? "Actual", type: "bar",
        data: (actual?.values ?? []).map(Number), barWidth: 14, itemStyle: { color: "var(--brand)" },
      },
      {
        // A tick mark, not a second bar — shape (not just color) is what
        // distinguishes the target from the actual value.
        name: target?.name ?? "Target", type: "scatter", symbol: "rect", symbolSize: [4, 22],
        data: targetPoints, itemStyle: { color: "#1f2937" },
      },
    ],
  };
}

/** Presentation-chart-native waterfall — a different data shape (and thus a
 * different builder) than CalculationWidget's own waterfall, but the exact
 * same invisible-base-plus-visible-segment ECharts technique. Unlike
 * CalculationWidget's convention, backend has already validated (see
 * contains_signed_deltas / _reconciles_as_bridge) that the middle values
 * here are genuinely signed — no client-side negation needed. */
function buildPresentationWaterfallOption(chart: PresentationChart) {
  const values = chart.series[0]?.values.map(Number) ?? [];
  const base: number[] = [];
  const rise: number[] = [];
  const fall: number[] = [];
  const startOrTotal: number[] = [];
  let running = 0;
  values.forEach((value, index) => {
    base.push(0); rise.push(0); fall.push(0); startOrTotal.push(0);
    if (index === 0 || index === values.length - 1) {
      running = value;
      startOrTotal[index] = value;
      return;
    }
    if (value >= 0) {
      base[index] = running;
      rise[index] = value;
    } else {
      base[index] = running + value;
      fall[index] = -value;
    }
    running += value;
  });
  return {
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    xAxis: { type: "category", data: chart.categories, axisLabel: { fontSize: 11 } },
    yAxis: { type: "value" },
    series: [
      { name: "Base", type: "bar", stack: "waterfall", itemStyle: { color: "transparent" }, emphasis: { disabled: true }, silent: true, data: base },
      { name: "Start / total", type: "bar", stack: "waterfall", itemStyle: { color: "#65d6cf" }, data: startOrTotal },
      { name: "Increase", type: "bar", stack: "waterfall", itemStyle: { color: "#7c8cff" }, data: rise },
      { name: "Decrease", type: "bar", stack: "waterfall", itemStyle: { color: "#ef7f8d" }, data: fall },
    ],
  };
}

export function EChartsPresentationChart({
  chart, chartRef,
}: {
  chart: PresentationChart;
  chartRef?: RefObject<ReactECharts | null>;
}) {
  const option =
    buildGrammarOption(chart) ?? (chart.type === "heatmap" ? buildHeatmapOption(chart)
    : chart.type === "correlation_matrix" ? buildCorrelationMatrixOption(chart)
    : chart.type === "bullet" ? buildBulletOption(chart)
    : buildPresentationWaterfallOption(chart));

  return (
    <ReactECharts
      ref={chartRef}
      option={{
        backgroundColor: "transparent",
        textStyle: { color: "#94a3b8", fontFamily: "inherit" },
        animationDuration: 450,
        ...option,
      }}
      style={{ height: "100%", width: "100%" }}
      notMerge
      opts={{ renderer: "canvas" }}
    />
  );
}
