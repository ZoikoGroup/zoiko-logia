import type { PresentationChart } from "@/lib/api";
import { downloadCsv, sanitizeFilename } from "@/lib/visualizationExport";

/** One row per category, one column per series — the same shape as the
 * accessible table already shown beside the chart, straight from the
 * validated series values (never a reformatted display string). */
export function exportPresentationChartCsv(chart: PresentationChart): void {
  const headers = ["Category", ...chart.series.map((series) => `${series.name}${chart.unit ? ` (${chart.unit})` : ""}`)];
  const rows = chart.categories.map((category, index) => [
    category,
    ...chart.series.map((series) => series.values[index] ?? ""),
  ]);
  downloadCsv(headers, rows, sanitizeFilename(chart.title, "csv"));
}
