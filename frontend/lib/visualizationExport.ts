/** Shared client-side export helpers for chart/graph/diagram visualizations
 * (PNG downloads, CSV downloads, filename/content sanitization). Kept here
 * rather than duplicated across the per-renderer exporters, since every
 * exporter needs the same filename rules, object-URL lifecycle, and
 * spreadsheet-formula-injection guard. */

/** Predictable, filesystem-safe filename: lowercase, ascii, hyphenated,
 * capped length, with today's date and the given extension. Never derived
 * from anything beyond the visualization's own title — no hidden state. */
export function sanitizeFilename(base: string, extension: string): string {
  const slug = base
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60) || "visualization";
  const date = new Date().toISOString().slice(0, 10);
  return `kriton-${slug}-${date}.${extension}`;
}

/** Prevents spreadsheet formula injection (CSV/Excel/Sheets execute a cell
 * starting with =, +, -, or @ as a formula on open). Prefixing with a
 * single quote forces text interpretation without changing the visible
 * value in any spreadsheet application. Also applies RFC 4180 quoting. */
export function escapeCsvCell(value: string | number): string {
  let text = String(value ?? "");
  if (/^[=+\-@]/.test(text)) text = `'${text}`;
  if (/[",\n]/.test(text)) text = `"${text.replace(/"/g, '""')}"`;
  return text;
}

export function rowsToCsv(headers: string[], rows: (string | number)[][]): string {
  const lines = [headers, ...rows].map((row) => row.map(escapeCsvCell).join(","));
  return lines.join("\r\n");
}

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  // Revoked after a short delay — some browsers need the navigation the
  // click triggers to actually start before the URL is torn down.
  setTimeout(() => URL.revokeObjectURL(url), 5_000);
}

export function downloadCsv(headers: string[], rows: (string | number)[][], filename: string): void {
  const csv = rowsToCsv(headers, rows);
  triggerDownload(new Blob([`﻿${csv}`], { type: "text/csv;charset=utf-8" }), filename);
}

export function downloadBlob(blob: Blob, filename: string): void {
  triggerDownload(blob, filename);
}

/** Converts an ECharts/Cytoscape base64 data URL (their synchronous export
 * APIs both support a "base64uri"-shaped string) into a Blob for download. */
export function dataUrlToBlob(dataUrl: string): Blob {
  const [meta, base64] = dataUrl.split(",");
  const mimeMatch = /data:(.*?);base64/.exec(meta);
  const mime = mimeMatch?.[1] || "image/png";
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}
