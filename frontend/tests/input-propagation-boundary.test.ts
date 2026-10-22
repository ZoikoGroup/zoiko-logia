import { afterEach, describe, expect, it, vi } from "vitest";
import { splitQuestions } from "@/lib/kriton-conversation";
import { askKritonStream } from "@/lib/api";

// Existing supplied wholesale figures. This is a client-mechanism regression,
// not a substitute for the missing latest £1.2m statement's original payload.
const shared = "Revenue £960,000, returns £24,000, opening inventory £85,000, purchases £570,000, closing inventory £95,000.";
const message = `${shared}\n\n1. Calculate net sales.\n2. Calculate cost of goods sold and gross profit.`;

afterEach(() => vi.unstubAllGlobals());

describe("financial context at the submission boundary", () => {
  it("keeps shared inputs and numbered deliverables in one submission", () => {
    expect(splitQuestions(message)).toEqual([message]);
  });

  it("serializes the complete selected question without dropping its figures", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ type: "result", data: { query_id: "synthetic-boundary", outcome: "answered" } })+"\n",
      { status: 200, headers: { "Content-Type": "application/x-ndjson" } },
    ));
    vi.stubGlobal("fetch", fetchMock);
    const questions = splitQuestions(message);
    expect(questions).toHaveLength(1);
    await askKritonStream("synthetic-not-a-credential", { query: questions[0], conversation_id: "synthetic-boundary" }, "synthetic-idempotency", () => {});
    const sent = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(sent.query).toBe(message);
  });

  it("does not discard shared table data or instructions after a numbered list", () => {
    const table = "| Metric | Amount |\n| --- | --- |\n| Revenue | £960,000 |\n\n1. Calculate net sales.\n2. Explain the figures.";
    expect(splitQuestions(table)).toEqual([table]);
    const tail = "1. Calculate gross profit from revenue £100 and COGS £60.\n2. Explain gross margin.\n\nUse GBP and finish with a management question.";
    expect(splitQuestions(tail)).toEqual([tail]);
  });

  it("still splits independent self-contained question lists", () => {
    expect(splitQuestions("1. What is deferred tax?\n2. What is accrual accounting?")).toEqual(["What is deferred tax?", "What is accrual accounting?"]);
  });
});
