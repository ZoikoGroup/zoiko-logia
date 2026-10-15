import { describe, expect, it } from "vitest";
import { ApiError, describeDetail } from "@/lib/api";
import { conversationHistory, followUpSubject, splitQuestions } from "@/lib/kriton-conversation";
import type { Turn } from "@/lib/ask-kriton-storage";

function answered(query: string, text: string): Turn {
  return { submittedQuery: query, result: { outcome: "answered", answer: { text } } } as Turn;
}

describe("follow-up history", () => {
  it("replays the latest answer even when it has no figures, so 'this' has content", () => {
    const history = conversationHistory([answered("the relationship between IFRS 18 and IAS 1", "IFRS 18 supersedes IAS 1 [REF-1].")]);
    expect(history.at(-1)).toEqual({ role: "assistant", content: "IFRS 18 supersedes IAS 1 [REF-1]." });
  });

  it("stays within the backend's 12-message limit", () => {
    const turns = Array.from({ length: 20 }, (_, i) => answered(`q${i}`, `Revenue 100, 200, 300 in year ${i}.`));
    expect(conversationHistory(turns).length).toBeLessThanOrEqual(12);
  });
});

describe("API error text", () => {
  it("turns a FastAPI validation list into readable text instead of [object Object]", () => {
    const detail = [{ loc: ["body", "previous_query"], msg: "String should have at most 2000 characters", type: "string_too_long" }];
    expect(new ApiError(422, detail).message).toBe("previous_query: String should have at most 2000 characters");
    expect(new ApiError(422, detail).message).not.toContain("[object Object]");
  });

  it("keeps string details and reads object messages", () => {
    expect(describeDetail("Only an Admin can create projects.")).toBe("Only an Admin can create projects.");
    expect(describeDetail({ message: "Too many requests" })).toBe("Too many requests");
    expect(describeDetail(null)).toBe("The request could not be completed.");
  });
});

describe("follow-up context", () => {
  it("keeps the original subject instead of nesting Context: layers", () => {
    const first = `Explain this with a grounded example. Context: ${followUpSubject("the relationship between IFRS 18 and IAS 1")}`;
    const second = `Summarize this as a checklist. Context: ${followUpSubject(first)}`;
    expect(second).toBe("Summarize this as a checklist. Context: the relationship between IFRS 18 and IAS 1");
  });

  it("shortens a long pasted subject at a word boundary", () => {
    const subject = followUpSubject("IFRS 18 presentation ".repeat(60));
    expect(subject.length).toBeLessThanOrEqual(501);
    expect(subject.endsWith("…")).toBe(true);
  });
});

describe("pasted review", () => {
  it("is sent as one message, not split into its numbered points", () => {
    const pasted = [
      "# Critical Analysis: IFRS Financial Statement Presentation Under IAS 1 and IFRS 18",
      "## 3. Critical Issue 2: The Complete Set of Financial Statements",
      "1. Statement of Financial Position.",
      "2. Statement of Profit or Loss and Other Comprehensive Income.",
      "### What should be added?",
      "1. Reporting-framework and effective-date awareness.",
      "2. Configurable statement presentation based on the applicable standard.",
      "comment on the above",
    ].join("\n\n");
    expect(splitQuestions(pasted)).toEqual([pasted]);
  });
});

describe("follow-ups after a pasted review", () => {
  const pasted = "# Critical Analysis: IFRS Financial Statement Presentation Under IAS 1 and IFRS 18\n\n## 1. Overall Assessment\n\n"
    + "IFRS 18 replaces IAS 1. A reclassification with a material effect needs a third balance sheet. ".repeat(30)
    + "\n\ncheck if it is correct.";

  it("uses the pasted document's title as the follow-up context", () => {
    expect(followUpSubject(pasted)).toBe("Critical Analysis: IFRS Financial Statement Presentation Under IAS 1 and IFRS 18");
  });

  it("suggests review follow-ups, not journal-entry ones, for a claim-by-claim review", async () => {
    const { getFollowUpSuggestions } = await import("@/lib/follow-up-suggestions");
    const result = { outcome: "answered", answer: { text: "I checked 15 factual claims in the text, each against sources searched for it: 9 correct." } };
    const suggestions = getFollowUpSuggestions(result as never, pasted);
    expect(suggestions).toContain("Summarize the confirmed rules as a checklist.");
    expect(suggestions.join(" ")).not.toMatch(/correcting entries|P&L and AR/);
  });
});

describe("which questions use the attached file", () => {
  it("a standards or self-contained question is not limited to an attached file", async () => {
    const { usesAttachedFile } = await import("@/lib/kriton-conversation");
    // After attaching balance_sheet.pdf, these were searched only in the balance sheet and escalated.
    expect(usesAttachedFile("Summarize the confirmed rules as a checklist. Context: Critical Analysis: IFRS Financial Statement Presentation Under IAS 1 and IFRS 18")).toBe(false);
    expect(usesAttachedFile("A shop bought stock for £18,000 and sold it for £25,500. What's the markup and the margin?")).toBe(false);
    // Questions about the file keep the file-only safeguard.
    expect(usesAttachedFile("give the financial statement")).toBe(true);
    expect(usesAttachedFile("Using the attached balance sheet, what is the current ratio?")).toBe(true);
    expect(usesAttachedFile("Does this report comply with IAS 1?")).toBe(true);
    expect(usesAttachedFile("What was Apex's revenue last year?")).toBe(true);   // never answered from another "Apex"
  });

  it("review follow-ups only offer what the table holds", async () => {
    const { getFollowUpSuggestions } = await import("@/lib/follow-up-suggestions");
    const clean = { outcome: "answered", answer: { text: "I checked 13 factual claims in the text, each against sources searched for it: 10 correct, 0 incorrect, 3 could not be verified." } };
    expect(getFollowUpSuggestions(clean as never, "x").join(" ")).not.toMatch(/incorrect or partly/);
    const mixed = { outcome: "answered", answer: { text: "I checked 5 factual claims in the text, each against sources searched for it: 3 correct, 1 partly confirmed, 1 incorrect, 0 could not be verified." } };
    expect(getFollowUpSuggestions(mixed as never, "x")[0]).toMatch(/incorrect or partly/);
  });
});
