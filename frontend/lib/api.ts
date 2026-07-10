import type { SafetyDecision } from "@/lib/safety-api";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export type UserPublic = {
  id: string;
  email: string;
  full_name: string;
  role: string;
  tenant_id: string;
};

export type TokenResponse = {
  access_token: string;
  token_type: string;
  user: UserPublic;
};

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  const res = await fetch(`${API_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, body?.detail ?? "Login failed");
  }

  return res.json();
}

export async function getMe(token: string): Promise<UserPublic> {
  const res = await fetch(`${API_URL}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!res.ok) {
    throw new ApiError(res.status, "Could not fetch current user");
  }

  return res.json();
}

export function getAuthToken(): string {
  if (typeof document === "undefined") return "";
  const match = document.cookie.match(/(?:^|; )zoiko_auth=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : "";
}

export type Role = {
  id: string;
  name: string;
  description: string;
  permissions_summary: string;
};

export type UserListItem = {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
};

export type UserCreateRequest = {
  email: string;
  password: string;
  full_name: string;
  role: string;
};

async function authedFetch(path: string, token: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      Authorization: `Bearer ${token}`,
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, body?.detail ?? `Request to ${path} failed`);
  }
  return res;
}

export async function listRoles(token: string): Promise<Role[]> {
  const res = await authedFetch("/roles", token);
  return res.json();
}

export async function listUsers(token: string): Promise<UserListItem[]> {
  const res = await authedFetch("/users", token);
  return res.json();
}

export async function createUser(token: string, payload: UserCreateRequest): Promise<UserListItem> {
  const res = await authedFetch("/users", token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

export async function setUserActive(token: string, id: string, isActive: boolean): Promise<UserListItem> {
  const res = await authedFetch(`/users/${id}`, token, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_active: isActive }),
  });
  return res.json();
}

export type Ticket = {
  id: string;
  category: string;
  severity: string;
  status: string;
  query_id: string | null;
  created_by: string;
  assigned_to: string | null;
  created_at: string;
};

export type TicketCreateRequest = {
  category: string;
  severity: string;
  query_id?: string;
};

export type Incident = {
  id: string;
  title: string;
  severity: string;
  status: string;
  commander: string | null;
  opened_at: string;
};

export async function listTickets(token: string): Promise<Ticket[]> {
  const res = await authedFetch("/support/tickets", token);
  return res.json();
}

export async function createTicket(token: string, payload: TicketCreateRequest): Promise<Ticket> {
  const res = await authedFetch("/support/tickets", token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

export async function updateTicketStatus(token: string, id: string, status: string): Promise<Ticket> {
  const res = await authedFetch(`/support/tickets/${id}`, token, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  return res.json();
}

export async function listIncidents(token: string): Promise<Incident[]> {
  const res = await authedFetch("/support/incidents", token);
  return res.json();
}

export type SyllabusPathway = {
  id: string;
  body: string;
  qualification: string;
  module: string;
  topic: string;
  learning_outcome: string;
};

export type TopicMapNode = {
  id: string;
  topic: string;
  prerequisites: string;
  standards_summary: string;
};

export async function listSyllabusPathways(token: string): Promise<SyllabusPathway[]> {
  const res = await authedFetch("/learning/pathways", token);
  return res.json();
}

export async function listTopicMapNodes(token: string): Promise<TopicMapNode[]> {
  const res = await authedFetch("/learning/topics", token);
  return res.json();
}

export type SourceVersion = {
  id: string;
  version_label: string;
  status: string;
  effective_from: string | null;
  effective_to: string | null;
  display_restriction: string;
  note: string;
  submitted_by: string;
  approved_by: string | null;
  created_at: string;
};

export type Source = {
  id: string;
  category: string;
  title: string;
  source_class: string;
  jurisdiction_scope: string;
  framework_scope: string;
  latest_version: SourceVersion;
};

export type SourceCreateRequest = {
  category: string;
  title: string;
  source_class: string;
  jurisdiction_scope?: string;
  framework_scope?: string;
  note?: string;
};

export async function listSources(token: string, category?: string): Promise<Source[]> {
  const query = category ? `?category=${encodeURIComponent(category)}` : "";
  const res = await authedFetch(`/sources${query}`, token);
  return res.json();
}

export async function createSource(token: string, payload: SourceCreateRequest): Promise<Source> {
  const res = await authedFetch("/sources", token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

export async function approveSourceVersion(token: string, sourceId: string, versionId: string): Promise<Source> {
  const res = await authedFetch(`/sources/${sourceId}/versions/${versionId}/approve`, token, {
    method: "POST",
  });
  return res.json();
}

export type ModelDefinition = {
  id: string;
  name: string;
  role: string;
  environment: string;
  version: string;
  status: string;
  provider: string;
};

export type PromptTemplate = {
  id: string;
  name: string;
  version: string;
  status: string;
  mode: string;
  submitted_by: string;
  approved_by: string | null;
};

export type TestRunResponse = {
  prompt_id: string;
  prompt_name: string;
  output_text: string;
};

export async function listModels(token: string): Promise<ModelDefinition[]> {
  const res = await authedFetch("/models", token);
  return res.json();
}

export async function listPrompts(token: string): Promise<PromptTemplate[]> {
  const res = await authedFetch("/prompts", token);
  return res.json();
}

export async function approvePrompt(token: string, promptId: string): Promise<PromptTemplate> {
  const res = await authedFetch(`/prompts/${promptId}/approve`, token, { method: "POST" });
  return res.json();
}

export async function runTestPrompt(token: string, promptId: string, inputText: string): Promise<TestRunResponse> {
  const res = await authedFetch("/model-gateway/test-run", token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt_id: promptId, input_text: inputText }),
  });
  return res.json();
}

export type AuditEvent = {
  id: string;
  event_name: string;
  payload_schema_version: string;
  event_time: string | null;
  ingested_at: string | null;
  emitting_service: string;
  tenant_id: string;
  actor_type: string;
  actor_id: string | null;
  subject_type: string;
  subject_id: string;
  correlation_id: string | null;
  causation_id: string | null;
  payload: Record<string, unknown>;
  payload_hash: string | null;
  previous_chain_hash: string | null;
  chain_hash: string | null;
  classification: string;
  replay_relevance: string;
  validation_status: string;
  legal_hold_id: string | null;
  archived: boolean;
  source: string;
};

export type AuditEventFilters = {
  eventName?: string;
  subjectType?: string;
  subjectId?: string;
  correlationId?: string;
  limit?: number;
};

export async function listAuditEvents(token: string, filters: AuditEventFilters = {}): Promise<AuditEvent[]> {
  const query = new URLSearchParams();
  if (filters.eventName) query.set("event_name", filters.eventName);
  if (filters.subjectType) query.set("subject_type", filters.subjectType);
  if (filters.subjectId) query.set("subject_id", filters.subjectId);
  if (filters.correlationId) query.set("correlation_id", filters.correlationId);
  if (filters.limit) query.set("limit", String(filters.limit));
  const qs = query.toString();
  const res = await authedFetch(`/audit/events${qs ? `?${qs}` : ""}`, token);
  return res.json();
}

export type ChainVerifyResult = {
  tenant_id: string;
  passed: boolean;
  events_checked: number;
  first_broken_event_id: string | null;
};

export async function verifyAuditChain(token: string): Promise<ChainVerifyResult> {
  const res = await authedFetch("/audit/chain-verify", token);
  return res.json();
}

export type ReplayKnownGap = {
  event_class: string;
  expected_event_name: string;
  gap_reason: string;
  impact_on_replay: string;
};

export type ReplayTimelineEvent = {
  event_id: string;
  event_name: string;
  event_time: string | null;
  emitting_service: string;
  payload: Record<string, unknown>;
  chain_hash: string | null;
  replay_relevance: string;
  source: string;
};

export type ReplayManifest = {
  correlation_id: string;
  completeness_status: "COMPLETE" | "PARTIAL_KNOWN_GAPS" | "INCOMPLETE_UNKNOWN";
  known_gaps: ReplayKnownGap[];
  manifest_trustworthiness: "AUTHORITATIVE" | "LIMITED" | "INCONCLUSIVE";
  chain_verification_result: string;
  generated_by: string;
  generated_at: string;
  events: ReplayTimelineEvent[];
  manifest_hash: string;
};

export async function getReplayManifest(token: string, correlationId: string): Promise<ReplayManifest> {
  const res = await authedFetch(`/audit/replay/${encodeURIComponent(correlationId)}`, token);
  return res.json();
}

// ── Ask Kriton™ — ZL-ENG-02 §12 Canonical Response Contract ────────────────

export type AskKritonRequest = {
  query: string;
  jurisdiction?: string;
  mode?: string;
  /** Playground overrides — not trusted from body in production */
  source_confidence?: string;
  pre_bundle_state?: string;
  privacy_class?: string;
};

export type SourceSummary = {
  id: string;
  title: string;
  category: string;
  jurisdiction_scope: string;
  version_label: string;
  status: string;
};

/** §7.2 SourceBundle — six confidence states */
export type SourceBundle = {
  source_bundle_id: string;
  retrieval_method: string;             // "keyword_mvp" (not RAG until §7 criteria met)
  eligible_source_count: number;
  excluded_source_count: number;
  sources: SourceSummary[];
  exclusion_reasons: string[];
  jurisdiction: string;
  authority_level: string;              // primary | secondary | internal
  freshness_state: string;              // current | stale | unknown
  licence_state: string;                // permitted | restricted | unknown
  confidence_state: ConfidenceState;
};

export type ConfidenceState =
  | "sufficient"
  | "limited"
  | "insufficient"
  | "conflicting_sources"
  | "stale_sources"
  | "restricted_sources";

export type SourceCitation = {
  ref_id: string;
  source_id: string;
  title: string;
};

export type ComposedAnswer = {
  text: string;
  citations: SourceCitation[];
  limitations: string[];
  /** @deprecated use text — retained for backward compatibility */
  output_text?: string;
};

/** §12 SafetyState — frontend renders from this, not by parsing answer text */
export type SafetyState = {
  risk_level: "LOW" | "MEDIUM" | "HIGH" | "RESTRICTED";
  policy_state: "allowed" | "blocked" | "needs_more_context";
  disclaimer_required: boolean;
};

export type NextAction = {
  type: string;  // ask_clarifying_question | escalate | refusal | security_incident | composition_failed
  message: string;
};

/** §12 — opaque audit reference; never exposes internal hashes */
export type AuditReference = {
  audit_chain_id: string;
};

export type OutcomeType =
  | "answered"
  | "refused"
  | "clarification_required"
  | "escalated"
  | "rejected";

export type RouteType =
  | "LLM"
  | "REFUSAL"
  | "CLARIFICATION"
  | "HUMAN_REVIEW"
  | "SECURITY_INCIDENT"
  | "REJECTED";

/** §12 Canonical response contract — frontend renders from route/outcome ONLY */
export type AskKritonResponse = {
  query_id: string;
  correlation_id: string;
  outcome: OutcomeType;
  route: RouteType;
  safety: SafetyState;
  confidence_state: ConfidenceState;
  source_bundle: SourceBundle | null;
  answer: ComposedAnswer | null;
  next_action: NextAction | null;
  /** Opaque — never expose audit_chain_id internals to UI rendering logic */
  audit_reference: AuditReference;
};

export async function askKriton(
  token: string,
  payload: AskKritonRequest,
  idempotencyKey?: string,
): Promise<AskKritonResponse> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;
  const res = await authedFetch("/orchestration/ask", token, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });
  return res.json();
}

export type UploadResponse = {
  status: string;
  title: string;
  chunks_stored: string;
  tenant_id: string;
  jurisdiction: string;
  file_path: string;
};

export async function uploadDocument(token: string, file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  // Note: do NOT set Content-Type header — browser sets it with boundary automatically
  const res = await authedFetch("/kriton/upload", token, {
    method: "POST",
    body: form,
  });
  return res.json();
}


