/**
 * Checks lib/math-delimiters.ts — the model's \[ … \] / \( … \) maths is
 * rewritten to the $$ / $ delimiters remark-math renders, without touching
 * code or ordinary brackets.
 *
 *   node lib/__tests__/math-delimiters.mjs
 *
 * Runs the real module (Node's TypeScript type-stripping), not a copy.
 */

import katex from "katex";
import { cleanMathText, normaliseLatexDelimiters } from "../math-delimiters.ts";

const cases = [
  [
    "display maths becomes a $$ block",
    "COGS:\n\\[ \\text{COGS} = 50{,}000 + 200{,}000 - 70{,}000 = 180{,}000 \\]\nSo…",
    "COGS:\n\n$$\n\\text{COGS} = 50{,}000 + 200{,}000 - 70{,}000 = 180{,}000\n$$\n\nSo…",
  ],
  ["inline maths becomes $$…$$ inline", "ratio \\( \\frac{a}{b} \\) here", "ratio $$\\frac{a}{b}$$ here"],
  ["inline code is untouched", "code `\\[x\\]` stays", "code `\\[x\\]` stays"],
  ["fenced code is untouched", "```\n\\[x\\]\n```", "```\n\\[x\\]\n```"],
  ["ordinary brackets and currency untouched", "plain [link text] and ₹5,000", "plain [link text] and ₹5,000"],
];

let failed = 0;
for (const [name, input, expected] of cases) {
  const actual = normaliseLatexDelimiters(input);
  if (actual === expected) {
    console.log(`PASS  ${name}`);
  } else {
    failed += 1;
    console.log(`FAIL  ${name}\n  expected ${JSON.stringify(expected)}\n  actual   ${JSON.stringify(actual)}`);
  }
}
// Every character the model has been seen (or is likely) to put inside a
// formula must reach KaTeX without a single console warning or render error.
const TYPOGRAPHY = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\u00a0\u2009\u202f\u200b\u2018\u2019\u201c\u201d\u2026\u00d7\u00f7\u20b9\u20ac\u00a3\u00b1\u2264\u2265\u2248\u2260\u2022\u00b7\u2032";
const realWarn = console.warn;
let warnings = 0;
let renderErrors = 0;
console.warn = () => { warnings += 1; };
for (const ch of TYPOGRAPHY) {
  for (const formula of [`a ${ch} b`, `\\text{a ${ch} b}`, `\\text{x \\textbf{${ch}}} ${ch} 1`]) {
    const html = katex.renderToString(cleanMathText(formula), { throwOnError: false });
    if (html.includes("katex-error")) renderErrors += 1;
  }
}
console.warn = realWarn;
if (warnings === 0 && renderErrors === 0) {
  console.log("PASS  no KaTeX warnings or render errors for model typography");
} else {
  failed += 1;
  console.log(`FAIL  KaTeX produced ${warnings} warnings and ${renderErrors} render errors`);
}

const rupee = cleanMathText("\u20b9\u202f5\u202f000 \\text{in \u20b9}");
// The narrow no-break space becomes a plain one; math mode ignores it.
if (rupee === "\\text{Rs. } 5 000 \\text{in Rs. }") {
  console.log("PASS  rupee is upright text in math, plain inside \\text");
} else {
  failed += 1;
  console.log(`FAIL  rupee handling: ${JSON.stringify(rupee)}`);
}

const wacc = "\\text{WACC}= (0.40 \\times 6.75\\%) + (0.60 \\times 14\\%) = \\mathbf{0.1110} \\; \\text{or} \\; \\mathbf{11.10 %}";
const waccHtml = katex.renderToString(cleanMathText(wacc), { throwOnError: false, displayMode: true });
if (!waccHtml.includes("katex-error") && cleanMathText(wacc).includes("6.75\\%") && !cleanMathText(wacc).includes("\\\\%")) {
  console.log("PASS  bare % in a formula renders as a percent, escaped % unchanged");
} else {
  failed += 1;
  console.log(`FAIL  percent handling: ${JSON.stringify(cleanMathText(wacc))}`);
}

for (const [input, expected] of [
  ["\\\\text{\u20b9}10,00,000", "\\text{Rs. }10,00,000"],
  ["= **40,00,000**", "= \\mathbf{40,00,000}"],
  ["a \\\\ b", "a \\\\ b"],
]) {
  const out = cleanMathText(input);
  if (out === expected && !katex.renderToString(out, { throwOnError: false }).includes("katex-error")) {
    console.log(`PASS  model formula slip repaired: ${JSON.stringify(input)}`);
  } else {
    failed += 1;
    console.log(`FAIL  ${JSON.stringify(input)} -> ${JSON.stringify(out)}`);
  }
}

console.log(failed ? `\n${failed} FAILED` : "\nALL PASS");
process.exit(failed ? 1 : 0);
