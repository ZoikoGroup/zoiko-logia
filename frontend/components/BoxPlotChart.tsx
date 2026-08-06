"use client";

import type { RefObject } from "react";
import ReactECharts from "echarts-for-react";
import type { PresentationChart } from "@/lib/api";

/** Recharts has no native box-plot component; ECharts does. This is the
 * only one of the Dynamic Visualization Engine v2 chart types that actually
 * needs it — everything else in AnswerVisualizations.tsx stays on Recharts.
 * Quartiles are computed here from the same validated series values already
 * shown in the accessible table, never invented. */
function quartiles(values: number[]): [number, number, number, number, number] {
  const sorted = [...values].sort((a, b) => a - b);
  const at = (p: number) => {
    const index = (sorted.length - 1) * p;
    const lower = Math.floor(index);
    const upper = Math.ceil(index);
    if (lower === upper) return sorted[lower];
    return sorted[lower] + (sorted[upper] - sorted[lower]) * (index - lower);
  };
  return [sorted[0], at(0.25), at(0.5), at(0.75), sorted[sorted.length - 1]];
}

export function BoxPlotChart({
  chart, chartRef,
}: {
  chart: PresentationChart;
  /** Forwarded so the caller can PNG-export via ECharts' own getDataURL —
   * a canvas-rendered chart has no <svg> for the generic exporter to find. */
  chartRef?: RefObject<ReactECharts | null>;
}) {
  const boxData = chart.series.map((series) => quartiles(series.values.map(Number)));
  const categories = chart.series.map((series) => series.name);

  return (
    <ReactECharts
      ref={chartRef}
      option={{
        tooltip: { trigger: "item" },
        grid: { left: 60, right: 20, top: 20, bottom: 40 },
        xAxis: { type: "category", data: categories, axisLabel: { fontSize: 11 } },
        yAxis: { type: "value", axisLabel: { fontSize: 11 } },
        series: [{
          type: "boxplot",
          data: boxData,
          itemStyle: { color: "var(--brand)", borderColor: "var(--ink)" },
        }],
      }}
      style={{ height: "100%", width: "100%" }}
      notMerge
      opts={{ renderer: "canvas" }}
    />
  );
}
