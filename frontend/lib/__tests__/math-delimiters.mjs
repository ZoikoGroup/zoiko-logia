/**
 * Checks lib/math-delimiters.ts — the model's \[ … \] / \( … \) maths is
 * rewritten to the $$ / $ delimiters remark-math renders, without touching
 * code or ordinary brackets.
 *
 *   node lib/__tests__/math-delimiters.mjs
 *
 * Runs the real module (Node's TypeScript type-stripping), not a copy.
 */

import { normaliseLatexDelimiters } from "../math-delimiters.ts";

const cases = [
  [
    "display maths becomes a $$ block",
    "COGS:\n\\[ \\text{COGS} = 50{,}000 + 200{,}000 - 70{,}000 = 180{,}000 \\]\nSo…",
    "COGS:\n\n$$\n\\text{COGS} = 50{,}000 + 200{,}000 - 70{,}000 = 180{,}000\n$$\n\nSo…",
  ],
  ["inline maths becomes $…$", "ratio \\( \\frac{a}{b} \\) here", "ratio $\\frac{a}{b}$ here"],
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
console.log(failed ? `\n${failed} FAILED` : "\nALL PASS");
process.exit(failed ? 1 : 0);
