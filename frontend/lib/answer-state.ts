// The state a Kriton response is shown in (ZL-ENG-AGT-01 §12). Every result
// and every failed request maps to exactly one, so the user always sees what
// happened rather than a raw HTTP code or a misleading answer.
import type { AskKritonResponse, VerificationBreakdown } from "@/lib/api";

export type AnswerState =
  | "answered"
  | "acknowledged"
  | "need-more-information"
  | "sources-unavailable"
  | "review-pending"
  | "refused"
  | "access-denied"
  | "service-unavailable"
  | "failed";

export type StateMessage = { state: AnswerState; title: string; detail: string };

/** Hide redundant boilerplate in saved answers; retain specific incompleteness. */
export function visibleAnswerLimitations(limitations: string[] = []): string[] {
  return [...new Set(limitations)].filter((text) =>
    !/^This response is for educational purposes only\. Consult a qualified professional\.$/.test(text)
    && !/^General guidance only\s*(?:—|:)/.test(text)
    && !/^No matching source was found in your governed source library;/.test(text),
  );
}

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
  // Say which failure it was: "temporarily unavailable" for a timeout, a
  // crash and an outage alike left no way to tell them apart.
  if (status === 504 || status === 408) {
    return {
      state: "service-unavailable",
      title: "Kriton took too long on this request",
      detail: "Nothing was answered because the processing time limit was reached. Try again, or ask about one part of the text at a time.",
    };
  }
  if (status === 500) {
    return {
      state: "service-unavailable",
      title: "Kriton hit an internal error",
      detail: "Nothing was answered. The error is in the backend log (\"Unhandled Ask Kriton stream failure\"). Please try again.",
    };
  }
  // The backend's own message names the cause ("database or network is
  // temporarily unavailable (reference 3f2a…)"); one generic line for a
  // restart, a database outage and a rate limit hid which one it was.
  const said = serverDetail?.trim();
  if (status === 429) {
    return {
      state: "service-unavailable",
      title: "Too many questions at once",
      detail: said || "Kriton accepts up to 30 questions a minute. Wait a moment and ask again.",
    };
  }
  if (status === null || status === 0) {
    return {
      state: "service-unavailable",
      title: "Could not reach the Kriton backend",
      detail: `Nothing was answered: the connection failed before a reply (the backend may be restarting or stopped).${said ? ` ${said}` : ""}`,
    };
  }
  if (UNAVAILABLE_STATUSES.has(status)) {
    return {
      state: "service-unavailable",
      title: "Kriton is temporarily unavailable",
      detail: `${said || "Nothing was answered. Please try again in a moment."} (HTTP ${status})`,
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
  if (["composition_failed", "provider_access_blocked", "provider_request_too_large", "provider_rate_limited", "request_budget_exhausted"].includes(result.next_action?.type ?? "")) return "service-unavailable";
  switch (result.outcome) {
    case "unavailable":
      return "service-unavailable";
    case "clarification_required":
      return "need-more-information";
    case "acknowledged":
      return "acknowledged";
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

// "Answered — calculated and verified" and "source grounded" overstated
// answers whose arithmetic was right but whose assumptions or sources were
// not (24 Oct 2026). A fully verified answer keeps its label; any other says
// what was verified.
export function verifiedLabel(label: string, verification?: VerificationBreakdown | null): string {
  if (!verification || !label.startsWith("Answered") || verification.overall === "fully_verified") return label;
  if (verification.arithmetic === "mismatch") return "Answered — a figure differs from the calculation";
  // Correct sums under an unverified treatment must not read as a verified
  // answer; a cited treatment is not a verified one either.
  const treatmentOpen = !!verification.treatment && verification.treatment !== "not_applicable";
  if (treatmentOpen && verification.arithmetic === "verified") {
    return "Answered — arithmetic verified; accounting treatment not verified";
  }
  if ((label === "Answered — calculated and verified" || verification.sources === "not_applicable")
      && verification.arithmetic === "verified") {
    return verification.assumptions === "stated"
      ? "Answered — arithmetic verified, assumptions not confirmed"
      : "Answered — arithmetic verified";
  }
  if (label === "Answered — source grounded" && verification.sources === "partial") return "Answered — partly source-verified";
  return label;
}

const PART_TEXT = {
  arithmetic: { verified: "verified", mismatch: "a figure differs from the calculation" },
  sources: { verified: "verified", partial: "partly verified", unsupported: "not source-verified" },
  assumptions: { confirmed: "your figures only", stated: "stated, not confirmed" },
  treatment: { cited_checks_passed: "cited; evidence checks passed", not_verified: "not verified", issue_found: "needs review" },
} as const;

/** One line naming each part that applies: "Arithmetic: verified · Assumptions: stated, not confirmed". */
export function verificationSummary(verification?: VerificationBreakdown | null): string | null {
  if (!verification) return null;
  const parts: string[] = [];
  if (verification.arithmetic !== "not_applicable") parts.push(`Arithmetic: ${PART_TEXT.arithmetic[verification.arithmetic]}`);
  if (verification.sources !== "not_applicable") parts.push(`Sources: ${PART_TEXT.sources[verification.sources]}`);
  if (verification.assumptions !== "not_applicable") parts.push(`Assumptions: ${PART_TEXT.assumptions[verification.assumptions]}`);
  if (verification.treatment && verification.treatment !== "not_applicable") {
    parts.push(`Accounting treatment: ${PART_TEXT.treatment[verification.treatment]}`);
  }
  return parts.length ? parts.join(" · ") : null;
}
