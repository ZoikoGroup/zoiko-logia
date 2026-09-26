/**
 * The model writes display maths as \[ … \] and inline maths as \( … \), but
 * remark-math only recognises $$ … $$ and $ … $ — and Markdown reads "\[" as
 * an escaped "[" — so formulas reached the reader as "[ \text{COGS} = … ]".
 * Rewrite the delimiters outside code spans/blocks, which stay untouched.
 */
export function normaliseLatexDelimiters(text: string): string {
  return text
    .split(/(```[\s\S]*?```|`[^`\n]*`)/g)
    .map((part, index) =>
      index % 2 === 1
        ? part
        : part
            .replace(/\\\[([\s\S]+?)\\\]/g, (_m, body: string) => `\n$$\n${body.trim()}\n$$\n`)
            .replace(/\\\(([\s\S]+?)\\\)/g, (_m, body: string) => `$${body.trim()}$`),
    )
    .join("");
}

// Typography the model puts inside formulas that KaTeX has no font metrics
// for — each one logged "Unrecognized Unicode character" and/or "No
// character metrics" on EVERY render (the latter unconditionally, so it can
// only be fixed by never handing KaTeX the character). Written as \u escapes
// on purpose: several are invisible spaces that would be unreviewable raw.
const UNIVERSAL: [RegExp, string][] = [
  [/[‐-―⁃−﹘﹣－]/g, "-"], // hyphens, dashes, minus
  [/[  -   　]/g, " "],       // no-break / thin / narrow spaces
  [/[​-‍⁠﻿]/g, ""],                    // zero-width characters
  [/[‘’‚‛′‵]/g, "'"],        // curly single quotes, primes
  [/[“”„‟″]/g, "''"],             // curly double quotes
  [/…/g, "..."],                                      // ellipsis
  [/[•∙]/g, "·"],                           // bullets -> middle dot (supported)
];

// [character, replacement in math mode, replacement inside \text{…}].
const SYMBOLS: [string, string, string][] = [
  ["×", " \\times ", "x"],
  ["÷", " \\div ", "/"],
  ["±", " \\pm ", "+/-"],
  ["≤", " \\le ", "<="],
  ["≥", " \\ge ", ">="],
  // Not "~" in text: LaTeX reads "~" as a non-breaking space.
  ["≈", " \\approx ", "approx. "],
  ["≠", " \\neq ", "!="],
  // KaTeX has no rupee or euro glyph: upright text in math (a bare "Rs" would
  // render as italic variables), plain text inside \text{…}.
  ["₹", "\\text{Rs. }", "Rs. "],
  ["€", "\\text{EUR }", "EUR "],
];

/** Split a formula into math and \text{…} (\textbf, \textit, …) runs,
 * honouring nested braces, so symbols get the right replacement per mode. */
function splitTextRuns(formula: string): { text: boolean; value: string }[] {
  const runs: { text: boolean; value: string }[] = [];
  const opener = /\\text[a-z]*\{/g;
  let cursor = 0;
  while (opener.exec(formula) !== null) {
    let depth = 1;
    let end = opener.lastIndex;
    while (end < formula.length && depth > 0) {
      if (formula[end] === "\\") end += 1; // skip the escaped character
      else if (formula[end] === "{") depth += 1;
      else if (formula[end] === "}") depth -= 1;
      end += 1;
    }
    runs.push({ text: false, value: formula.slice(cursor, opener.lastIndex) });
    runs.push({ text: true, value: formula.slice(opener.lastIndex, end - 1) });
    runs.push({ text: false, value: "}" });
    cursor = end;
    opener.lastIndex = end;
  }
  runs.push({ text: false, value: formula.slice(cursor) });
  return runs;
}

/** Make a formula KaTeX-safe: no character KaTeX cannot draw. */
export function cleanMathText(formula: string): string {
  const universal = UNIVERSAL.reduce((value, [pattern, replacement]) => value.replace(pattern, replacement), formula);
  return splitTextRuns(universal)
    .map(({ text, value }) =>
      SYMBOLS.reduce((out, [symbol, inMath, inText]) => out.split(symbol).join(text ? inText : inMath), value),
    )
    .join("");
}
