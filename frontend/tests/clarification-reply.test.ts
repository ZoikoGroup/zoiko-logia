import { describe, expect, it } from "vitest";
import { openClarification } from "@/lib/clarification-reply";
import { stateForResult } from "@/lib/answer-state";
import { getFollowUpSuggestions } from "@/lib/follow-up-suggestions";
import type { AskKritonResponse } from "@/lib/api";

const turn = (submittedQuery: string, outcome: string | null, query_id = `q-${submittedQuery.length}`, question = "") => ({
  submittedQuery,
  result: outcome ? ({ outcome, query_id, next_action: { message: question } } as Pick<AskKritonResponse, "outcome" | "query_id">
    & { next_action: { message: string } }) : null,
});
const TIMING = "To calculate the lease I need: (1) whether payments are made in advance or in arrears.";

describe("Replying to Kriton's question (stage 2)", () => {
  it("replies to the latest question with the request it clarifies", () => {
    const open = openClarification([
      turn("What is IFRS 16?", "answered"),
      turn("Calculate VAT payable on sales £100,000.", "clarification_required", "q-vat"),
    ]);
    expect(open).toEqual({ replyTo: "q-vat", request: "Calculate VAT payable on sales £100,000.", cycle: 1 });
  });

  it("carries the whole exchange when Kriton asked again", () => {
    const open = openClarification([
      turn("Calculate the lease liability.", "clarification_required", "q-1", "I need the payment, rate, term and timing."),
      turn("£10,000 a year at 5% for 3 years.", "clarification_required", "q-2", TIMING),
    ]);
    expect(open).toEqual({ replyTo: "q-2", request: "Calculate the lease liability.\n£10,000 a year at 5% for 3 years.", cycle: 2 });
  });

  it("does not carry a reply after which Kriton asked the same question again", () => {
    // The 28 Oct live test: the ambiguous reply kept every later reply ambiguous.
    const lease = "Calculate the lease liability for payments of £10,000 a year at 5% for 3 years.";
    const open = openClarification([
      turn(lease, "clarification_required", "q-1", TIMING),
      turn('"in advance or in arrears?"', "clarification_required", "q-2", TIMING),
    ]);
    expect(open).toEqual({ replyTo: "q-2", request: lease, cycle: 2 });
  });

  it("never treats the message after an acknowledgement or an answer as a reply", () => {
    expect(openClarification([turn("We are a UK company.", "acknowledged")])).toBeNull();
    expect(openClarification([turn("Calculate VAT.", "clarification_required"), turn("All standard-rated.", "answered")])).toBeNull();
    expect(openClarification([])).toBeNull();
  });

  it("keeps the request within the backend's limit", () => {
    const open = openClarification([turn("x".repeat(5000), "clarification_required", "q-long")]);
    expect(open?.request).toHaveLength(4000);
  });
});

describe("The acknowledged outcome", () => {
  const ack = {
    outcome: "acknowledged",
    next_action: { type: "acknowledge_context", message: "Noted — I'll use this.", suggestions: ["Explain the accounting treatment"] },
    answer: null,
  } as unknown as AskKritonResponse;

  it("is its own state, not a request for more information", () => {
    expect(stateForResult(ack)).toBe("acknowledged");
  });

  it("offers the acknowledgement's own actions", () => {
    expect(getFollowUpSuggestions(ack, "We are a UK company.")).toEqual(["Explain the accounting treatment"]);
  });
});
