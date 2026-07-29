import { supabase } from "@/lib/supabase";
import { getCurrentAccessToken } from "@/lib/session-token";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010/api/v1";

export type UserPublic = {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  full_name: string;
  role: string;
  tenant_id: string;
};

export type ProvisionRequest = {
  first_name?: string;
  last_name?: string;
  company_name?: string;
};

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** Idempotent — creates the local profile row on first call for a given
 * Supabase user (self-serve sign-up or first Google login), a no-op on
 * every call after. Called with the Supabase access token directly (not
 * getAuthToken()) since this can run before session-token.ts is updated. */
export async function provisionProfile(accessToken: string, payload: ProvisionRequest = {}): Promise<UserPublic> {
  const res = await fetch(`${API_URL}/auth/provision`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, body?.detail ?? "Could not provision profile");
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
  return getCurrentAccessToken();
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
  if (res.status === 401 && typeof window !== "undefined") {
    supabase.auth.signOut();
    if (window.location.pathname !== "/login") {
      window.location.href = "/login";
    }
    throw new ApiError(401, "Session expired — please log in again.");
  }
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
  source_id?: string | null;
  created_by: string;
  assigned_to: string | null;
  created_at: string;
};

export type TicketCreateRequest = {
  category: string;
  severity: string;
  query_id?: string;
  source_id?: string;
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

export type CPDEntry = {
  id: string;
  topic: string;
  minutes: number;
  logged_at: string;
};

export type CPDSummary = {
  total_minutes: number;
  total_hours: number;
  entry_count: number;
};

export type CPDEntryCreateRequest = {
  topic: string;
  minutes: number;
};

export async function listCPDEntries(token: string): Promise<CPDEntry[]> {
  const res = await authedFetch("/learning/cpd", token);
  return res.json();
}

export async function createCPDEntry(token: string, payload: CPDEntryCreateRequest): Promise<CPDEntry> {
  const res = await authedFetch("/learning/cpd", token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

export async function getCPDSummary(token: string): Promise<CPDSummary> {
  const res = await authedFetch("/learning/cpd/summary", token);
  return res.json();
}

export type SourceVersion = {
  id: string;
  source_id: string;
  version_label: string;
  status: string;
  effective_from: string | null;
  effective_to: string | null;
  display_restriction: string;
  note: string;
  submitted_by: string;
  approved_by: string | null;
  created_at: string;
  file_path: string | null;
  /** Same shape/contract as SourceCitation.url above. */
  url: string | null;
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
  effective_from?: string;
  effective_to?: string;
  file?: File | null;
};

export type ExpiringSource = {
  source_id: string;
  title: string;
  effective_to: string;
  days_remaining: number;
};

export type JurisdictionCategorySummary = {
  category: string;
  approved_count: number;
  pending_count: number;
};

export type JurisdictionSummary = {
  jurisdiction_scope: string;
  approved_count: number;
  pending_count: number;
  readiness: "READY" | "PARTIAL" | "NOT_STARTED" | string;
  categories: JurisdictionCategorySummary[];
};

export async function listSources(token: string, category?: string): Promise<Source[]> {
  const query = category ? `?category=${encodeURIComponent(category)}` : "";
  const res = await authedFetch(`/sources${query}`, token);
  return res.json();
}

export async function createSource(token: string, payload: SourceCreateRequest): Promise<Source> {
  const form = new FormData();
  form.set("category", payload.category);
  form.set("title", payload.title);
  form.set("source_class", payload.source_class);
  form.set("jurisdiction_scope", payload.jurisdiction_scope ?? "Global");
  form.set("framework_scope", payload.framework_scope ?? "");
  form.set("note", payload.note ?? "");
  if (payload.effective_from) form.set("effective_from", payload.effective_from);
  if (payload.effective_to) form.set("effective_to", payload.effective_to);
  if (payload.file) form.set("file", payload.file);
  const res = await authedFetch("/sources", token, {
    method: "POST",
    body: form,
  });
  return res.json();
}

export async function getExpiringSource(token: string): Promise<ExpiringSource | null> {
  const res = await authedFetch("/sources/expiring", token);
  return res.json();
}

export async function getJurisdictionSummary(token: string): Promise<JurisdictionSummary[]> {
  const res = await authedFetch("/sources/jurisdiction-summary", token);
  return res.json();
}

export async function approveSourceVersion(token: string, sourceId: string, versionId: string): Promise<Source> {
  const res = await authedFetch(`/sources/${sourceId}/versions/${versionId}/approve`, token, {
    method: "POST",
  });
  return res.json();
}

/** Opens a SourceCitation/SourceVersion `url` in a new tab. An absolute
 * external URL (a live-fetched government/API source) is safe to navigate
 * to directly — no backend auth needed, so it never touches authedFetch.
 * A relative `/sources/{id}/file` link is our own endpoint and DOES require
 * auth; the browser's plain navigation can't attach an Authorization
 * header, so this fetches it as an authenticated blob first and opens that
 * instead — the same reason no source link in this app is ever rendered as
 * a plain `<a href>`. */
export async function openSourceUrl(token: string, url: string): Promise<void> {
  if (/^https?:\/\//i.test(url)) {
    window.open(url, "_blank", "noopener,noreferrer");
    return;
  }
  const res = await authedFetch(url, token);
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  window.open(objectUrl, "_blank", "noopener,noreferrer");
  // Revoked after a delay rather than immediately — the new tab needs the
  // blob URL to still be valid by the time it finishes loading it.
  setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
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
  /** Prior user queries this conversation, most recent last — never the composed answers. */
  history?: string[];
  /** Which persisted conversation to append this turn to — omit/null to start a new one. */
  conversation_id?: string | null;
  /** Playground overrides — not trusted from body in production */
  source_confidence?: string;
  pre_bundle_state?: string;
  privacy_class?: string;
  clarification_cycle?: number;
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
  /** "live_api" for a dynamically-fetched source (live_sources/ or
   * reference_data/ connectors — Treasury, Census, FRED, professional
   * search, etc.), "document" for an ingested/uploaded document. */
  source_type?: "document" | "live_api";
  /** Only set for live-data citations — a real, clickable external URL (e.g. the ONS dataset page). Document citations have no public URL today. */
  source_url?: string | null;
  /** Absolute external URL for a live-fetched source, a relative
   * `/sources/{id}/file` link for an uploaded/ingested document (requires
   * auth — see openSourceUrl), or null if this source has no viewable
   * document (e.g. no file was ever uploaded for it). */
  url: string | null;
  /** Exact supporting excerpt selected for this answer. */
  evidence_preview?: string;
};

/** Governed calculation architecture — interactive rendering
 * (2026-07-23, backend/docs/calculation_architecture.md). Every numeric
 * field is a string (Decimal-as-string), matching the backend's convention
 * throughout the calculation domain — never parse these as JS `number`
 * without care for precision. */
export type WidgetInput = {
  name: string;
  label: string;
  value: string;
  unit: string;
  min: string;
  max: string;
  step: string;
};

export type ChartPoint = {
  x: string;
  y: string;
};

export type CalculationWidget = {
  formula_id: string;
  formula_name: string;
  formula_display: string;
  methodology_reference: string;
  inputs: WidgetInput[];
  output_label: string;
  output_value: string;
  output_unit: string;
  chart_label: string;
  chart_x_label: string;
  chart_y_label: string;
  chart_points: ChartPoint[];
  calculation_id: string;
};

export type PresentationSeries = {
  name: string;
  values: string[];
};

/** A single headline number from a table that reduces to one row (e.g.
 * "Total revenue: $482,000") — no delta/trend in v1, a single row has no
 * second point to diff against. */
export type PresentationMetric = {
  metric_id: string;
  label: string;
  value: string;
  unit: string;
};

export type PresentationChart = {
  chart_id: string;
  type: "bar" | "line" | "area" | "donut";
  title: string;
  categories: string[];
  series: PresentationSeries[];
  unit: string;
};

export type PresentationGuide = {
  guide_id: string;
  type: "process" | "timeline" | "checklist" | "decision_flow";
  title: string;
  items: string[];
};

export type AnswerPresentation = {
  layout: "concise" | "descriptive" | "comparison" | "step_by_step" | "data_visualization" | "calculation";
  table_count: number;
  has_steps: boolean;
  charts: PresentationChart[];
  metrics: PresentationMetric[];
  guides: PresentationGuide[];
  sections: string[];
  follow_up_questions: string[];
};

export type ComposedAnswer = {
  text: string;
  citations: SourceCitation[];
  limitations: string[];
  calculation_widget?: CalculationWidget | null;
  presentation?: AnswerPresentation | null;
  /** @deprecated use text — retained for backward compatibility */
  output_text?: string;
};

/** §12 SafetyState — frontend renders from this, not by parsing answer text */
export type SafetyState = {
  risk_level: "ZERO" | "LOW" | "MEDIUM" | "HIGH" | "RESTRICTED";
  policy_state: "allowed" | "blocked" | "needs_more_context";
  disclaimer_required: boolean;
  refusal_text?: string;
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
  | "limited_response"
  | "rejected";

export type RouteType =
  | "LLM"
  | "REFUSAL"
  | "CLARIFICATION"
  | "HUMAN_REVIEW"
  | "REFERRAL"
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
  /** Set by the backend after ask_kriton() returns — the persisted
   * conversation this turn was recorded into (see app/domains/chat_history).
   * Pass it back on the next AskKritonRequest to continue the same thread. */
  conversation_id: string | null;
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
    // Never leave the chat composer disabled forever when the API process is
    // unavailable or a provider stalls. The UI catches this and turns the
    // pending turn into a retryable error.
    signal: AbortSignal.timeout(90_000),
  });
  return res.json();
}

/** Called on every slider change in a rendered CalculationWidget — re-runs
 * the formula server-side (never client-side) so the displayed number is
 * always the one verified engine's output, never a JS reimplementation of
 * the formula that could drift from it. See
 * backend/docs/calculation_architecture.md and
 * backend/app/domains/calculation/api_router.py. */
export async function recomputeCalculation(
  token: string,
  formulaId: string,
  inputs: Record<string, { value: string; unit: string }>,
): Promise<CalculationWidget> {
  const res = await authedFetch("/calculations/recompute", token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ formula_id: formulaId, inputs }),
  });
  return res.json();
}

export type ConversationSummary = {
  id: string;
  title: string;
  jurisdiction: string;
  mode: string;
  created_at: string;
  updated_at: string;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  route: string | null;
  risk_level: string | null;
  citations: SourceCitation[] | null;
  created_at: string;
};

export type ConversationDetail = ConversationSummary & {
  messages: ChatMessage[];
};

export async function listConversations(token: string): Promise<ConversationSummary[]> {
  const res = await authedFetch("/conversations", token);
  return res.json();
}

export async function getConversation(token: string, id: string): Promise<ConversationDetail> {
  const res = await authedFetch(`/conversations/${id}`, token);
  return res.json();
}

export async function renameConversation(token: string, id: string, title: string): Promise<ConversationSummary> {
  const res = await authedFetch(`/conversations/${id}`, token, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  return res.json();
}

export async function deleteConversation(token: string, id: string): Promise<void> {
  await authedFetch(`/conversations/${id}`, token, { method: "DELETE" });
}

export type SavedAnswer = {
  id: string;
  query_id: string;
  query_text: string;
  answer_text: string;
  risk_level: string;
  tags: string[];
  created_at: string;
};

export type SavedAnswerCreateRequest = {
  query_id: string;
  query_text: string;
  answer_text: string;
  risk_level: string;
  tags?: string[];
};

export async function listSavedAnswers(token: string): Promise<SavedAnswer[]> {
  const res = await authedFetch("/kriton-workspace/saved-answers", token);
  return res.json();
}

export async function createSavedAnswer(token: string, payload: SavedAnswerCreateRequest): Promise<SavedAnswer> {
  const res = await authedFetch("/kriton-workspace/saved-answers", token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

export async function deleteSavedAnswer(token: string, id: string): Promise<void> {
  await authedFetch(`/kriton-workspace/saved-answers/${id}`, token, { method: "DELETE" });
}

export type Draft = {
  id: string;
  title: string;
  content: string;
  status: string;
  saved_answer_id: string | null;
  created_at: string;
  updated_at: string;
};

export type DraftCreateRequest = {
  title: string;
  content?: string;
  saved_answer_id?: string;
};

export type DraftUpdateRequest = {
  title?: string;
  content?: string;
  status?: string;
};

export async function listDrafts(token: string): Promise<Draft[]> {
  const res = await authedFetch("/kriton-workspace/drafts", token);
  return res.json();
}

export async function createDraft(token: string, payload: DraftCreateRequest): Promise<Draft> {
  const res = await authedFetch("/kriton-workspace/drafts", token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

export async function updateDraft(token: string, id: string, payload: DraftUpdateRequest): Promise<Draft> {
  const res = await authedFetch(`/kriton-workspace/drafts/${id}`, token, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
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
