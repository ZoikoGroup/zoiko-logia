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
const ANSWER_CHARS = 1500;
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
  return new Set(withFigures.slice(-ANSWERS_REPLAYED));
}

export function conversationHistory(turns: Turn[]): ConversationMessage[] {
  // Document-derived answers are not replayed as evidence on a later turn.
  // A document must be selected and authorized again before being consulted.
  const recent = turns.filter((turn) => turn.result && !turn.attachments?.length)
    .slice(-(MAX_HISTORY_MESSAGES - ANSWERS_REPLAYED));
  const replayed = answersToReplay(recent);
  const messages: ConversationMessage[] = [];
  recent.forEach((turn) => {
    messages.push({ role: "user", content: turn.submittedQuery.slice(0, 4000) });
    const answer = turn.result?.answer?.text?.trim();
    if (answer && replayed.has(turn)) {
      messages.push({ role: "assistant", content: answer.slice(0, ANSWER_CHARS) });
    }
  });
  return messages;
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
  const outsideAsksSomething = tree.children.some(
    (node) => node.type === "paragraph" && toString(node).includes("?"),
  );
  if (outsideAsksSomething) return [text];

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
