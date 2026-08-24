import { supabase } from "@/lib/supabase";
import { getCurrentAccessToken } from "@/lib/session-token";
import type { GovernanceDashboardViewModel } from "@/lib/governance-dashboard-types";
import type { CommandCenterViewModel } from "@/lib/command-center-types";

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

export async function getGovernanceDashboard(
  token: string,
  options: { environment: string; jurisdiction: string; windowDays: number },
  signal?: AbortSignal,
): Promise<GovernanceDashboardViewModel> {
  const query = new URLSearchParams({
    environment: options.environment,
    jurisdiction: options.jurisdiction,
    window_days: String(options.windowDays),
  });
  const res = await authedFetch(`/governance-dashboard?${query}`, token, { signal });
  return res.json();
}

export async function getCommandCenter(
  token: string,
  context: { jurisdiction: string; framework: string; period: string },
  signal?: AbortSignal,
): Promise<CommandCenterViewModel> {
  const query = new URLSearchParams(context);
  const res = await authedFetch(`/command-center?${query}`, token, { signal });
  return res.json();
}

export async function switchCommandCenterContext(
  token: string,
  payload: { jurisdiction: string; framework: string; period: string; previous_context_token: string },
): Promise<{ accepted: boolean; boundaryType: string }> {
  const res = await authedFetch("/command-center/context", token, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify(payload),
  });
  return res.json();
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
  clarification_cycle?: number;
  /** Scopes chart-repetition/telemetry to one thread. Not yet read by the
   * backend — accepted here so the frontend contract is forward-compatible. */
  conversation_id?: string;
  /** Documents attached to this turn. Ids of successfully indexed uploads
   * only; the backend re-verifies ownership and readiness, so sending an id
   * the caller does not own simply retrieves nothing. */
  document_ids?: string[];
};

// ---- Top-level response ----

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

export type ConfidenceState =
  | "sufficient"
  | "limited"
  | "insufficient"
  | "conflicting_sources"
  | "stale_sources"
  | "restricted_sources";

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

// ---- Source grounding ----

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

export type SourceCitation = {
  ref_id: string;
  source_id: string;
  title: string;
  /** External URL, internal doc link, or null. Null for an uploaded document —
   *  there is no public link to the user's own file. */
  url: string | null;
  /** The genuine retrieved snippet this citation was grounded in. */
  evidence_preview?: string | null;
  /** Provenance, for connectors that know their own origin and currency
   *  (market data, and uploaded documents). Absent for a plain web hit. */
  provider?: string | null;
  fetched_at?: string | null;
  /** realtime | delayed | historical | filing | user_upload. "user_upload"
   *  marks a citation that came from a file the user attached, which the panel
   *  must present as their own evidence rather than as a published source. */
  freshness?: string | null;
};

// ---- The answer itself ----

export type ResponseBlockType =
  | "markdown"
  | "visualization"
  | "calculation"
  | "limitations"
  | "citations"
  | "suggested_actions";

export type ResponseBlock = {
  id: string;
  type: ResponseBlockType;
  content?: string | null;
  /** Points into charts/guides/graphs/etc. */
  resource_ids: string[];
};

// ---- Calculation widget (interactive slider + chart) ----

export type WidgetInput = {
  name: string;
  label: string;
  value: string;   // Decimal-as-string
  unit: string;
  min: string;      // Decimal-as-string
  max: string;      // Decimal-as-string
  step: string;     // Decimal-as-string
};

export type ChartPoint = { x: string; y: string };

export type CalculationWidget = {
  formula_id: string;
  formula_name: string;
  formula_display: string;
  methodology_reference: string;
  inputs: WidgetInput[];
  output_label: string;
  output_value: string;
  output_unit: string;
  chart_type: "line" | "bar" | "donut" | "gauge" | "waterfall" | "stacked_bar" | "bullet" | "treemap" | "sankey" | "kpi";
  chart_label: string;
  chart_x_label: string;
  chart_y_label: string;
  chart_points: ChartPoint[];
  calculation_id: string;
};

// ---- Presentation / visualization payload ----

export type PresentationChartType =
  | "bar" | "line" | "area" | "donut" | "dual_axis" | "grouped_bar" | "stacked_bar"
  | "percentage_stacked_bar" | "diverging_bar" | "histogram" | "box_plot" | "radar"
  | "funnel" | "slope" | "scatter" | "bubble" | "heatmap" | "correlation_matrix"
  | "dumbbell" | "lollipop" | "bullet" | "waterfall" | "composition_bar";

export type PresentationSeries = { name: string; values: string[]; unit: string };

export type VisualizationGrammar = {
  version: "1.0";
  renderer: "echarts";
  composition: "layer" | "facet";
  layers: Array<{
    mark: "bar" | "line" | "area" | "point";
    series_index: number;
    axis: "primary" | "secondary";
    stack?: string | null;
  }>;
  facet_columns?: number | null;
  fallback_chart_type?: PresentationChartType | null;
};

export type PresentationChart = {
  chart_id: string;
  type: PresentationChartType;
  title: string;
  categories: string[];
  series: PresentationSeries[];
  unit: string;
  domain: "general" | "accounting" | "audit" | "tax";
  summary_mode: "latest" | "total" | "average";
  // Optional — chart-selection alternatives, telemetry, and personalization
  // metadata layered on across v3–v10; never required for rendering.
  alternatives?: PresentationChartType[];
  original_chart_type?: PresentationChartType | null;
  fallback_note?: string | null;
  schema_version?: string;
  grammar?: VisualizationGrammar | null;
  deterministic_candidates?: PresentationChartType[];
  candidate_scores?: Record<string, number>;
  validation_result?: "accepted" | "safe_fallback";
};

export type PresentationGuide = Record<string, unknown>;
export type PresentationGraph = Record<string, unknown>;

export type AnswerPresentation = {
  layout: "concise" | "descriptive" | "comparison" | "step_by_step" | "data_visualization" | "calculation";
  table_count: number;
  has_steps: boolean;
  charts: PresentationChart[];
  guides: PresentationGuide[];
  graphs: PresentationGraph[];
  sections: string[];
  follow_up_questions: string[];
  response_form?: "TEXT_ONLY" | "TEXT_KPI" | "TEXT_TABLE" | "TEXT_CHART" | "TEXT_GRAPH" | "TEXT_FLOWCHART" | "TEXT_TIMELINE" | "TEXT_MULTI_VISUAL" | "VISUAL_ONLY";
  visual_required?: boolean;
  visual_family?: "NONE" | "STATISTICAL" | "RELATIONSHIP" | "PROCESS" | "TABULAR" | "MULTI";
  planner_confidence?: number;
};

export type ComposedAnswer = {
  text: string;
  citations: SourceCitation[];
  limitations: string[];
  calculation_widget?: CalculationWidget | null;
  presentation?: AnswerPresentation | null;
  response_mode?: "concise" | "educational" | "analytical" | "calculation" | "workflow" | "compound";
  /** Preferred, ordered rendering path — not yet returned by the backend. */
  blocks?: ResponseBlock[];
  /** @deprecated use text — retained for backward compatibility */
  output_text?: string;
};

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
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 120_000);
  try {
    const res = await authedFetch("/orchestration/ask", token, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    return res.json();
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(408, "Kriton took too long to respond. Please try again.");
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
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

/** `status` is the real ingestion outcome, not just "the bytes arrived":
 *  "ready" means the file was parsed, chunked and is now searchable;
 *  "failed" means it was not, and `failure_reason` says why (a scanned PDF, a
 *  password-protected file, an empty spreadsheet). The UI must not show a
 *  success tick for "failed" — the user would then ask questions about a
 *  document that contributes nothing to the answer. */
export type AttachmentUploadResult = {
  document_id: string;
  filename: string;
  status: "ready" | "failed" | "pending";
  chunk_count: number;
  char_count: number;
  failure_reason: string | null;
};

export type AttachmentSummary = AttachmentUploadResult & {
  size_bytes: number;
  created_at: string | null;
};

/** XHR (not fetch) because upload progress events need `xhr.upload.onprogress`. */
export function uploadKritonAttachment(
  token: string,
  file: File,
  onProgress?: (fraction: number) => void,
): Promise<AttachmentUploadResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_URL}/kriton-workspace/attachments`);
    xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText));
        } catch {
          reject(new ApiError(xhr.status, "The attachment response could not be read."));
        }
      } else {
        let detail = `Attachment upload failed (${xhr.status})`;
        try {
          detail = JSON.parse(xhr.responseText)?.detail ?? detail;
        } catch {
          /* keep default detail */
        }
        reject(new ApiError(xhr.status, detail));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, "Could not reach the attachment service."));
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

export async function listKritonAttachments(token: string): Promise<AttachmentSummary[]> {
  const res = await authedFetch("/kriton-workspace/attachments", token);
  return res.json();
}

export async function deleteKritonAttachment(token: string, documentId: string): Promise<void> {
  await authedFetch(`/kriton-workspace/attachments/${encodeURIComponent(documentId)}`, token, {
    method: "DELETE",
  });
}

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
