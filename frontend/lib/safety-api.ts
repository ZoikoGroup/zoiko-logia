/**
 * Safety Service API client for the frontend.
 *
 * Calls the configured backend (NEXT_PUBLIC_API_URL, same as lib/api.ts).
 */

import { getCurrentAccessToken } from "@/lib/session-token";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010/api/v1";
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
    const res = await fetch(`${BACKEND}${path}`, {
      ...options,
      headers: {
        ...options?.headers,
        "Content-Type": "application/json",
        Authorization: `Bearer ${getCurrentAccessToken()}`,
      },
    });
    if (!res.ok) {
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

export async function getEscalations(): Promise<Escalation[]> {
  const remote = await tryBackend<Escalation[]>("/escalations");
  return remote ?? [];
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

export async function actOnEscalation(
  caseId: string,
  action: string,
  reviewerId: string,
  reason: string = "",
): Promise<Escalation | null> {
  return tryBackend<Escalation>(`/escalations/${caseId}/action`, {
    method: "POST",
    body: JSON.stringify({ action, reviewer_id: reviewerId, reason }),
  }, true);
}

export async function getEscalationStats(): Promise<EscalationStats | null> {
  return tryBackend<EscalationStats>("/escalations/stats");
}

export async function getSafetyOverrides(activeOnly = true): Promise<SafetyOverride[]> {
  const remote = await tryBackend<SafetyOverride[]>(`/overrides?active_only=${activeOnly}`);
  return remote || [];
}

export async function createSafetyOverride(payload: {
  actor_id: string;
  authority_role: string;
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
  const remote = await tryBackend<SafetyEvent[]>("/events?limit=30");
  if (remote) return remote;
  return [];
}

export async function getTemplates(): Promise<
  { template_id: string; title: string; body: string; safe_alternative: string; restricted_sub_class: string | null }[]
> {
  const remote = await tryBackend<
    { template_id: string; title: string; body: string; safe_alternative: string; restricted_sub_class: string | null }[]
  >("/templates");
  return remote ?? [];
}
