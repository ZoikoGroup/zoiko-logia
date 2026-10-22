/**
 * Safety Service API client for the frontend.
 *
 * Calls the configured backend (NEXT_PUBLIC_API_URL, same as lib/api.ts).
 */

import { fetchWithSession } from "@/lib/auth-fetch";
import { getCurrentAccessToken } from "@/lib/session-token";
import { impersonationHeaders } from "@/lib/impersonation";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8010/api/v1";
const BACKEND = `${API_URL}/safety`;

// ─── Types ──────────────────────────────────────────────────────────────────

export type Escalation = {
  id: string;
  query_id: string;
  query_text: string;
  topic: string;
  risk_level: string;
  restricted_sub_class: string | null;
  jurisdiction: string;
  owner: string | null;
  reviewer_role: string | null;
  sla_deadline: string | null;
  status: string;
  route_reason: string | null;
  detail: string | null;
  reviewer_decision: string | null;
  reviewer_id: string | null;
  created_at: string | null;
  resolved_at: string | null;
};

export type SafetyEvent = {
  id: number;
  event_type: string;
  query_id: string | null;
  payload: Record<string, unknown>;
  timestamp: string | null;
};

// ─── Backend API Calls ──────────────────────────────────────────────────────

async function tryBackend<T>(path: string, options?: RequestInit, required = false): Promise<T | null> {
  try {
    const res = await fetchWithSession(`${BACKEND}${path}`, getCurrentAccessToken(), {
      ...options,
      headers: {
        ...options?.headers,
        "Content-Type": "application/json",
        ...impersonationHeaders(),
        Authorization: `Bearer ${getCurrentAccessToken()}`,
      },
    });
    if (!res.ok) {
      if (required && res.status === 401) throw new Error("Session expired — please sign in again.");
      if (required) {
        const body = await res.json().catch(() => null);
        throw new Error(typeof body?.detail === "string" ? body.detail : "Safety action failed. Please try again.");
      }
      return null;
    }
    return (await res.json()) as T;
  } catch (error) {
    if (required) throw error;
    return null;
  }
}

// ─── Public API ─────────────────────────────────────────────────────────────

export async function validateOutput(text: string): Promise<{
  is_safe: boolean;
  violations: { phrase: string; category: string; severity: string }[];
  cleaned_text: string;
}> {
  const remote = await tryBackend<{
    is_safe: boolean;
    violations: { phrase: string; category: string; severity: string }[];
    cleaned_text: string;
  }>("/validate-output", {
    method: "POST",
    body: JSON.stringify({ text }),
  });
  if (remote) return remote;

  return {
    is_safe: false,
    violations: [{ phrase: "Validation unavailable", category: "Service unavailable", severity: "hard" }],
    cleaned_text: "",
  };
}

// Lists throw on failure (required) so a backend error shows as an error,
// never as an empty ledger.
export async function getEscalations(): Promise<Escalation[]> {
  return (await tryBackend<Escalation[]>("/escalations", undefined, true))!;
}

export type EscalationStats = {
  total: number;
  pending: number;
  under_review: number;
  resolved: number;
  refused: number;
  escalated: number;
  over_sla: number;
};

export type SafetyOverride = {
  id: string;
  actor_id: string;
  authority_role: string;
  original_route: string;
  new_route: string;
  scope: string;
  reason: string;
  created_at: string;
  expires_at: string;
  post_action_review_due: string | null;
  is_active: boolean;
};

/** The reviewer recorded is the signed-in user (set by the backend). */
export async function actOnEscalation(
  caseId: string,
  action: string,
  reason: string = "",
): Promise<Escalation | null> {
  return tryBackend<Escalation>(`/escalations/${caseId}/action`, {
    method: "POST",
    body: JSON.stringify({ action, reason }),
  }, true);
}

export async function getEscalationStats(): Promise<EscalationStats | null> {
  return tryBackend<EscalationStats>("/escalations/stats");
}

export async function getSafetyOverrides(activeOnly = true): Promise<SafetyOverride[]> {
  const remote = await tryBackend<SafetyOverride[]>(`/overrides?active_only=${activeOnly}`);
  return remote || [];
}

/** The actor and authority role are the signed-in user's (set by the backend). */
export async function createSafetyOverride(payload: {
  original_route: string;
  new_route: string;
  scope: string;
  reason: string;
  duration_hours: number;
}): Promise<SafetyOverride | null> {
  return tryBackend<SafetyOverride>("/overrides", {
    method: "POST",
    body: JSON.stringify(payload),
  }, true);
}

export async function getSafetyEvents(): Promise<SafetyEvent[]> {
  return (await tryBackend<SafetyEvent[]>("/events?limit=30", undefined, true))!;
}

export async function getTemplates(): Promise<
  { template_id: string; title: string; body: string; safe_alternative: string; restricted_sub_class: string | null }[]
> {
  return (await tryBackend<
    { template_id: string; title: string; body: string; safe_alternative: string; restricted_sub_class: string | null }[]
  >("/templates", undefined, true))!;
}

// ─── AI Governance views (live ledger data) ────────────────────────────────
// These throw on failure so a page can say the data did not load, rather
// than rendering zeros that look like a quiet day.

export type SafetyTrendPoint = { date: string; classified: number; blocked: number; review: number; other: number };

export type AnswerOutcomes = {
  answered: number;
  refused: number;
  clarified: number;
  rejected_by_validator: number;
  sent_to_review: number;
  security_incidents: number;
};

export type SafetySummary = {
  generated_at: string;
  last_event_at: string | null;
  totals: {
    events: number; classified: number; uncertain: number; blocked: number;
    incidents: number; review_cases: number; review_decisions: number;
  };
  last_7_days: { events: number; classified: number; blocked: number; incidents: number };
  answer_outcomes: AnswerOutcomes;
  answer_outcomes_7d: AnswerOutcomes;
  by_event_type: Record<string, number>;
  risk_levels: Record<string, number>;
  trend: SafetyTrendPoint[];
  escalations: EscalationStats;
  active_overrides: number;
};

export type RouteRuleView = {
  allowed: boolean;
  route: string;
  requires_sources: boolean;
  requires_citation: boolean;
  requires_professional_boundary: boolean;
  limitation: string | null;
};

export type RestrictedSubclassView = {
  code: string;
  description: string;
  route: string;
  clarification_permitted: boolean;
  reviewer_role: string | null;
  patterns: string[];
  refusal_templates: string[];
  blocked_count: number;
};

export type PolicyView = {
  policy: {
    id: string; version: string; scope: string; owner: string; approver: string | null;
    effective_from: string | null; rollback_target: string | null;
    rules: { pattern: string; risk: string }[];
  } | null;
  classifier_version: string;
  routing_matrix_version: string;
  routing_matrix: Record<string, Record<string, RouteRuleView>>;
  sla_hours: Record<string, number>;
  escalation_rules: {
    id: string; trigger_condition: string; reviewer_role: string;
    sla_hours: number; severity: string; notification_path: string;
  }[];
  restricted_subclasses: RestrictedSubclassView[];
  risk_level_window_days: number;
  risk_levels: Record<string, number>;
  open_cases_by_risk: Record<string, number>;
};

export type BoundaryRule = { check: string; pattern: string; applies: string; outcome: string };

export type BoundaryView = {
  validator: string;
  rules: BoundaryRule[];
  counts: {
    answers_returned: number; answers_rejected: number; refusals: number;
    certification_refusals: number; prohibited_claim_refusals: number;
  };
  rejections_by_check: { key: string; label: string; count: number }[];
  recent_rejections: { query_id: string; time: string | null; route: string | null; categories: string[]; failures: string[] }[];
};

export type BoundaryCheckResult = {
  passed: boolean;
  failures: string[];
  outcome: "released" | "refused" | "human_review";
  certification_request: boolean;
};

export async function getSafetySummary(): Promise<SafetySummary> {
  return (await tryBackend<SafetySummary>("/summary", undefined, true))!;
}

export async function getPolicyView(): Promise<PolicyView> {
  return (await tryBackend<PolicyView>("/policy", undefined, true))!;
}

export async function getBoundaryView(): Promise<BoundaryView> {
  return (await tryBackend<BoundaryView>("/boundaries", undefined, true))!;
}

export async function checkBoundary(payload: {
  text: string;
  user_specific: boolean;
  confidence_state: string;
  authority_level: string;
}): Promise<BoundaryCheckResult> {
  return (await tryBackend<BoundaryCheckResult>("/boundaries/check", {
    method: "POST",
    body: JSON.stringify(payload),
  }, true))!;
}
