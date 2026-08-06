import type { PresentationChart } from "@/lib/api";
import { downloadCsv, sanitizeFilename } from "@/lib/visualizationExport";

/** Waterfall's CSV needs the running total and step type spelled out
 * explicitly — a plain category/value dump (what exportPresentationChartCsv
 * does for every other chart type) would lose the bridge semantics the
 * chart itself conveys visually. Mirrors EChartsPresentationChart's own
 * base/rise/fall computation so the two never drift apart. */
export function exportPresentationWaterfallCsv(chart: PresentationChart): void {
  const values = chart.series[0]?.values.map(Number) ?? [];
  const headers = ["Step", "Raw change", "Running total", "Step type"];
  const rows: (string | number)[][] = [];
  let running = 0;
  values.forEach((value, index) => {
    const isFirst = index === 0;
    const isLast = index === values.length - 1;
    const stepType = isFirst ? "start" : isLast ? "total" : value >= 0 ? "increase" : "decrease";
    running = isFirst || isLast ? value : running + value;
    rows.push([chart.categories[index] ?? `Step ${index + 1}`, value, running, stepType]);
  });
  downloadCsv(headers, rows, sanitizeFilename(chart.title, "csv"));
}
