import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { downloadBlob, downloadCsv, escapeCsvCell, rowsToCsv, sanitizeFilename } from "@/lib/visualizationExport";

describe("escapeCsvCell", () => {
  it("prefixes formula-injection characters with a single quote", () => {
    expect(escapeCsvCell("=SUM(A1:A9)")).toBe("'=SUM(A1:A9)");
    expect(escapeCsvCell("+1234")).toBe("'+1234");
    expect(escapeCsvCell("-1234")).toBe("'-1234");
    expect(escapeCsvCell("@SUM(1)")).toBe("'@SUM(1)");
  });

  it("leaves ordinary values untouched", () => {
    expect(escapeCsvCell("INV-100")).toBe("INV-100");
    expect(escapeCsvCell(42)).toBe("42");
    expect(escapeCsvCell("-not-actually-negative")).toBe("'-not-actually-negative"); // still guarded — leading '-' is the risk, not intent
  });

  it("quotes values containing commas, quotes, or newlines per RFC 4180", () => {
    expect(escapeCsvCell("a,b")).toBe('"a,b"');
    expect(escapeCsvCell('say "hi"')).toBe('"say ""hi"""');
  });
});

describe("sanitizeFilename", () => {
  it("produces a predictable, ascii, hyphenated filename with today's date", () => {
    const name = sanitizeFilename("Evidence Chain: Invoice → Payment", "png");
    expect(name).toMatch(/^kriton-evidence-chain-invoice-payment-\d{4}-\d{2}-\d{2}\.png$/);
  });

  it("falls back to a safe default for an empty or fully-stripped title", () => {
    expect(sanitizeFilename("", "csv")).toMatch(/^kriton-visualization-\d{4}-\d{2}-\d{2}\.csv$/);
  });
});

describe("rowsToCsv", () => {
  it("preserves raw numeric-looking string values without reformatting", () => {
    const csv = rowsToCsv(["X", "Y"], [["2026-01", "1234.500000"]]);
    expect(csv).toContain("1234.500000");
    expect(csv).not.toContain("1,234.5");
  });
});

describe("download helpers revoke object URLs", () => {
  let createObjectURL: ReturnType<typeof vi.fn>;
  let revokeObjectURL: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.useFakeTimers();
    createObjectURL = vi.fn(() => "blob:mock-url");
    revokeObjectURL = vi.fn();
    URL.createObjectURL = createObjectURL as unknown as typeof URL.createObjectURL;
    URL.revokeObjectURL = revokeObjectURL as unknown as typeof URL.revokeObjectURL;
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("revokes the object URL after downloadBlob", () => {
    downloadBlob(new Blob(["x"]), "kriton-test.png");
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).not.toHaveBeenCalled();
    vi.runAllTimers();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock-url");
  });

  it("revokes the object URL after downloadCsv", () => {
    downloadCsv(["a"], [["1"]], "kriton-test.csv");
    vi.runAllTimers();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock-url");
  });
});
