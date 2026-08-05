import type { CalculationWidget } from "@/lib/api";
import { downloadCsv, sanitizeFilename } from "@/lib/visualizationExport";

/** Exports the governed calculation engine's own chart_points — Decimal-as-
 * string values straight from the verified backend result, never reformatted
 * display strings — so the CSV always matches the number the widget shows. */
export function exportChartCsv(widget: CalculationWidget): void {
  const headers = [widget.chart_x_label || "X", widget.chart_y_label || "Y", "Unit"];
  const rows = widget.chart_points.map((point) => [point.x, point.y, widget.output_unit]);
  downloadCsv(headers, rows, sanitizeFilename(widget.chart_label || widget.formula_name, "csv"));
}
