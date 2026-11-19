import { describe, expect, it } from "vitest";
import { normaliseMarkdownTables } from "@/components/AnswerRenderer";

// 19 Nov 2026: a balance sheet with blank spacer rows ("| | |") was split
// into fragments shown as raw pipes — the spacer row was taken for the
// "|---|" rule line that starts a new table.
const BALANCE_SHEET = [
  "| **Assets** | |",
  "|---|---|",
  "| Property, plant and equipment | 210,000 |",
  "| **Total assets** | 299,900 |",
  "| | |",
  "| **Liabilities** | |",
  "| Trade payables | 39,100 |",
  "| **Total liabilities** | 57,500 |",
  "| | |",
  "| **Total equity** | 246,900 |",
].join("\n");

describe("blank spacer rows inside a table", () => {
  it("keep the table in one piece", () => {
    const out = normaliseMarkdownTables(BALANCE_SHEET);
    const lines = out.split("\n");
    // No blank line is inserted between the rows, so it stays one table.
    expect(lines.slice(lines.indexOf("| **Assets** | |")).every((line) => line.trim() !== "")).toBe(true);
    expect(out).toContain("| | |\n| **Liabilities** | |");
  });

  it("still starts a table at a real rule line", () => {
    const out = normaliseMarkdownTables("Heading text\n| a | b |\n|---|---|\n| 1 | 2 |");
    expect(out).toBe("Heading text\n\n| a | b |\n|---|---|\n| 1 | 2 |");
  });
});
