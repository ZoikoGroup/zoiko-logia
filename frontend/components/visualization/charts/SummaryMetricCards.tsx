import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import type { VisualizationSpec } from "@/lib/api";

/**
 * First/latest + trend arrow, above the chart. Suppressed entirely
 * for chart types where "latest value of a series" isn't a meaningful
 * concept — HISTOGRAM (a distribution, not a sequence), BOX (a five-number
 * summary), SCATTER (paired values, no single ordered series), HEATMAP (a
 * relationship matrix). Only LINE/BAR are genuine ordered value sequences.
 */
export function shouldShowSummaryMetrics(type: VisualizationSpec["type"]): boolean {
  return type === "LINE" || type === "BAR";
}

export function SummaryMetricCards({ viz }: { viz: VisualizationSpec }) {
  if (!shouldShowSummaryMetrics(viz.type) || viz.data.length < 2 || viz.series.length > 1) return null;
  const first = viz.data[0];
  const latest = viz.data[viz.data.length - 1];
  // A waterfall's bars are steps: its end is their running total, not the last
  // step ("Latest −300 Income tax expense" stood over a bridge ending at 900, QA D03).
  const waterfall = viz.variant === "WATERFALL_CHART";
  const end = waterfall ? viz.data.reduce((sum, point) => sum + point.y, 0) : latest.y;
  const delta = end - first.y;
  const direction = delta > 0 ? "up" : delta < 0 ? "down" : "flat";
  const unit = viz.unit ? ` ${viz.unit}` : "";

  const cards = waterfall
    ? [
        { label: "Start", value: first.y, sub: first.x },
        { label: "End result", value: end, sub: `After ${viz.data.length - 1} steps` },
      ]
    : [
        { label: "First", value: first.y, sub: first.x },
        { label: "Latest", value: latest.y, sub: latest.x },
      ];

  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      {cards.map((c, index) => (
        <div key={c.label} className="rounded-lg border border-line bg-soft px-3 py-2">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted">{c.label}</p>
          <p className="mt-0.5 flex items-center gap-1 text-sm font-bold text-ink">
            {c.value.toLocaleString()}
            {unit}
            {index === 1 && (
              direction === "up" ? <TrendingUp size={14} className="text-ok" /> :
              direction === "down" ? <TrendingDown size={14} className="text-bad" /> :
              <Minus size={14} className="text-muted" />
            )}
          </p>
          <p className="text-[11px] text-muted">{c.sub}</p>
        </div>
      ))}
    </div>
  );
}
