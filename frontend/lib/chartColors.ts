// Fixed-order categorical palette (see app/globals.css --chart-1..8) —
// validated CVD-safe (dataviz skill's reference set, re-checked against
// Kriton's own panel surface, not a generic default). Index-based and never
// reassigned: a series keeps the same color for as long as it's visible,
// even if a filter changes which series are shown. Distinct from
// --ok/--warn/--bad — those are reserved status colors elsewhere in the app
// (risk levels), never borrowed as an arbitrary "series 4."
//
// Single source of truth for both chart-rendering surfaces in the app
// (KritonChart's fenced-JSON charts in ask-kriton/page.tsx, and the
// structured AnswerVisualizations component) — previously each had its own,
// different palette (an 8-color validated set here vs. a 4-color ad hoc
// set of semantic status tokens in AnswerVisualizations), which could drift
// out of sync and gave the two chart surfaces inconsistent colors for the
// same data shape.
export const CHART_SERIES_COLORS = [
  "var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)",
  "var(--chart-5)", "var(--chart-6)", "var(--chart-7)", "var(--chart-8)",
];

export function seriesColor(index: number, totalSeries: number): string {
  // A single series needs no categorical identity at all — it's the one
  // thing being plotted, so it gets the app's own deliberate brand hue
  // rather than an arbitrary slot from the multi-series palette.
  if (totalSeries === 1) return "var(--brand)";
  return CHART_SERIES_COLORS[index % CHART_SERIES_COLORS.length];
}
