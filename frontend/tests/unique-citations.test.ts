import { describe, expect, it } from "vitest";
import type { SourceCitation } from "@/lib/api";
import { uniqueCitations } from "@/lib/unique-citations";

function doc(ref: number, file: string, location: string, documentId = file): SourceCitation {
  return { ref_id: `REF-${ref}`, source_id: documentId, title: `${file} — ${location}`, url: null, provider: "uploaded_document" };
}

function web(ref: number, url: string, title = url): SourceCitation {
  return { ref_id: `REF-${ref}`, source_id: url, title, url };
}

describe("uniqueCitations", () => {
  it("lists each uploaded file once, with how many sections were used", () => {
    const shown = uniqueCitations([
      doc(1, "ledger.csv", "'ledger'!1:41"),
      doc(2, "ledger.csv", "'ledger'!42:81"),
      doc(3, "payroll.csv", "'payroll'!1:21"),
      doc(4, "ledger.csv", "'ledger'!82:121"),
    ]);
    expect(shown.map((c) => c.title)).toEqual(["ledger.csv — 3 sections", "payroll.csv — 'payroll'!1:21"]);
    expect(shown[0].ref_id).toBe("REF-1");
  });

  it("drops an excerpt cited twice", () => {
    const shown = uniqueCitations([
      doc(1, "invoices.csv", "'invoices'!1:41"),
      doc(2, "invoices.csv", "'invoices'!1:41"),
    ]);
    expect(shown.map((c) => c.title)).toEqual(["invoices.csv — 'invoices'!1:41"]);
  });

  it("keeps two different files with the same name apart", () => {
    const shown = uniqueCitations([
      doc(1, "report.xlsx", "'Q1'!1:10", "doc-a"),
      doc(2, "report.xlsx", "'Q1'!1:10", "doc-b"),
    ]);
    expect(shown).toHaveLength(2);
  });

  it("lists each web source once and leaves distinct ones alone", () => {
    const shown = uniqueCitations([
      web(1, "https://www.gov.uk/vat-rates", "VAT rates"),
      web(2, "https://www.gov.uk/vat-rates", "VAT rates"),
      web(3, "https://www.gov.uk/income-tax-rates", "Income Tax rates"),
    ]);
    expect(shown.map((c) => c.title)).toEqual(["VAT rates", "Income Tax rates"]);
  });

  it("returns nothing for nothing", () => {
    expect(uniqueCitations([])).toEqual([]);
  });
});
