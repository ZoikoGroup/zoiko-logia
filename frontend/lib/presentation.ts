import type { PresentationChart } from "@/lib/api";

function legacyCurrency(unit: string) {
  if (unit === "$" || unit === "USD") return "USD";
  if (unit === "£" || unit === "GBP") return "GBP";
  if (unit === "€" || unit === "EUR") return "EUR";
  return null;
}

export function formatPresentationValue(
  value: number,
  chart: Pick<PresentationChart, "unit" | "value_format" | "currency_code" | "decimal_places">,
  compact = false,
) {
  const currency = chart.currency_code ?? legacyCurrency(chart.unit);
  const valueFormat = chart.value_format ?? (chart.unit === "%" ? "percent" : currency ? "currency" : "number");
  const decimalPlaces = chart.decimal_places ?? 2;
  const options: Intl.NumberFormatOptions = {
    maximumFractionDigits: compact ? Math.min(decimalPlaces, 1) : decimalPlaces,
    notation: compact ? "compact" : "standard",
  };

  if (valueFormat === "currency" && currency) {
    options.style = "currency";
    options.currency = currency;
    options.currencyDisplay = "narrowSymbol";
    options.currencySign = "accounting";
  }

  // Kriton's governed reports use one stable numeric convention regardless
  // of the workstation locale, so copied/exported USD values cannot switch
  // from 210,000 to 2,10,000 between reviewers.
  const formatted = value.toLocaleString("en-US", options);
  return valueFormat === "percent" ? `${formatted}%` : formatted;
}

export async function writeTextToClipboard(value: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  textarea.remove();
  if (!copied) throw new Error("Clipboard copy was rejected");
}

/** Writes a rendered figure to the clipboard as a real image, so it pastes
 * into Word/Slides/Teams as a picture rather than as a file path. There is no
 * execCommand fallback here: legacy browsers cannot put binary data on the
 * clipboard at all, and silently copying nothing would be worse than a
 * reported failure, so this throws and the caller surfaces it.
 *
 * Chromium requires the ClipboardItem to be constructed synchronously with a
 * Promise<Blob> when the blob is produced asynchronously, but passing an
 * already-resolved Blob is valid everywhere and keeps the call sites simple —
 * callers rasterize first, then copy. */
export async function writeImageToClipboard(blob: Blob) {
  const clipboard = navigator.clipboard;
  if (!clipboard?.write || typeof ClipboardItem === "undefined") {
    throw new Error("This browser cannot copy images to the clipboard");
  }
  await clipboard.write([new ClipboardItem({ [blob.type || "image/png"]: blob })]);
}

export function tableRowsToTsv(rows: readonly (readonly string[])[]) {
  return rows
    .map((row) => row.map((cell) => cell.replace(/\s+/g, " ").trim()).join("\t"))
    .join("\n");
}

function csvCell(value: string | number) {
  const text = String(value);
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

export function presentationChartToCsv(chart: PresentationChart) {
  const rows = [
    [chart.x_axis_label || "Label", ...chart.series.map((series) => series.name)],
    ...chart.categories.map((category, index) => [
      category,
      ...chart.series.map((series) => series.values[index] ?? ""),
    ]),
  ];
  return rows.map((row) => row.map(csvCell).join(",")).join("\r\n");
}

export function presentationChartToMarkdown(chart: PresentationChart) {
  const header = [chart.x_axis_label || "Label", ...chart.series.map((series) => series.name)];
  const divider = header.map((_, index) => index === 0 ? "---" : "---:");
  const rows = chart.categories.map((category, index) => [
    category,
    ...chart.series.map((series) => {
      const raw = Number(series.values[index]);
      return Number.isFinite(raw) ? formatPresentationValue(raw, chart) : "";
    }),
  ]);
  return [header, divider, ...rows].map((row) => `| ${row.join(" | ")} |`).join("\n");
}

export function safeDownloadName(value: string, extension: string) {
  const stem = value
    .normalize("NFKD")
    .replace(/[^a-zA-Z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .toLowerCase()
    .slice(0, 80) || "kriton-export";
  return `${stem}.${extension}`;
}
