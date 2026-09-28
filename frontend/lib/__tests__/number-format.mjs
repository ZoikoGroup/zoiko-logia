/**
 * Checks lib/number-format.ts — rupee amounts display in Indian grouping,
 * everything else is left alone.
 *
 *   node lib/__tests__/number-format.mjs
 */

import { indianiseRupeeAmounts as f } from "../number-format.ts";

const cases = [
  ["INR after the amount", "10,000 × 109.26 = 1,092,600 INR", "10,000 × 109.26 = 10,92,600 INR"],
  ["₹ before the amount", "Total ₹1,092,600.50 due", "Total ₹10,92,600.50 due"],
  ["already Indian grouping unchanged", "₹10,92,600 and ₹2,62,500", "₹10,92,600 and ₹2,62,500"],
  ["small amounts unchanged", "₹87,500 and 9,000 INR", "₹87,500 and 9,000 INR"],
  ["crore-sized amounts", "INR 12,345,678", "INR 1,23,45,678"],
  ["dollars keep international grouping", "$1,092,600 and 11,403 USD", "$1,092,600 and 11,403 USD"],
  ["bare numbers untouched", "Population 1,092,600", "Population 1,092,600"],
  ["code untouched", "`INR 1,092,600`", "`INR 1,092,600`"],
];
let failed = 0;
for (const [name, input, expected] of cases) {
  const actual = f(input);
  const ok = actual === expected;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : `\n  expected ${expected}\n  actual   ${actual}`}`);
  failed += ok ? 0 : 1;
}
console.log(failed ? `\n${failed} FAILED` : "\nALL PASS");
process.exit(failed ? 1 : 0);
