import { describe, expect, it } from "vitest";
import {
  answerBodyOnly,
  safeDownloadName,
  tableElementToRows,
  tableRowsToMarkdown,
  tableRowsToTsv,
} from "@/lib/presentation";

/**
 * The export helpers are where a mistake is silent: a copied answer that
 * quietly keeps the disclaimer, or a table that loses a column, looks fine on
 * screen and is only wrong once it has left the app.
 */

describe("answerBodyOnly", () => {
  it("removes the appended disclaimer and the rule that precedes it", () => {
    const answer = [
      "Tesla's market capitalisation is USD 1.31 trillion.",
      "",
      "---",
      "⚠️ **Kriton™ Disclaimer**: This response is provided for educational purposes only.",
    ].join("\n");

    const body = answerBodyOnly(answer);
    expect(body).toBe("Tesla's market capitalisation is USD 1.31 trillion.");
    expect(body).not.toContain("Disclaimer");
    // The separator must go too, or the copied text ends on a dangling rule.
    expect(body).not.toContain("---");
  });

  it("strips inline citation markers, which are meaningless outside the app", () => {
    expect(answerBodyOnly("Revenue rose [REF-1] year on year [REF-2].")).toBe(
      "Revenue rose year on year.",
    );
  });

  it("leaves an answer with no disclaimer untouched", () => {
    expect(answerBodyOnly("A plain answer.")).toBe("A plain answer.");
  });

  it("does not mistake a body mention of 'disclaimer' for the appended block", () => {
    const answer = "Every audit report carries a disclaimer paragraph.";
    expect(answerBodyOnly(answer)).toBe(answer);
  });
});

describe("safeDownloadName", () => {
  it("slugifies a question into a usable filename", () => {
    expect(safeDownloadName("What is Apple's share price?", "md")).toBe("what-is-apple-s-share-price.md");
  });

  it("falls back rather than producing a bare extension", () => {
    expect(safeDownloadName("???", "md")).toBe("kriton-answer.md");
    expect(safeDownloadName("", "md")).toBe("kriton-answer.md");
  });

  it("caps the length so a long question cannot break the filesystem", () => {
    const stem = safeDownloadName("a".repeat(500), "md").replace(/\.md$/, "");
    expect(stem.length).toBeLessThanOrEqual(80);
  });
});

describe("tableRowsToTsv", () => {
  it("joins with tabs so spreadsheets split it into cells without an import step", () => {
    expect(tableRowsToTsv([["Metric", "Value"], ["EPS", "1.08"]])).toBe("Metric\tValue\nEPS\t1.08");
  });

  it("collapses internal whitespace, which would otherwise break the column count", () => {
    expect(tableRowsToTsv([["  Gross   margin  ", "18.85%"]])).toBe("Gross margin\t18.85%");
  });
});

describe("tableRowsToMarkdown", () => {
  it("emits a header separator row", () => {
    expect(tableRowsToMarkdown([["A", "B"], ["1", "2"]])).toBe("| A | B |\n| --- | --- |\n| 1 | 2 |");
  });

  it("escapes pipes so a cell cannot split the table", () => {
    expect(tableRowsToMarkdown([["A|B"]])).toBe("| A\\|B |\n| --- |");
  });

  it("returns empty for no rows rather than a malformed table", () => {
    expect(tableRowsToMarkdown([])).toBe("");
  });
});

describe("tableElementToRows", () => {
  it("reads every cell of the rendered table, header included", () => {
    document.body.innerHTML = `
      <table>
        <thead><tr><th>Metric</th><th>Value</th></tr></thead>
        <tbody><tr><td>EPS</td><td>1.08</td></tr><tr><td>P/E</td><td>343.4</td></tr></tbody>
      </table>`;
    const table = document.querySelector("table") as HTMLTableElement;

    expect(tableElementToRows(table)).toEqual([
      ["Metric", "Value"],
      ["EPS", "1.08"],
      ["P/E", "343.4"],
    ]);
  });
});
