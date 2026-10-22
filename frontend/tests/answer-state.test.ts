import { describe, expect, it } from "vitest";
import { ACCESS_DENIED_TEXT, stateForError, stateForResult, suppliedAnswerLabel, visibleAnswerLimitations } from "@/lib/answer-state";

const answer = (limitations: string[] = []) => ({ text: "", citations: [], limitations });

it("hides repeated boilerplate while retaining concrete missing-work notices", () => {
  const incomplete = "Incomplete answer: the current exchange rate could not be retrieved.";
  expect(visibleAnswerLimitations([
    "General guidance only — not advice on your or your client's specific matter. Consult a qualified professional before acting.",
    "No matching source was found in your governed source library; this answer is based on live data and web sources. Verify figures against the official source.",
    incomplete, incomplete,
  ])).toEqual([incomplete]);
});

describe("answer states (ZL-ENG-AGT-01 §12)", () => {
  it("never leaks server detail on an access refusal", () => {
    const shown = stateForError(403, "Source 'Client X tax file' belongs to tenant t2");
    expect(shown.state).toBe("access-denied");
    expect(shown.detail).toBe(ACCESS_DENIED_TEXT);
    expect(JSON.stringify(shown)).not.toContain("Client X");
  });

  it("shows outages and timeouts as service-unavailable, not as an answer", () => {
    for (const status of [null, 503, 504, 429]) expect(stateForError(status).state).toBe("service-unavailable");
    expect(stateForError(422, "Question too long").detail).toBe("Question too long");
  });

  it("maps every result outcome to one state", () => {
    expect(stateForResult({ outcome: "clarification_required", next_action: null, answer: null })).toBe("need-more-information");
    expect(stateForResult({ outcome: "escalated", next_action: null, answer: null })).toBe("review-pending");
    expect(stateForResult({ outcome: "refused", next_action: null, answer: null })).toBe("refused");
    expect(stateForResult({ outcome: "refused", next_action: { type: "composition_failed", message: "" }, answer: null })).toBe("service-unavailable");
    expect(stateForResult({ outcome: "refused", next_action: { type: "provider_access_blocked", message: "" }, answer: null })).toBe("service-unavailable");
    expect(stateForResult({ outcome: "refused", next_action: { type: "provider_request_too_large", message: "" }, answer: null })).toBe("service-unavailable");
    expect(stateForResult({ outcome: "unavailable", next_action: null, answer: null })).toBe("service-unavailable");
    expect(stateForResult({ outcome: "unavailable", next_action: { type: "provider_rate_limited", message: "" }, answer: null })).toBe("service-unavailable");
    expect(stateForResult({ outcome: "unavailable", next_action: { type: "request_budget_exhausted", message: "" }, answer: null })).toBe("service-unavailable");
    expect(stateForResult({ outcome: "answered", next_action: null, answer: answer(["No factual answer was verified against the sources."]) })).toBe("sources-unavailable");
    expect(stateForResult({ outcome: "answered", next_action: null, answer: answer() })).toBe("answered");
  });
});


describe("supplied-data answer labels", () => {
  it("distinguishes arithmetic, chart formatting and suitability explanations", () => {
    expect(suppliedAnswerLabel({ ...answer(), response_kind: "calculation" })).toBe("Answered — calculated from supplied figures");
    expect(suppliedAnswerLabel({ ...answer(), response_kind: "chart" })).toBe("Answered — from figures you supplied");
    expect(suppliedAnswerLabel({ ...answer(), response_kind: "chart_explanation" })).toBe("Answered — chart suitability explained");
  });

  it("does not claim verification for older supplied-data responses", () => {
    expect(suppliedAnswerLabel({ ...answer(), computed_from_question: true })).toBe("Answered — from figures in this conversation");
    expect(suppliedAnswerLabel(answer())).toBeNull();
    expect(suppliedAnswerLabel(null)).toBeNull();
  });
});

describe("failed request says which failure it was", () => {
  it("names a timeout and an internal error separately", () => {
    expect(stateForError(504).title).toBe("Kriton took too long on this request");
    expect(stateForError(500).title).toBe("Kriton hit an internal error");
    expect(stateForError(503).title).toBe("Kriton is temporarily unavailable");
  });
});
