import { describe, expect, it } from "vitest";
import type { AskKritonResponse } from "@/lib/api";
import { getFollowUpSuggestions } from "@/lib/follow-up-suggestions";
import { followUpContext } from "@/lib/kriton-conversation";

const original = "Global tax audits are rarely random.\n• Persistent losses: Local entities report recurring losses.";

describe("clarification actions", () => {
  it("offers explicit actions with the original material, never the assistant's question", () => {
    const result = {
      outcome: "clarification_required",
      next_action: {
        message: "What would you like me to do with this text?",
        suggestions: ["Check whether these claims are accurate.", "Explain this text in plain language.", "Rewrite this text for clarity."],
      },
    } as AskKritonResponse;
    const actions = getFollowUpSuggestions(result, original);
    expect(actions).toEqual(result.next_action!.suggestions);
    expect(actions).not.toContain(result.next_action!.message);
    expect(`${actions[0]} Context: ${followUpContext(original)}`).toContain(original);
  });

  it("does not turn missing-input questions or older clarification responses into prompts", () => {
    const result = { outcome: "clarification_required", next_action: { message: "Which country?" } } as AskKritonResponse;
    expect(getFollowUpSuggestions(result, original)).toEqual([]);
  });

  it("does not offer elaboration on refused or evidence-gap-only answers", () => {
    for (const outcome of ["refused", "unavailable", "limited_response", "rejected"]) {
      expect(getFollowUpSuggestions({ outcome } as AskKritonResponse, original)).toEqual([]);
    }
    expect(getFollowUpSuggestions({ outcome: "answered", answer: { text: "No evidence found.", completeness: "none" } } as AskKritonResponse, original)).toEqual([]);
    expect(getFollowUpSuggestions({ outcome: "answered", answer: { text: "I checked 4 factual claims in the text: 0 correct, 0 incorrect, 4 could not be verified." } } as AskKritonResponse, original)).toEqual([]);
  });
});
