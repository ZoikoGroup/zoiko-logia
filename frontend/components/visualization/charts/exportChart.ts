import type { VisualizationSpec } from "@/lib/api";
import type { EChartsInstanceLike } from "./EChartsAdapter";

function downloadDataUrl(dataUrl: string, filename: string) {
  const a = document.createElement("a");
  a.href = dataUrl;
  a.download = filename;
  a.click();
}

function downloadBlob(content: string, mime: string, filename: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  downloadDataUrl(url, filename);
  URL.revokeObjectURL(url);
}

function safeFilename(viz: VisualizationSpec, ext: string): string {
  const base = (viz.title ?? viz.type).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
  return `${base || "chart"}.${ext}`;
}

// ── PNG export ────────────────────────────────────────────────────────────
// Canvas engine (ECharts): capture the live chart instance directly — it
// already renders to canvas, so this is just reading back its own bitmap.
export function exportEChartsPng(instance: EChartsInstanceLike | null, viz: VisualizationSpec) {
  if (!instance) return;
  const backgroundColor = getComputedStyle(document.documentElement).getPropertyValue("--panel").trim() || "#ffffff";
  const dataUrl = instance.getDataURL({ type: "png", pixelRatio: 2, backgroundColor });
  downloadDataUrl(dataUrl, safeFilename(viz, "png"));
}

// Declarative-library engine (Recharts, SVG-based): rasterize the rendered
// SVG onto a canvas — there is no live bitmap to read back, only markup.
export function exportSvgAsPng(container: HTMLElement, viz: VisualizationSpec) {
  const svg = container.querySelector("svg");
  if (!svg) return;
  const clone = svg.cloneNode(true) as SVGSVGElement;
  const { width, height } = svg.getBoundingClientRect();
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));
  const backgroundColor = getComputedStyle(document.documentElement).getPropertyValue("--panel").trim() || "#ffffff";

  const svgString = new XMLSerializer().serializeToString(clone);
  const svgBlob = new Blob([svgString], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(svgBlob);

  const image = new Image();
  image.onload = () => {
    const canvas = document.createElement("canvas");
    const scale = 2;
    canvas.width = width * scale;
    canvas.height = height * scale;
    const ctx = canvas.getContext("2d");
    if (ctx) {
      ctx.scale(scale, scale);
      ctx.fillStyle = backgroundColor;
      ctx.fillRect(0, 0, width, height);
      ctx.drawImage(image, 0, 0, width, height);
      downloadDataUrl(canvas.toDataURL("image/png"), safeFilename(viz, "png"));
    }
    URL.revokeObjectURL(url);
  };
  image.src = url;
}

// ── CSV export ────────────────────────────────────────────────────────────
// Chart-type-aware — each shape's real fields get their own writer rather
// than a lossy one-size-fits-all category/value pair.
function csvRow(cells: (string | number)[]): string {
  return cells.map((c) => {
    const s = String(c);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }).join(",");
}

export function exportChartCsv(viz: VisualizationSpec) {
  const lines: string[] = [];

  if (viz.type === "LINE" || viz.type === "BAR") {
    lines.push(csvRow(["Period", viz.title ?? "Value"]));
    for (const p of viz.data) lines.push(csvRow([p.x, p.y]));
  } else if (viz.type === "HISTOGRAM") {
    lines.push(csvRow(["Bin", "Count"]));
    for (const p of viz.data) lines.push(csvRow([p.x, p.y]));
  } else if (viz.type === "BOX" && viz.box) {
    lines.push(csvRow(["Statistic", "Value"]));
    lines.push(csvRow(["Minimum", viz.box.minimum]));
    lines.push(csvRow(["Q1", viz.box.q1]));
    lines.push(csvRow(["Median", viz.box.median]));
    lines.push(csvRow(["Q3", viz.box.q3]));
    lines.push(csvRow(["Maximum", viz.box.maximum]));
    viz.box.outliers.forEach((v, i) => lines.push(csvRow([`Outlier ${i + 1}`, v])));
  } else if (viz.type === "SCATTER") {
    const xLabel = viz.encoding?.x.field ?? "X";
    const yLabel = viz.encoding?.y.field ?? "Y";
    lines.push(csvRow(["Period", xLabel, yLabel]));
    for (const p of viz.scatter) lines.push(csvRow([p.label, p.x, p.y]));
  } else if (viz.type === "HEATMAP") {
    lines.push(csvRow(["Source", "Target", "Value"]));
    for (const c of viz.cells) lines.push(csvRow([c.x, c.y, c.value]));
  } else if (viz.type === "DONUT") {
    lines.push(csvRow(["Holder", "Share (%)", "Estimated"]));
    for (const s of viz.donut) lines.push(csvRow([s.label, s.value, s.is_estimated ? "Yes (band midpoint)" : "No"]));
  } else if (viz.type === "CANDLESTICK") {
    lines.push(csvRow(["Date", "Open", "High", "Low", "Close", "Volume"]));
    for (const b of viz.candlestick) lines.push(csvRow([b.dimension, b.open, b.high, b.low, b.close, b.volume ?? ""]));
  } else if (viz.type === "GROUPED_BAR") {
    lines.push(csvRow(["Period", ...viz.series.map((s) => s.name)]));
    const categories = viz.series[0]?.data.map((p) => p.x) ?? [];
    categories.forEach((cat, i) => {
      lines.push(csvRow([cat, ...viz.series.map((s) => s.data[i]?.y ?? 0)]));
    });
  } else {
    return;
  }

  downloadBlob(lines.join("\n"), "text/csv;charset=utf-8", safeFilename(viz, "csv"));
}
