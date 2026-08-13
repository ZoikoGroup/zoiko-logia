/**
 * Fixed membership: which rendering engine a chart type routes through.
 * Not per-chart config — routing is a lookup, never a per-instance decision,
 * so it can't silently drift between two charts of the same type.
 *
 * RECHARTS: types the declarative library expresses natively (grid/axis/
 * tooltip/legend/series composition) — LINE and BAR share one shape
 * (VisualizationDataPoint[]), HISTOGRAM is a bar-of-precomputed-bins.
 *
 * ECHARTS (canvas engine): types needing capabilities Recharts doesn't have
 * natively — HEATMAP (category-axis matrix + visualMap), BOX (native
 * boxplot series type), SCATTER (dual numeric axes with a tooltip formatter
 * keyed on paired values), DONUT (native pie/donut series type).
 *
 * Only the types this backend actually produces today are listed (see
 * backend/app/orchestration/visualization/registry.py) — the wider
 * taxonomy (PIE_DONUT, WATERFALL, RADAR, FUNNEL, ...) has no real,
 * non-fabricated data source in this codebase yet, so it isn't routed here
 * either; adding a row is the same day a real data source and backend
 * builder exist for it, matching every other visualization type's history
 * in this project.
 */
import type { VisualizationSpec } from "@/lib/api";

export type ChartEngine = "RECHARTS" | "ECHARTS";

const RECHARTS_TYPES = new Set<VisualizationSpec["type"]>(["LINE", "BAR", "HISTOGRAM"]);
const ECHARTS_TYPES = new Set<VisualizationSpec["type"]>(["HEATMAP", "BOX", "SCATTER", "DONUT"]);

export function engineFor(type: VisualizationSpec["type"]): ChartEngine | null {
  if (RECHARTS_TYPES.has(type)) return "RECHARTS";
  if (ECHARTS_TYPES.has(type)) return "ECHARTS";
  return null;
}

// Same-shape client-side "View" alternatives — a type may only appear here
// if the ALTERNATIVE can render straight from the CURRENT spec's own data
// fields, with no refetch and no data the payload doesn't already carry.
// LINE and BAR both consume the identical `data: VisualizationDataPoint[]`
// shape, so switching is a pure re-render. BOX's declared backend fallback
// (registry.py: BOX -> HISTOGRAM) is NOT included here: a histogram needs
// the full underlying value array to bin, and BOX's spec only carries the
// five-number summary + outliers — genuinely not enough data to render one
// without a refetch, so offering it would be a dead/broken menu item.
export const SAME_SHAPE_VIEW_ALTERNATIVES: Partial<Record<VisualizationSpec["type"], VisualizationSpec["type"][]>> = {
  LINE: ["BAR"],
  BAR: ["LINE"],
};
