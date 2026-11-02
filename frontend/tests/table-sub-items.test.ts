import { describe, expect, it } from "vitest";
import { indentSubItemCells } from "@/components/AnswerRenderer";

const INDENT = "    ";

describe("table sub-item rows", () => {
  it("shows a dashed sub-item as the indented name only", () => {
    expect(indentSubItemCells("| – Rent | 96,000 |")).toBe(`| ${INDENT}Rent | 96,000 |`);
    expect(indentSubItemCells("| - Salaries and wages | 284,000 |")).toBe(`| ${INDENT}Salaries and wages | 284,000 |`);
    expect(indentSubItemCells("| — Utilities | 18,400 |")).toBe(`| ${INDENT}Utilities | 18,400 |`);
  });

  it("leaves rule lines, minus amounts, dash placeholders and other dashes alone", () => {
    for (const row of [
      "| --- | ---: |",
      "|---|---|",
      "| Net loss | - 5,000 |",
      "| Net loss | - (5,000) |",
      "| Comparative | — |",
      "| Employer NI – pension | 38,600 |",
      "| Revenue | 1,850,000 |",
    ]) {
      expect(indentSubItemCells(row)).toBe(row);
    }
  });
});
