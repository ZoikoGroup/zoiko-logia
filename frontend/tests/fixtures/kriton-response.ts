import type { AskKritonResponse } from "@/lib/api";

/** Synthetic public contract; no model accuracy or actual audit identity implied. */
export function syntheticKritonResponse(overrides: Partial<AskKritonResponse> = {}): AskKritonResponse {
  return {
    query_id: "synthetic-stream", correlation_id: "synthetic-correlation",
    outcome: "answered", route: "CALCULATION",
    safety: { risk_level: "LOW", policy_state: "allowed", disclaimer_required: false },
    confidence_state: "sufficient", source_bundle: null,
    answer: { text: "2 + 2 = 4", citations: [], limitations: [], completeness: "complete" },
    next_action: null, artifacts: [], audit_reference: { audit_chain_id: "synthetic-audit" },
    ...overrides,
  };
}
