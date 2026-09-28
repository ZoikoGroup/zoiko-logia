/**
 * Checks lib/kriton-conversation.ts conversationHistory — follow-ups get the
 * recent questions plus the last answers (so "show the same data as a line
 * chart" has the data), never more than the backend's 12-message limit (more
 * would 422 every follow-up), and never document-derived turns.
 *
 *   node lib/__tests__/conversation-history.mjs
 */

import { conversationHistory } from "../kriton-conversation.ts";

const turn = (i, extra = {}) => ({
  id: `t${i}`, query: `q${i}`, submittedQuery: `question ${i}`, loading: false, error: null,
  result: { answer: { text: `answer ${i} ` + "x".repeat(3000) } }, ...extra,
});

let failed = 0;
const check = (name, ok) => { console.log(`${ok ? "PASS" : "FAIL"}  ${name}`); failed += ok ? 0 : 1; };

const many = conversationHistory(Array.from({ length: 20 }, (_, i) => turn(i)));
check("never exceeds 12 messages", many.length <= 12);
check("last two answers replayed", many.filter((m) => m.role === "assistant").length === 2 && many.at(-1).content.startsWith("answer 19"));
check("answers are truncated", many.filter((m) => m.role === "assistant").every((m) => m.content.length <= 1500));
check("keeps newest questions", many.some((m) => m.content === "question 19") && !many.some((m) => m.content === "question 0"));

const docs = conversationHistory([turn(1), turn(2, { attachments: [{ documentId: "d" }] })]);
check("document turns are not replayed", !docs.some((m) => m.content.includes("2")));

const pending = conversationHistory([turn(1), { ...turn(2), result: null }]);
check("unanswered turns are skipped", pending.length === 2 && pending[0].content === "question 1");

console.log(failed ? `\n${failed} FAILED` : "\nALL PASS");
process.exit(failed ? 1 : 0);
