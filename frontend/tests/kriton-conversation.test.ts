import { describe, expect, it } from "vitest";
import { conversationHistory } from "@/lib/kriton-conversation";
import type { Turn } from "@/lib/ask-kriton-storage";

function turn(text: string): Turn {
  return { submittedQuery: "Show monthly sales as a line chart.", result: { outcome: "answered", answer: { text } } } as Turn;
}

describe("complete chart context", () => {
  it("preserves JSON beyond the old 1,500 character cutoff", () => {
    const chart = "```chart\n" + JSON.stringify({ type: "line", title: "Sales", categories: Array.from({length:120},(_,i)=>`Month ${i}`), series:[{name:"Sales", data:Array.from({length:120},(_,i)=>i*100)}] }) + "\n```";
    const history = conversationHistory([turn("Introductory text.\n" + chart)]);
    expect(chart.length).toBeGreaterThan(1500);
    expect(history.at(-1)?.content).toBe(chart);
    expect(() => JSON.parse(history.at(-1)!.content.slice(9,-4))).not.toThrow();
  });
  it("omits oversized chart blocks whole instead of replaying partial data", () => {
    const text = "```chart\n" + JSON.stringify({ type:"line", categories:Array.from({length:500},(_,i)=>`Long category ${i}`),series:[{name:"Sales",data:Array.from({length:500},(_,i)=>i)}] }) + "\n```";
    const history = conversationHistory([turn(text)]);
    expect(history.at(-1)?.content).toContain("exceeds the conversation context limit");
    expect(history.at(-1)?.content).not.toContain("```chart");
  });
});

describe("exporting an answer from a file turn", () => {
  // "Export this answer as a Word document" got a new report: the answer came from
  // a turn with an attached file, and those answers are never replayed.
  const fileTurn = { submittedQuery: "Which document is the released FY2025 revenue?", attachments: [{ id: "d1" }],
    result: { outcome: "answered", answer: { text: "Released FY2025 revenue is 10,000 (page 1)." } } } as unknown as Turn;
  it("sends that answer when the request is to export it", () => {
    const history = conversationHistory([fileTurn], "Export this answer as a Word document");
    expect(history.at(-1)).toEqual({ role: "assistant", content: "Released FY2025 revenue is 10,000 (page 1)." });
  });
  it("still keeps file answers out of any other request", () => {
    expect(conversationHistory([fileTurn], "Now show it as a chart")).toEqual([]);
    expect(conversationHistory([fileTurn])).toEqual([]);
  });
});
