"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef } from "react";
import { cssVar } from "@/lib/css-var";
import type { VisualizationSpec } from "@/lib/api";
import { chartPalette } from "./palette";

// echarts-for-react touches the DOM (canvas), so load it client-only.
const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

/**
 * ECharts (canvas engine) for HEATMAP/BOX/SCATTER (see engineRouting.ts) —
 * capabilities the declarative library doesn't have natively: a category-
 * axis matrix with a visualMap gradient, a native "boxplot" series type,
 * and dual numeric axes with a paired-value tooltip formatter. No in-canvas
 * title — ChartCard renders title+subtitle as HTML above the chart, so
 * typography stays on the app's own text tokens.
 */
function buildHeatmapOption(viz: VisualizationSpec): Record<string, unknown> {
  const ink = cssVar("--ink", "#17211f");
  const muted = cssVar("--muted", "#667673");
  const [brand] = chartPalette();
  const soft = cssVar("--soft", "#f7faf8");

  const xCats = Array.from(new Set(viz.cells.map((c) => c.x)));
  const yCats = Array.from(new Set(viz.cells.map((c) => c.y)));
  const data = viz.cells.map((c) => [xCats.indexOf(c.x), yCats.indexOf(c.y), c.value]);
  const maxValue = Math.max(1, ...viz.cells.map((c) => c.value));

  return {
    tooltip: { position: "top" },
    grid: { left: 8, right: 24, top: 16, bottom: 64, containLabel: true },
    xAxis: { type: "category", data: xCats, axisLabel: { color: muted, rotate: xCats.length > 4 ? 35 : 0 } },
    yAxis: { type: "category", data: yCats, axisLabel: { color: muted } },
    visualMap: {
      min: 0, max: maxValue, calculable: true, orient: "horizontal", bottom: 0,
      inRange: { color: [soft, brand] }, textStyle: { color: muted },
    },
    series: [{
      type: "heatmap", data,
      label: { show: true, color: ink },
      emphasis: { itemStyle: { shadowBlur: 6, shadowColor: "rgba(0,0,0,0.2)" } },
    }],
  };
}

function buildBoxplotOption(viz: VisualizationSpec): Record<string, unknown> {
  const muted = cssVar("--muted", "#667673");
  const line = cssVar("--line", "#eef3f2");
  const [seriesColor] = chartPalette();
  // Outliers are a genuine flagged/anomalous status, not a second series
  // identity — --bad (reserved) is the right token here, unlike a generic
  // multi-series chart where status colors must never stand in for identity.
  const outlierColor = cssVar("--bad", "#e2725b");
  const box = viz.box;
  if (!box) return {};
  const category = box.label || viz.title || "value";
  return {
    tooltip: { trigger: "item" },
    grid: { left: 8, right: 24, top: 16, bottom: 32, containLabel: true },
    xAxis: { type: "category", data: [category], axisLabel: { color: muted } },
    // scale: true — a real quartile range far from zero (e.g. India CPI's
    // ~192-197) would otherwise render as a sliver pinned to the top of a
    // 0-anchored axis; ECharts value axes force zero into range by default
    // unless told this is a magnitude scale that should fit the real data.
    yAxis: { type: "value", scale: true, axisLabel: { color: muted }, splitLine: { lineStyle: { color: line } } },
    series: [
      {
        name: category, type: "boxplot",
        data: [[box.minimum, box.q1, box.median, box.q3, box.maximum]],
        itemStyle: { color: seriesColor, borderColor: seriesColor },
      },
      ...(box.outliers.length
        ? [{ name: "Outliers", type: "scatter", data: box.outliers.map((v) => [category, v]), itemStyle: { color: outlierColor } }]
        : []),
    ],
  };
}

function buildScatterOption(viz: VisualizationSpec): Record<string, unknown> {
  const muted = cssVar("--muted", "#667673");
  const line = cssVar("--line", "#eef3f2");
  const [seriesColor] = chartPalette();
  const xLabel = viz.encoding?.x.field ?? "X";
  const yLabel = viz.encoding?.y.field ?? "Y";
  return {
    tooltip: {
      trigger: "item",
      formatter: (p: { data: [number, number]; name: string }) =>
        `${p.name}<br/>${xLabel}: ${p.data[0]}<br/>${yLabel}: ${p.data[1]}`,
    },
    grid: { left: 8, right: 24, top: 16, bottom: 48, containLabel: true },
    // scale: true on both axes — same reasoning as buildBoxplotOption's
    // yAxis: a scatter's two real series rarely sit near zero on the same
    // scale, so forcing it in would bunch every point into one corner.
    xAxis: { type: "value", name: xLabel, scale: true, axisLabel: { color: muted }, splitLine: { lineStyle: { color: line } } },
    yAxis: { type: "value", name: yLabel, scale: true, axisLabel: { color: muted }, splitLine: { lineStyle: { color: line } } },
    series: [{
      type: "scatter", symbolSize: 10,
      data: viz.scatter.map((p) => ({ name: p.label, value: [p.x, p.y] })),
      itemStyle: { color: seriesColor },
    }],
  };
}

function buildDonutOption(viz: VisualizationSpec): Record<string, unknown> {
  const ink = cssVar("--ink", "#17211f");
  const muted = cssVar("--muted", "#667673");
  const panel = cssVar("--panel", "#ffffff");
  const colors = chartPalette();
  return {
    tooltip: {
      trigger: "item",
      formatter: (p: { name: string; value: number; percent: number; data: { isEstimated?: boolean } }) =>
        `${p.name}<br/>${p.value.toFixed(1)}%${p.data?.isEstimated ? " (estimated)" : ""}`,
    },
    legend: { bottom: 0, textStyle: { color: muted }, type: "scroll" },
    color: colors,
    series: [{
      type: "pie",
      radius: ["45%", "70%"],
      // A visible ring between slices reads as a real dataset boundary, not
      // a rendering gap — same "surface gap between fills" rule as a
      // stacked bar's segment gaps.
      itemStyle: { borderColor: panel, borderWidth: 2 },
      label: { color: ink, formatter: "{b}: {d}%" },
      labelLine: { lineStyle: { color: muted } },
      data: viz.donut.map((s) => ({ name: s.label, value: s.value, isEstimated: s.is_estimated })),
    }],
  };
}

export function buildEChartsOption(viz: VisualizationSpec): Record<string, unknown> {
  if (viz.type === "HEATMAP") return buildHeatmapOption(viz);
  if (viz.type === "BOX") return buildBoxplotOption(viz);
  if (viz.type === "SCATTER") return buildScatterOption(viz);
  if (viz.type === "DONUT") return buildDonutOption(viz);
  return {};
}

// Minimal surface of the live ECharts instance this module needs — just
// enough to export a PNG directly from the canvas engine's own bitmap.
export interface EChartsInstanceLike {
  getDataURL: (opts: Record<string, unknown>) => string;
  resize: () => void;
}

export function EChartsChart({ viz, onInstance }: { viz: VisualizationSpec; onInstance?: (instance: EChartsInstanceLike) => void }) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<EChartsInstanceLike | null>(null);

  useEffect(() => {
    if (!wrapperRef.current) return;
    const observer = new ResizeObserver(() => instanceRef.current?.resize());
    observer.observe(wrapperRef.current);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={wrapperRef} className="h-full min-w-0 w-full">
      <ReactECharts
        option={buildEChartsOption(viz)}
        className="h-full w-full"
        style={{ height: "100%", width: "100%" }}
        notMerge
        onChartReady={(instance: EChartsInstanceLike) => {
          instanceRef.current = instance;
          onInstance?.(instance);
        }}
      />
    </div>
  );
}
