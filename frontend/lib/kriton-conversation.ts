import { unified } from "unified";
import remarkParse from "remark-parse";
import { toString } from "mdast-util-to-string";
import type { Turn } from "@/lib/ask-kriton-storage";

export type ConversationMessage = { role: "user" | "assistant"; content: string };

export function conversationHistory(turns: Turn[]): ConversationMessage[] {
  // Document-derived answers are not replayed as evidence on a later turn.
  // A document must be selected and authorized again before being consulted.
  return turns.filter((turn) => turn.result && !turn.attachments?.length)
    .slice(-12)
    .map((turn) => ({ role: "user", content: turn.submittedQuery.slice(0, 4000) }));
}

export function splitQuestions(text: string): string[] {
  // Clipboard text sometimes flattens a Markdown list with bold item labels.
  const normalized = text.replace(/\s+(\d{1,2}[.)]\s+\*\*)/g, "\n$1");
  const tree = unified().use(remarkParse).parse(normalized);
  const lists = tree.children.filter((node) => node.type === "list" && node.ordered && node.start === 1);
  if (lists.length !== 1 || lists[0].type !== "list") return [text];
  const items = lists[0].children;
  if (items.length < 2 || items.length > 10) return [text];
  const questions = items.map((item) => {
    const content = toString(item).trim();
    const quoted = content.match(/[\u201c"]([^\u201d"]+)[\u201d"]/);
    return quoted?.[1]?.trim() || content;
  });
  const questionIntent = /^(?:what|how|why|when|which|can|could|should|explain|compare|calculate|compute|summari[sz]e|list|define|describe|show|help|give|revenue\b|pie chart\b)/i;
  return questions.every((question) => questionIntent.test(question) || question.endsWith("?"))
    ? questions : [text];
}
