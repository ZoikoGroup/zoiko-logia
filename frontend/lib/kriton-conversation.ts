import { unified } from "unified";
import remarkParse from "remark-parse";
import { toString } from "mdast-util-to-string";
import type { Turn } from "@/lib/ask-kriton-storage";

export type ConversationMessage = { role: "user" | "assistant"; content: string };

/** Backend limit (AskKritonRequest.conversation_history max_length). */
const MAX_HISTORY_MESSAGES = 12;
/** Earlier answers replayed so "show the same data as a line chart" has the
 * data: live figures live in the answer, not in the question that asked. */
const ANSWERS_REPLAYED = 2;
const ANSWER_CHARS = 4000;
/** Several figures, not just a year or one number in a sentence. */
const FIGURES = /\d[\d,.]*/g;

/** The answers worth replaying: the most recent ones carrying figures. A
 * "couldn't find it" reply or a refusal has nothing to chart, and replaying
 * only the last two turns left "Give me a chart" with no data to use. */
function answersToReplay(recent: Turn[]): Set<Turn> {
  const withFigures = recent.filter((turn) => {
    const answer = turn.result?.answer?.text ?? "";
    return turn.result?.outcome !== "refused" && (answer.match(FIGURES)?.length ?? 0) >= 3;
  });
  const replayed = new Set(withFigures.slice(-ANSWERS_REPLAYED));
  // The latest real answer is always replayed: "Explain this with an example"
  // or "Summarize this as a checklist" is about it, and an answer without
  // figures ("IFRS 18 supersedes IAS 1…") was never sent, so "this" meant
  // nothing to the model.
  const latestAnswered = [...recent].reverse().find((turn) => turn.result?.outcome === "answered" && turn.result?.answer?.text?.trim());
  if (latestAnswered) replayed.add(latestAnswered);
  return replayed;
}

/** Preserve a complete chart block instead of cutting JSON mid-dataset.
 * The API bounds each message to 4,000 characters; oversized charts are
 * omitted whole so the backend cannot accidentally reuse a partial series. */
function replayAnswer(answer: string): string {
  const charts = [...answer.matchAll(/```chart\s*\n[\s\S]*?```/g)];
  if (charts.length) {
    const chart = charts.at(-1)![0];
    if (chart.length <= ANSWER_CHARS) return chart;
    return "The previous chart dataset exceeds the conversation context limit. Ask the user to supply the dataset again; do not infer missing observations.";
  }
  // A truncated table would appear complete to the chart parser.
  if (answer.length <= ANSWER_CHARS) return answer;
  return "The preceding answer exceeds the conversation context limit. Ask for the relevant dataset rather than treating a truncated table as complete.";
}

export function conversationHistory(turns: Turn[]): ConversationMessage[] {
  // Document-derived answers are not replayed as evidence on a later turn.
  // A document must be selected and authorized again before being consulted.
  const recent = turns.filter((turn) => turn.result && !turn.attachments?.length)
    // Room for the figure answers plus the latest answer (answersToReplay).
    .slice(-(MAX_HISTORY_MESSAGES - ANSWERS_REPLAYED - 1));
  const replayed = answersToReplay(recent);
  const messages: ConversationMessage[] = [];
  recent.forEach((turn) => {
    messages.push({ role: "user", content: turn.submittedQuery.slice(0, 4000) });
    const answer = turn.result?.answer?.text?.trim();
    if (answer && replayed.has(turn)) {
      messages.push({ role: "assistant", content: replayAnswer(answer) });
    }
  });
  return messages;
}

const FOLLOW_UP_CONTEXT_MARKER = " Context: ";
const FOLLOW_UP_SUBJECT_CHARS = 500;

/** The original subject of a follow-up chain. A follow-up of a follow-up used
 * to nest: "Summarize this as a checklist. Context: Explain this with a
 * grounded example. Context: …" — every click added a layer, and the search
 * ran on the pile of instructions instead of the topic. */
/** Backend websearch.LONG_INPUT_CHARS: longer is pasted material, not a question. */
const PASTED_MATERIAL_CHARS = 1500;

/** Submission context must retain every original task and qualifier.
 * followUpSubject is a short topic preview and must not be sent as the task. */
export function followUpContext(query: string): string {
  return query.split(FOLLOW_UP_CONTEXT_MARKER).at(-1)!.trim();
}

export function followUpSubject(query: string): string {
  let subject = followUpContext(query);
  if (subject.length > PASTED_MATERIAL_CHARS) {
    // A pasted document's topic is its title, not its first 500 characters
    // ("# Critical Analysis: … ## 1. Overall Assessment **Verdict: …").
    const lines = subject.split("\n").map((line) => line.replace(/^[#>*\s]+|[*\s]+$/g, "")).filter(Boolean);
    subject = lines[0] ?? subject;
  }
  if (subject.length <= FOLLOW_UP_SUBJECT_CHARS) return subject;
  const cut = subject.slice(0, FOLLOW_UP_SUBJECT_CHARS);
  return `${cut.slice(0, cut.lastIndexOf(" ") > 0 ? cut.lastIndexOf(" ") : cut.length)}…`;
}

const MAX_SPLIT_QUESTIONS = 10;
const QUESTION_START =
  /^(?:what|how|why|when|which|who|where|is|are|can|could|should|do|does|explain|compare|calculate|compute|summari[sz]e|list|define|describe|show|plot|draw|chart|convert|find|prepare|create|give|help|analy[sz]e|review|revenue\b|pie chart\b|bar chart\b|line chart\b)/i;

/**
 * Split a pasted set of numbered questions into separate questions, so each
 * gets its own full answer \u2014 as ChatGPT/Claude answer every question in one
 * message. Handles lists that start at any number, several numbered lists
 * separated by headings ("Follow-ups\u2026"), bold item labels, and items that
 * carry an expected answer ("\u2026 days? \u2192 6 times"). Returns [text] unchanged
 * when the message is not clearly a question list \u2014 e.g. prose outside the
 * lists asks its own question, which a split would silently drop.
 */
export function splitQuestions(text: string): string[] {
  // Clipboard text sometimes flattens a Markdown list with bold item labels.
  // A numbered line directly under plain text ("Follow-ups…\n9. What if…")
  // cannot start a list in CommonMark unless it is "1.", so it would be folded
  // into that paragraph; a blank line before each numbered line prevents it.
  const normalized = text
    .replace(/\s+(\d{1,2}[.)]\s+\*\*)/g, "\n$1")
    .replace(/([^\n])\n(\d{1,2}[.)]\s)/g, "$1\n\n$2");
  const tree = unified().use(remarkParse).parse(normalized);
  const lists = tree.children.filter((node) => node.type === "list" && node.ordered);
  if (!lists.length) return [text];
  // Outside text can contain shared figures or instructions without a "?".
  // Splitting it away changes the actual request before the backend sees it.
  const hasSharedContext = tree.children.some((node) => {
    if (node.type === "list" && node.ordered) return false;
    const content = toString(node).trim();
    if (!content) return node.type !== "paragraph" && node.type !== "heading";
    // Only purely structural labels may be discarded when splitting a batch.
    return !/^(?:questions|follow[- ]ups?(?:\s*\(ask right after #\d+\))?)$/i.test(content);
  });
  if (hasSharedContext) return [text];

  const items = lists.flatMap((list) => (list.type === "list" ? list.children : []));
  if (items.length < 2 || items.length > MAX_SPLIT_QUESTIONS) return [text];
  const questions = items.map((item) => {
    const content = toString(item).trim();
    // "**Calculation:** \u201cRevenue is \u2026\u201d" \u2014 the quote IS the question. A short
    // quoted term inside a question ("What does \u201cgoing concern\u201d mean?") is not.
    const quoted = content.match(/[\u201c"]([^\u201d"]+)[\u201d"]/)?.[1]?.trim();
    return quoted && quoted.length >= content.length * 0.6 ? quoted : content;
  });
  return questions.every((question) => QUESTION_START.test(question) || question.includes("?"))
    ? questions : [text];
}

// ── Does a question use the file attached to the chat? ─────────────────────
// Attaching a file limited EVERY later question in the chat to that file, so
// "Summarize the confirmed rules (IAS 1, IFRS 18) as a checklist", asked after
// attaching balance_sheet.pdf, searched only the balance sheet and was
// escalated for "no eligible sources". A question that names the file keeps
// the file-only scope; one that names an accounting standard or carries all
// its own figures, and does not mention the file, is not about it. Everything
// else keeps the file-only safeguard ("What was Apex's revenue?" with Apex's
// report attached must not be answered from another Apex on the web).
// File words always count; ordinary nouns ("statement", "report", "sheet")
// only when the question points at one ("the financial statement", "this
// report") — a topic title such as "IFRS Financial Statement Presentation"
// is not a reference to the attached file.
const MENTIONS_FILE = new RegExp(
  "\\b(?:attach\\w*|upload\\w*|pdf|csv|xlsx|spreadsheet|workbook|these (?:figures|numbers|amounts|accounts)|in (?:it|there))\\b"
  + "|\\b(?:the|this|that|my|our|your|its|attached|uploaded)\\s+(?:\\w+\\s+){0,2}"
  + "(?:document|file|report|statements?|sheet|balance sheet|trial balance|ledger|invoices?|accounts|p\\s*&\\s*l)\\b",
  "i",
);
const NAMES_STANDARD = /\b(?:IFRS|IAS|IFRIC|GAAP|ASC|FRS|Ind\s?AS|ISA)\s?\d*\b/;
const OWN_FIGURES = /[£$€₹]\s?\d|\d[\d,]*(?:\.\d+)?\s*%/g;

export function usesAttachedFile(query: string): boolean {
  const text = query.split(FOLLOW_UP_CONTEXT_MARKER)[0] + " " + (query.split(FOLLOW_UP_CONTEXT_MARKER)[1] ?? "");
  if (MENTIONS_FILE.test(text)) return true;
  if (NAMES_STANDARD.test(text)) return false;
  return (text.match(OWN_FIGURES)?.length ?? 0) < 2;
}
