import { describe, expect, it } from "vitest";
import { stripInlineRefs } from "@/components/AnswerRenderer";

describe("citation markers leave no gaps", () => {
  it("drops the word that pointed at the marker", () => {
    expect(stripInlineRefs("Apply the three criteria in [REF-3] and evaluate control transfer."))
      .toBe("Apply the three criteria and evaluate control transfer.");
    expect(stripInlineRefs("Revenue is 10,000 as stated in [REF-1].")).toBe("Revenue is 10,000.");
  });

  it("removes brackets left empty", () => {
    expect(stripInlineRefs("the equity shown on the balance sheet ([REF-2]).")).toBe("the equity shown on the balance sheet.");
    expect(stripInlineRefs("the balance sheet (REF-2) agrees.")).toBe("the balance sheet agrees.");
  });

  it("drops a Source column that only held markers, and keeps one with real text", () => {
    const table = "| Item | Amount | Source |\n|---|---|---|\n| Cash | 1,200 | [REF-1] |\n| Total | 7,500 | [REF-2] |";
    expect(stripInlineRefs(table)).toBe("| Item | Amount |\n| --- | --- |\n| Cash | 1,200 |\n| Total | 7,500 |");
    const kept = "| Item | Source |\n|---|---|\n| Cash | p.2 |";
    expect(stripInlineRefs(kept)).toBe(kept);
  });

  it("leaves ordinary prose alone", () => {
    const text = "Log in and review the figures (net of VAT) in the report.";
    expect(stripInlineRefs(text)).toBe(text);
  });
});
