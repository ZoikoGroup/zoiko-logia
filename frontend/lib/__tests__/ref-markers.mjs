/**
 * Checks lib/presentation.ts REF_MARKER — internal citation ids never reach the
 * reader, whatever brackets or hyphen the model uses, while ordinary
 * parenthesised numbers survive.
 *
 *   node lib/__tests__/ref-markers.mjs
 */

import { answerBodyOnly } from "../presentation.ts";

const cases = [
  ["square brackets", "Revenue rose 5% [REF-1].", "Revenue rose 5%."],
  ["bare number in brackets", "Rates vary [2].", "Rates vary."],
  ["list of refs", "See the data [REF-2, REF-5].", "See the data."],
  ["parentheses with non-breaking hyphen", "World Bank WDI – Germany (REF‑1) and France (REF‑2).", "World Bank WDI – Germany and France."],
  ["bare REF", "Source: REF-3 shows growth.", "Source: shows growth."],
  ["ordinary (1) kept", "Step (1): record the sale.", "Step (1): record the sale."],
];

let failed = 0;
for (const [name, input, expected] of cases) {
  const actual = answerBodyOnly(input).replace(/[ \t]+([.,;:])/g, "$1").replace(/[ \t]{2,}/g, " ");
  if (actual === expected) console.log(`PASS  ${name}`);
  else { failed += 1; console.log(`FAIL  ${name}\n  expected ${JSON.stringify(expected)}\n  actual   ${JSON.stringify(actual)}`); }
}
console.log(failed ? `\n${failed} FAILED` : "\nALL PASS");
process.exit(failed ? 1 : 0);
