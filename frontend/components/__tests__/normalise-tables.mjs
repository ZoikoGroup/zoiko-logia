/**
 * Proves that model-written Markdown tables actually parse as tables.
 *
 *   node components/__tests__/normalise-tables.mjs
 *
 * Unlike the Mermaid checks, this one CAN be verified properly: remark + GFM
 * run in Node with no DOM, so the assertion is "does the parser emit a table
 * node", not "does the string look right".
 *
 * Keep the logic here in step with AnswerRenderer.normaliseMarkdownTables.
 */
import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkGfm from "remark-gfm";

const TABLE_ROW = /^ {0,3}\|.*\|\s*$/;
const TABLE_RULE = /^ {0,3}\|[\s:|-]+\|\s*$/;

function normaliseMarkdownTables(text) {
  const lines = text.split("\n");
  const out = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const deindented = line.replace(/^\s+(?=\|)/, "");
    const isRow = TABLE_ROW.test(deindented);
    const startsTable =
      isRow && i + 1 < lines.length && TABLE_RULE.test(lines[i + 1].replace(/^\s+(?=\|)/, ""));
    if (startsTable) {
      const previous = out[out.length - 1];
      if (previous !== undefined && previous.trim() !== "") out.push("");
    }
    if (isRow) {
      out.push(deindented);
      const next = lines[i + 1];
      const nextIsRow = next !== undefined && TABLE_ROW.test(next.replace(/^\s+(?=\|)/, ""));
      if (next !== undefined && !nextIsRow && next.trim() !== "") out.push("");
      continue;
    }
    out.push(line);
  }
  return out.join("\n");
}

const processor = unified().use(remarkParse).use(remarkGfm);

function countTables(md) {
  let tables = 0;
  const walk = (node) => {
    if (node.type === "table") tables++;
    (node.children ?? []).forEach(walk);
  };
  walk(processor.parse(md));
  return tables;
}

function rowsOf(md) {
  let rows = 0;
  const walk = (node) => {
    if (node.type === "tableRow") rows++;
    (node.children ?? []).forEach(walk);
  };
  walk(processor.parse(md));
  return rows;
}

// ── The exact shape from the screenshot: table glued to its heading ─────────

const SCREENSHOT = `**5. Quick-look sample of the Reconciliation table (GitHub-flavoured Markdown)**
| Metric | Calculated (WP) | Reported (Summary) | Difference |
|------------------------|----------------|-------------------|------------|
| Total Revenue | 2,264,000 | 2,264,000 | 0 |
| Total Cost | 1,109,000 | 1,109,000 | 0 |
| Completed Deals | 16 | 16 | 0 |
*(Values are taken directly from your Summary sheet.)*`;

const HEADING_THEN_TABLE = `### KPI Overview
| KPI | Value |
|---|---|
| Total Revenue | US$ 2,264,000 |`;

const LIST_THEN_TABLE = `1. First step
2. Second step
| Item | Amount |
|---|---|
| Revenue | 100 |`;

const INDENTED_TABLE = `Summary below:
    | Metric | Value |
    |---|---|
    | Revenue | 100 |`;

const ALREADY_CORRECT = `Some text.

| A | B |
|---|---|
| 1 | 2 |

More text.`;

// The shape the screenshot actually shows: the pipes are in a MONOSPACE font,
// which means Markdown saw a code block — the rows were indented under the
// numbered item rather than merely lacking a blank line.
const NUMBERED_INDENTED = `**4. Alignment with audit-working-paper best practice**

**5. Quick-look sample of the Reconciliation table (GitHub-flavoured Markdown)**
    | Metric | Calculated (WP) | Reported (Summary) | Difference |
    |------------------------|----------------|-------------------|------------|
    | Total Revenue | 2,264,000 | 2,264,000 | 0 |
    | Completed Deals | 16 | 16 | 0 |
*(Values are taken directly from your Summary sheet.)*`;

const CASES = [
  ["screenshot shape: numbered + indented", NUMBERED_INDENTED, 1, 3],
  ["screenshot: heading then table", SCREENSHOT, 1, 4],
  ["heading then table", HEADING_THEN_TABLE, 1, 2],
  ["numbered list then table", LIST_THEN_TABLE, 1, 2],
  ["indented table (was a code block)", INDENTED_TABLE, 1, 2],
  ["already correct", ALREADY_CORRECT, 1, 2],
];

let failed = 0;
console.log(`${"case".padEnd(36)} before  after  rows`);
console.log("-".repeat(60));
for (const [label, md, wantTables, wantRows] of CASES) {
  const before = countTables(md);
  const fixed = normaliseMarkdownTables(md);
  const after = countTables(fixed);
  const rows = rowsOf(fixed);
  const ok = after === wantTables && rows === wantRows;
  if (!ok) failed++;
  console.log(
    `${ok ? "PASS" : "FAIL"} ${label.padEnd(31)} ${before}       ${after}      ${rows}`
  );
  if (!ok) {
    console.log(`      expected ${wantTables} table / ${wantRows} rows`);
    console.log(fixed.split("\n").map((l) => "      | " + l).join("\n"));
  }
}

// The trailing paragraph after the screenshot table must survive as its own text.
const fixedScreenshot = normaliseMarkdownTables(SCREENSHOT);
const keepsTrailer = fixedScreenshot.includes("*(Values are taken directly from your Summary sheet.)*");
console.log(`${keepsTrailer ? "PASS" : "FAIL"} trailing note preserved`);
if (!keepsTrailer) failed++;

// Text with no tables must come back untouched.
const PROSE = "Just an answer.\n\nWith two paragraphs and a | pipe | in prose.";
const untouched = normaliseMarkdownTables(PROSE) === PROSE;
console.log(`${untouched ? "PASS" : "FAIL"} prose with a stray pipe untouched`);
if (!untouched) failed++;

console.log(failed ? `\n${failed} FAILURE(S)` : "\nALL PASS");
process.exit(failed ? 1 : 0);
