import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";

import {
  formatPresentationValue,
  presentationChartToCsv,
  presentationChartToMarkdown,
  safeDownloadName,
  tableRowsToTsv,
  writeTextToClipboard,
} from "./presentation.ts";

const usdChart = {
  chart_id: "receivables",
  type: "bar" as const,
  title: "Monthly receivables",
  categories: ["January", "February"],
  series: [{ name: "Receivables", values: ["210000", "195000"] }],
  unit: "$",
  value_format: "currency" as const,
  currency_code: "USD" as const,
  decimal_places: 0,
  x_axis_label: "Month",
};

test("formats full and compact governed currency values", () => {
  assert.match(formatPresentationValue(210000, usdChart), /\$210,000/);
  assert.match(formatPresentationValue(210000, usdChart, true), /\$210K/i);
  assert.match(formatPresentationValue(-1200, usdChart), /\(\$1,200\)/);
});

test("exports deterministic chart data as CSV", () => {
  assert.equal(
    presentationChartToCsv(usdChart),
    "Month,Receivables\r\nJanuary,210000\r\nFebruary,195000",
  );
});

test("quotes long category labels safely in CSV", () => {
  const chart = { ...usdChart, categories: ["January, audited"], series: [{ name: "Receivables", values: ["210000"] }] };
  assert.match(presentationChartToCsv(chart), /"January, audited",210000/);
});

test("exports a portable formatted Markdown table", () => {
  const markdown = presentationChartToMarkdown(usdChart);
  assert.match(markdown, /\| Month \| Receivables \|/);
  assert.match(markdown, /\| January \| \$210,000 \|/);
});

test("creates filesystem-safe export names", () => {
  assert.equal(safeDownloadName("Monthly A/R: 2026", "csv"), "monthly-a-r-2026.csv");
});

test("exports rendered table cells as spreadsheet-friendly TSV", () => {
  assert.equal(
    tableRowsToTsv([
      ["Filing status", "2025", "2026"],
      ["Married Filing Jointly", "$31,500", "$32,200"],
    ]),
    "Filing status\t2025\t2026\nMarried Filing Jointly\t$31,500\t$32,200",
  );
});

test("clipboard fallback copies in browsers without the modern API", async () => {
  const dom = new JSDOM("<!doctype html><body></body>");
  const originalDocument = globalThis.document;
  const originalNavigator = globalThis.navigator;
  let copied = false;
  Object.defineProperty(globalThis, "document", { value: dom.window.document, configurable: true });
  Object.defineProperty(globalThis, "navigator", { value: dom.window.navigator, configurable: true });
  Object.defineProperty(dom.window.document, "execCommand", {
    value: (command: string) => command === "copy" && (copied = true),
    configurable: true,
  });

  try {
    await writeTextToClipboard("validated answer");
    assert.equal(copied, true);
    assert.equal(dom.window.document.querySelector("textarea"), null);
  } finally {
    Object.defineProperty(globalThis, "document", { value: originalDocument, configurable: true });
    Object.defineProperty(globalThis, "navigator", { value: originalNavigator, configurable: true });
    dom.window.close();
  }
});
