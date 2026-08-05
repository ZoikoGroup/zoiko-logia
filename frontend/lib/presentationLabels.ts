/** Shared between AnswerVisualizations.tsx (guides) and AnswerChartFigure.tsx
 * (charts) — kept in its own module rather than exported from either
 * component file to avoid a circular import between the two. */
export const DOMAIN_LABELS = {
  general: "Validated data",
  accounting: "Accounting analysis",
  audit: "Audit workflow",
  tax: "Tax analysis",
} as const;

/** Dynamic Visualization Selection v5 — mirrors the backend's
 * _CHART_FAMILY (presentation_dataprofile.py) exactly, for telemetry
 * enrichment only (never used to decide which alternatives are offered —
 * that's entirely a backend, registry-driven decision; the frontend just
 * labels whatever family the backend already put in chart.alternatives). */
const CHART_FAMILY: Record<string, string> = {
  bar: "category_series", grouped_bar: "category_series",
  diverging_bar: "category_series", radar: "category_series",
  dumbbell: "category_series", lollipop: "category_series", bullet: "category_series",
  histogram: "distribution", box_plot: "distribution",
  scatter: "paired_numeric", bubble: "paired_numeric",
  heatmap: "matrix", correlation_matrix: "matrix",
  funnel: "ordered_single_measure", waterfall: "ordered_single_measure",
  slope: "two_point_per_entity",
  stacked_bar: "multi_group_composition", percentage_stacked_bar: "multi_group_composition",
  line: "temporal_series", area: "temporal_series",
  donut: "single_total_composition", composition_bar: "single_total_composition",
};

export function chartFamily(chartType: string | null | undefined): string | null {
  return chartType ? (CHART_FAMILY[chartType] ?? null) : null;
}
