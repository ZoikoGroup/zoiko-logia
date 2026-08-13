import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import type { VisualizationSpec } from "@/lib/api";

/**
 * First/latest/total + trend arrow, above the chart. Suppressed entirely
 * for chart types where "latest value of a series" isn't a meaningful
 * concept — HISTOGRAM (a distribution, not a sequence), BOX (a five-number
 * summary), SCATTER (paired values, no single ordered series), HEATMAP (a
 * relationship matrix). Only LINE/BAR are genuine ordered value sequences.
 */
export function shouldShowSummaryMetrics(type: VisualizationSpec["type"]): boolean {
  return type === "LINE" || type === "BAR";
}

export function SummaryMetricCards({ viz }: { viz: VisualizationSpec }) {
  if (!shouldShowSummaryMetrics(viz.type) || viz.data.length < 2) return null;
  const first = viz.data[0];
  const latest = viz.data[viz.data.length - 1];
  const total = viz.data.reduce((sum, p) => sum + p.y, 0);
  const delta = latest.y - first.y;
  const direction = delta > 0 ? "up" : delta < 0 ? "down" : "flat";
  const unit = viz.unit ? ` ${viz.unit}` : "";

  const cards = [
    { label: "First", value: first.y, sub: first.x },
    { label: "Latest", value: latest.y, sub: latest.x },
    { label: "Total", value: total, sub: `${viz.data.length} periods` },
  ];

  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {cards.slice(0, 3).map((c) => (
        <div key={c.label} className="rounded-lg border border-line bg-soft px-3 py-2">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted">{c.label}</p>
          <p className="mt-0.5 flex items-center gap-1 text-sm font-bold text-ink">
            {c.value.toLocaleString()}
            {unit}
            {c.label === "Latest" && (
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
