// The state a Kriton response is shown in (ZL-ENG-AGT-01 §12). Every result
// and every failed request maps to exactly one, so the user always sees what
// happened rather than a raw HTTP code or a misleading answer.
import type { AskKritonResponse } from "@/lib/api";

export type AnswerState =
  | "answered"
  | "need-more-information"
  | "sources-unavailable"
  | "review-pending"
  | "refused"
  | "access-denied"
  | "service-unavailable"
  | "failed";

export type StateMessage = { state: AnswerState; title: string; detail: string };

// Exact copy required by §12 for access refusals: no snippet, no detail.
export const ACCESS_DENIED_TEXT = "This information is not available to your account.";

const UNAVAILABLE_STATUSES = new Set([408, 429, 500, 502, 503, 504]);

/** A request that failed before Kriton produced a result. `status` is null
 * for a network failure. Server detail is shown only where it cannot leak
 * protected content (never for an access refusal). */
export function stateForError(status: number | null, serverDetail?: string | null): StateMessage {
  if (status === 401 || status === 403) {
    return { state: "access-denied", title: "Not available", detail: ACCESS_DENIED_TEXT };
  }
  if (status === null || UNAVAILABLE_STATUSES.has(status)) {
    return {
      state: "service-unavailable",
      title: "Kriton is temporarily unavailable",
      detail: "Nothing was answered. Please try again in a moment.",
    };
  }
  return {
    state: "failed",
    title: "Kriton could not complete this request",
    detail: serverDetail?.trim() || "Nothing was answered. Please try again or rephrase the question.",
  };
}

/** A result Kriton returned. */
export function stateForResult(result: Pick<AskKritonResponse, "outcome" | "next_action" | "answer">): AnswerState {
  if (result.next_action?.type === "composition_failed") return "service-unavailable";
  switch (result.outcome) {
    case "clarification_required":
      return "need-more-information";
    case "escalated":
      return "review-pending";
    case "refused":
    case "rejected":
      return "refused";
  }
  const limitations = result.answer?.limitations ?? [];
  if (limitations.some((l) => l.includes("No factual answer was verified"))) return "sources-unavailable";
  return result.answer ? "answered" : "failed";
}

/** A route can format data without performing a calculation. Prefer the
 * explicit answer kind, and conservatively label older supplied-data replies. */
export function suppliedAnswerLabel(answer: AskKritonResponse["answer"]): string | null {
  switch (answer?.response_kind) {
    case "chart_explanation": return "Answered — chart suitability explained";
    case "chart": return "Answered — from figures you supplied";
    case "calculation": return "Answered — calculated from supplied figures";
  }
  return answer?.computed_from_question ? "Answered — from figures in this conversation" : null;
}
