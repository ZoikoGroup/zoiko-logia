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

export function followUpSubject(query: string): string {
  let subject = query.split(FOLLOW_UP_CONTEXT_MARKER).at(-1)!.trim();
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
