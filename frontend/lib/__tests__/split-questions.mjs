/**
 * Checks lib/kriton-conversation.ts splitQuestions — a pasted set of numbered
 * questions becomes separate questions (each fully answered), while ordinary
 * messages that merely contain a list stay whole.
 *
 *   node lib/__tests__/split-questions.mjs
 */

import { splitQuestions } from "../kriton-conversation.ts";

let failed = 0;
const check = (name, actual, expected) => {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : `\n  expected ${JSON.stringify(expected)}\n  actual   ${JSON.stringify(actual)}`}`);
  failed += ok ? 0 : 1;
};

const pasted = `6. Inventory ₹2,40,000 and cost of goods sold ₹14,40,000. What is the inventory turnover and days? → 6 times, about 61 days
7. Invest $10,000 at 8% compounded annually for 3 years. What is the final amount? → $12,597.12
8. Asset cost €90,000, residual €10,000, life 8 years. What is the annual straight-line depreciation? → €10,000

Follow-ups (ask right after #5)
9. What if gross profit increases by 20%? → ₹4,32,000 → 36%
10. Show both ratios in a bar chart. (chart with 30% and 36%)`;
const split = splitQuestions(pasted);
check("list starting at 6, two lists, heading between -> 5 questions", split.length, 5);
check("keeps the full item text including the expected answer", split[1], "Invest $10,000 at 8% compounded annually for 3 years. What is the final amount? → $12,597.12");
check("chart request kept as its own question", split[4], "Show both ratios in a bar chart. (chart with 30% and 36%)");

check("labelled quoted items use the quote",
  splitQuestions('1. **Basic:** “Explain accrual accounting.”\n2. **Calc:** “Revenue is £250,000. Calculate margin.”'),
  ["Explain accrual accounting.", "Revenue is £250,000. Calculate margin."]);

check("a short quoted term does not replace the question",
  splitQuestions('1. What does “going concern” mean?\n2. What is materiality?'),
  ["What does “going concern” mean?", "What is materiality?"]);

check("a question with a list of options stays whole",
  splitQuestions("Which method should we use?\n\n1. FIFO\n2. Weighted average"),
  ["Which method should we use?\n\n1. FIFO\n2. Weighted average"]);

check("a single question is unchanged", splitQuestions("What is deferred tax?"), ["What is deferred tax?"]);

check("more than 10 items is not split",
  splitQuestions(Array.from({ length: 11 }, (_, i) => `${i + 1}. What is item ${i}?`).join("\n")).length, 1);

console.log(failed ? `\n${failed} FAILED` : "\nALL PASS");
process.exit(failed ? 1 : 0);
