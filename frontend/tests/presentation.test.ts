import { describe, expect, it, vi } from "vitest";

import {
  formatPresentationValue,
  presentationChartToCsv,
  presentationChartToMarkdown,
  safeDownloadName,
  tableRowsToTsv,
  writeImageToClipboard,
  writeTextToClipboard,
} from "@/lib/presentation";

const usdChart = {
  chart_id: "receivables",
  type: "bar" as const,
  title: "Monthly receivables",
  categories: ["January", "February"],
  series: [{ name: "Receivables", values: ["210000", "195000"], unit: "$" }],
  unit: "$",
  domain: "accounting" as const,
  summary_mode: "total" as const,
  value_format: "currency" as const,
  currency_code: "USD" as const,
  decimal_places: 0,
  x_axis_label: "Month",
};

describe("presentation formatting and export helpers", () => {
  it("formats full and compact governed currency values", () => {
    expect(formatPresentationValue(210000, usdChart)).toMatch(/\$210,000/);
    expect(formatPresentationValue(210000, usdChart, true)).toMatch(/\$210K/i);
    // accounting currencySign — negatives are parenthesised, not hyphenated
    expect(formatPresentationValue(-1200, usdChart)).toMatch(/\(\$1,200\)/);
  });

  it("exports deterministic chart data as CSV", () => {
    expect(presentationChartToCsv(usdChart)).toBe(
      "Month,Receivables\r\nJanuary,210000\r\nFebruary,195000",
    );
  });

  it("quotes long category labels safely in CSV", () => {
    const chart = {
      ...usdChart,
      categories: ["January, audited"],
      series: [{ name: "Receivables", values: ["210000"], unit: "$" }],
    };
    expect(presentationChartToCsv(chart)).toMatch(/"January, audited",210000/);
  });

  it("exports a portable formatted Markdown table", () => {
    const markdown = presentationChartToMarkdown(usdChart);
    expect(markdown).toMatch(/\| Month \| Receivables \|/);
    expect(markdown).toMatch(/\| January \| \$210,000 \|/);
  });

  it("creates filesystem-safe export names", () => {
    expect(safeDownloadName("Monthly A/R: 2026", "csv")).toBe("monthly-a-r-2026.csv");
  });

  it("falls back to a generic name when a query has no alphanumerics", () => {
    expect(safeDownloadName("¿?—", "md")).toBe("kriton-export.md");
  });

  it("exports rendered table cells as spreadsheet-friendly TSV", () => {
    expect(
      tableRowsToTsv([
        ["Filing status", "2025", "2026"],
        ["Married Filing Jointly", "$31,500", "$32,200"],
      ]),
    ).toBe("Filing status\t2025\t2026\nMarried Filing Jointly\t$31,500\t$32,200");
  });
});

describe("writeTextToClipboard", () => {
  it("uses the modern async clipboard API when the browser exposes it", async () => {
    const writes: string[] = [];
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: async (value: string) => void writes.push(value) },
      configurable: true,
    });
    try {
      await writeTextToClipboard("governed answer");
      expect(writes).toEqual(["governed answer"]);
      // the fallback path must not have run
      expect(document.querySelector("textarea")).toBeNull();
    } finally {
      Reflect.deleteProperty(navigator, "clipboard");
    }
  });

  it("falls back to execCommand in browsers without the modern API, leaving no stray node", async () => {
    // jsdom implements neither navigator.clipboard nor execCommand, which is
    // exactly the legacy shape this fallback exists for.
    let copied = false;
    Object.defineProperty(document, "execCommand", {
      value: (command: string) => command === "copy" && (copied = true),
      configurable: true,
    });
    try {
      await writeTextToClipboard("validated answer");
      expect(copied).toBe(true);
      expect(document.querySelector("textarea")).toBeNull();
    } finally {
      Reflect.deleteProperty(document, "execCommand");
    }
  });

  it("copies a figure as a real image so it pastes as a picture", async () => {
    const written: unknown[] = [];
    class FakeClipboardItem {
      constructor(public items: Record<string, Blob>) {}
    }
    vi.stubGlobal("ClipboardItem", FakeClipboardItem);
    Object.defineProperty(navigator, "clipboard", {
      value: { write: async (items: unknown[]) => void written.push(...items) },
      configurable: true,
    });
    try {
      const blob = new Blob(["png-bytes"], { type: "image/png" });
      await writeImageToClipboard(blob);
      expect(written).toHaveLength(1);
      expect((written[0] as FakeClipboardItem).items["image/png"]).toBe(blob);
    } finally {
      vi.unstubAllGlobals();
      Reflect.deleteProperty(navigator, "clipboard");
    }
  });

  it("throws rather than silently copying nothing where images are unsupported", async () => {
    // Legacy browsers cannot put binary data on the clipboard at all; a
    // silent no-op would look identical to a successful copy.
    vi.stubGlobal("ClipboardItem", undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { write: async () => {} },
      configurable: true,
    });
    try {
      await expect(writeImageToClipboard(new Blob([]))).rejects.toThrow(/cannot copy images/i);
    } finally {
      vi.unstubAllGlobals();
      Reflect.deleteProperty(navigator, "clipboard");
    }
  });

  it("throws when the copy is rejected so callers can surface a failure", async () => {
    Object.defineProperty(document, "execCommand", {
      value: () => false,
      configurable: true,
    });
    try {
      await expect(writeTextToClipboard("rejected")).rejects.toThrow(/rejected/i);
      expect(document.querySelector("textarea")).toBeNull();
    } finally {
      Reflect.deleteProperty(document, "execCommand");
    }
  });
});
