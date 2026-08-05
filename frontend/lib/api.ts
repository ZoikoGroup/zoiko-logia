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
  const send = (accessToken: string) => fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      Authorization: `Bearer ${accessToken}`,
    },
  });
  let res = await send(token);
  if (res.status === 401 && typeof window !== "undefined") {
    // Access tokens expire during long Kriton demos. Supabase maintains a
    // refresh token in browser storage, so refresh and retry the original
    // request once before treating the session as expired. Previously the
    // first 401 immediately signed the user out even when refresh was valid.
    const { data, error } = await supabase.auth.refreshSession();
    const refreshedToken = data.session?.access_token;
    if (!error && refreshedToken) {
      res = await send(refreshedToken);
      if (res.status !== 401) {
        if (!res.ok) {
          const body = await res.json().catch(() => null);
          throw new ApiError(res.status, body?.detail ?? `Request to ${path} failed`);
        }
        return res;
      }
    }
    await supabase.auth.signOut();
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
  /** Playground overrides — not trusted from body in production */
  source_confidence?: string;
  pre_bundle_state?: string;
  privacy_class?: string;
  clarification_cycle?: number;
  /** Dynamic Visualization Selection v4 — the current chat thread's locally-
   * generated id (already used for the recents sidebar); scopes the chart-
   * repetition penalty and telemetry to this conversation server-side. */
  conversation_id?: string;
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
  chart_type: "line" | "bar" | "donut" | "gauge" | "waterfall" | "stacked_bar" | "bullet" | "treemap" | "sankey" | "kpi";
  chart_label: string;
  chart_x_label: string;
  chart_y_label: string;
  chart_points: ChartPoint[];
  calculation_id: string;
};

export type PresentationSeries = {
  name: string;
  values: string[];
  unit: string;
};

export type PresentationChartType =
  | "bar"
  | "line"
  | "area"
  | "donut"
  | "dual_axis"
  | "grouped_bar"
  | "stacked_bar"
  | "percentage_stacked_bar"
  | "diverging_bar"
  | "histogram"
  | "box_plot"
  | "radar"
  | "funnel"
  | "slope"
  | "scatter"
  | "bubble"
  | "heatmap"
  | "correlation_matrix"
  | "dumbbell"
  | "lollipop"
  | "bullet"
  | "waterfall"
  // v5 — temporal/composition brought into the candidate system.
  | "composition_bar";

export type SelectionSource =
  | "deterministic_default"
  | "explicit_user_request"
  | "alternative_switch"
  | "safe_fallback"
  | "legacy_payload"
  | "personalized";

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
  // Dynamic Visualization Selection v3 — all optional so a v1/v2 payload
  // (live or previously saved, missing these fields entirely) still
  // type-checks and renders unchanged.
  alternatives?: PresentationChartType[];
  original_chart_type?: PresentationChartType | null;
  fallback_note?: string | null;
  schema_version?: string;
  // v4 — diagnostic/telemetry metadata only, never used for rendering.
  analytical_intent?: string | null;
  selection_source?: SelectionSource | null;
  preference_affected_selection?: boolean;
  // v10 — diagnostic/telemetry metadata only, same posture as
  // preference_affected_selection above. personalization_affected_selection
  // is true only when a consent-based signal actually won a near-tie break
  // on THIS chart — never merely because personalization is enabled.
  personalization_enabled?: boolean;
  personalization_affected_selection?: boolean;
  personalization_model_version?: string | null;
  personalization_confidence_band?: "low" | "medium" | "high" | null;
  preferred_output?: "auto" | "chart" | "table";
  visual_density?: "compact" | "standard" | "detailed";
  contrast_preference?: "system" | "standard" | "high";
  reduced_motion?: boolean;
  table_alternative_default_open?: boolean;
  label_orientation?: "auto" | "horizontal" | "vertical";
  grammar?: VisualizationGrammar | null;
};

export type VisualizationPreferences = {
  preferred_output: "auto" | "chart" | "table";
  comparison_preference: "auto" | "grouped_bar" | "dumbbell" | "lollipop" | "diverging_bar";
  trend_preference: "auto" | "line" | "area";
  composition_preference: "auto" | "donut" | "composition_bar" | "stacked_bar" | "percentage_stacked_bar";
  value_display: "auto" | "absolute" | "percentage";
  label_orientation: "auto" | "horizontal" | "vertical";
  visual_density: "compact" | "standard" | "detailed";
  contrast_preference: "system" | "standard" | "high";
  reduced_motion: boolean;
  table_alternative_default_open: boolean;
  schema_version: "1.0";
};

export async function getVisualizationPreferences(token: string): Promise<VisualizationPreferences> {
  const res = await authedFetch("/orchestration/visualization-preferences", token);
  if (!res.ok) throw new ApiError(res.status, "Could not load visualization preferences");
  return res.json();
}

export async function putVisualizationPreferences(token: string, value: VisualizationPreferences): Promise<VisualizationPreferences> {
  const res = await authedFetch("/orchestration/visualization-preferences", token, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(value),
  });
  if (!res.ok) throw new ApiError(res.status, "Could not save visualization preferences");
  return res.json();
}

export async function resetVisualizationPreferences(token: string): Promise<VisualizationPreferences> {
  const res = await authedFetch("/orchestration/visualization-preferences", token, { method: "DELETE" });
  if (!res.ok) throw new ApiError(res.status, "Could not reset visualization preferences");
  return res.json();
}

// V10 — consent-based visualization personalization. Disabled by default;
// never inferred from usage. See backend/app/orchestration/
// visualization_personalization_consent.py for the authoritative shape.
export type PersonalizationConsent = {
  personalization_enabled: boolean;
  personalization_scope: "visualization_only";
  personalization_history_window: "30_days" | "90_days" | "180_days";
  allow_view_switch_learning: boolean;
  allow_export_learning: boolean;
  allow_save_learning: boolean;
  consent_updated_at?: string | null;
  schema_version: "1.0";
};

export const defaultPersonalizationConsent: PersonalizationConsent = {
  personalization_enabled: false,
  personalization_scope: "visualization_only",
  personalization_history_window: "90_days",
  allow_view_switch_learning: true,
  allow_export_learning: true,
  allow_save_learning: true,
  schema_version: "1.0",
};

export async function getPersonalizationConsent(token: string): Promise<PersonalizationConsent> {
  const res = await authedFetch("/orchestration/visualization-personalization/consent", token);
  if (!res.ok) throw new ApiError(res.status, "Could not load personalization settings");
  return res.json();
}

export async function putPersonalizationConsent(token: string, value: PersonalizationConsent): Promise<PersonalizationConsent> {
  const res = await authedFetch("/orchestration/visualization-personalization/consent", token, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(value),
  });
  if (!res.ok) throw new ApiError(res.status, "Could not save personalization settings");
  return res.json();
}

// Chart-type labels and counts only — never raw event history (requirement:
// "Do not expose detailed event history").
export type PersonalizationSummary = {
  eligible: boolean;
  interaction_count: number;
  conversation_count: number;
  top_family_preferences: Record<string, string>;
  top_intent_preferences: Record<string, string>;
};

export async function getPersonalizationSummary(token: string): Promise<PersonalizationSummary> {
  const res = await authedFetch("/orchestration/visualization-personalization/summary", token);
  if (!res.ok) throw new ApiError(res.status, "Could not load personalization summary");
  return res.json();
}

export async function resetPersonalizationProfile(token: string): Promise<void> {
  const res = await authedFetch("/orchestration/visualization-personalization/reset", token, { method: "POST" });
  if (!res.ok) throw new ApiError(res.status, "Could not reset personalization learning");
}

export async function deletePersonalizationProfile(token: string): Promise<void> {
  const res = await authedFetch("/orchestration/visualization-personalization", token, { method: "DELETE" });
  if (!res.ok) throw new ApiError(res.status, "Could not delete personalization profile");
}

export type VisualizationGapRow = {
  analytical_intent: string | null; requested_capability: string; requested_visualization_family: string;
  validated_data_shape: string; current_fallback: string; sample_size: number; distinct_conversations: number;
  distinct_actors: number; fallback_retention_rate: number | null; fallback_switch_rate: number | null;
  render_failure_rate: number; evidence_status: "insufficient_evidence" | "directional_signal" | "eligible_for_review";
  recommended_issue_classification: string;
  recommended_action: string;
};
export type VisualizationGapSummary = { total_visualization_requests: number; total_fallback_events: number; gap_rate: number; rows: VisualizationGapRow[]; environment: string };
export type VisualizationGapFilters = { dateFrom?: string; dateTo?: string; environment?: string; analyticalIntent?: string; requestedChartType?: string; requestedVisualizationFamily?: string; dataShapeClass?: string; evidenceStatus?: string };
export async function getVisualizationGapSummary(token: string, filters: VisualizationGapFilters = {}): Promise<VisualizationGapSummary> {
  const query = new URLSearchParams();
  if (filters.dateFrom) query.set("date_from", filters.dateFrom); if (filters.dateTo) query.set("date_to", filters.dateTo);
  if (filters.environment) query.set("environment", filters.environment); if (filters.analyticalIntent) query.set("analytical_intent", filters.analyticalIntent);
  if (filters.requestedChartType) query.set("requested_chart_type", filters.requestedChartType);
  if (filters.requestedVisualizationFamily) query.set("requested_visualization_family", filters.requestedVisualizationFamily);
  if (filters.dataShapeClass) query.set("data_shape_class", filters.dataShapeClass); if (filters.evidenceStatus) query.set("evidence_status", filters.evidenceStatus);
  const res = await authedFetch(`/orchestration/analytics/visualization-gaps/summary?${query}`, token);
  if (!res.ok) throw new ApiError(res.status, "Could not load visualization gap report"); return res.json();
}
export type VisualizationGapReport = { id:string; period_start:string; period_end:string; evidence_version:string; approved_findings:string[]; artifact:Record<string,unknown>; status:"draft"|"under_review"|"approved"|"rejected"; created_by:string; approved_by:string|null; approved_at:string|null };
export async function createVisualizationGapReport(token:string, periodStart:string, periodEnd:string, approvedFindings:string[]):Promise<VisualizationGapReport>{
  const res=await authedFetch("/orchestration/analytics/visualization-gaps/reports",token,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({period_start:periodStart,period_end:periodEnd,approved_findings:approvedFindings.slice(0,3)})});
  if(!res.ok)throw new ApiError(res.status,"Could not create gap report");return res.json();
}
export async function transitionVisualizationGapReport(token:string,id:string,status:"under_review"|"approved"|"rejected"):Promise<VisualizationGapReport>{
  const res=await authedFetch(`/orchestration/analytics/visualization-gaps/reports/${id}/${status}`,token,{method:"POST"});if(!res.ok)throw new ApiError(res.status,"Could not update gap report");return res.json();
}

// V8.4/V8.5 — production evidence monitoring. Counts and status only; the
// backing endpoints never return raw event records, identifiers, queries,
// values, or labels — see backend/app/orchestration/evidence_monitoring.py.
export type MonitoringRunStatus = "running"|"succeeded"|"failed";
export type MonitoringTriggerSource = "scheduled"|"manual";
export type MonitoringRunSummary = {
  tenant_id: string; started_at: string; completed_at: string | null; status: MonitoringRunStatus;
  trigger_source: MonitoringTriggerSource; monitoring_period: string; evidence_version: string;
  valid_event_count: number; draft_created: boolean; alert_created: boolean;
  report_id: string | null; failure_category: string | null;
};
export type EvidenceMonitoringStatus = {
  tenant_id: string; valid_event_count: number; distinct_conversation_count: number; distinct_actor_count: number;
  overall_evidence_status: "insufficient_evidence"|"directional_signal"|"eligible_for_review";
  monitoring_status: "collecting_evidence"|"directional_signal"|"ready_for_review"|"awaiting_approval"|"approved_findings_available";
  next_eligible_finding: VisualizationGapRow | null; events_to_next_threshold: number | null;
  diversity_gate_blocking_next: boolean; last_aggregation_at: string | null; last_report: VisualizationGapReport | null;
  last_scheduled_run: MonitoringRunSummary | null; last_manual_run: MonitoringRunSummary | null;
  current_run: MonitoringRunSummary | null; next_scheduled_run_at: string | null;
};
export async function getEvidenceMonitoringStatus(token:string):Promise<EvidenceMonitoringStatus>{
  const res=await authedFetch("/orchestration/analytics/visualization-gaps/evidence-monitoring/status",token);
  if(!res.ok)throw new ApiError(res.status,"Could not load evidence monitoring status");return res.json();
}
export type EvidenceMonitoringRunResult = {
  tenant_id: string; started_at: string; completed_at: string | null; status: MonitoringRunStatus;
  trigger_source: MonitoringTriggerSource; monitoring_period: string; evidence_version: string;
  valid_event_count: number; distinct_conversation_count: number; distinct_actor_count: number;
  eligible_finding_count: number; draft_created: boolean; alert_created: boolean; deduplicated: boolean;
  report_id: string | null; failure_category: string | null;
};
export async function runEvidenceMonitoring(token:string):Promise<EvidenceMonitoringRunResult>{
  const res=await authedFetch("/orchestration/analytics/visualization-gaps/evidence-monitoring/run",token,{method:"POST"});
  if(res.status===409)throw new ApiError(409,"A monitoring run is already active for this tenant — wait for it to finish.");
  if(!res.ok)throw new ApiError(res.status,"Could not run evidence monitoring");return res.json();
}

export type PresentationGuide = {
  guide_id: string;
  type: "process" | "timeline" | "checklist" | "decision_flow" | "sequence";
  title: string;
  items: string[];
  domain: "general" | "accounting" | "audit" | "tax";
  renderer: "html" | "mermaid" | "react_flow";
  editable: boolean;
  flow_nodes?: Array<{ id: string; position: { x: number; y: number }; label: string }>;
  flow_edges?: Array<{ id: string; source: string; target: string }>;
};

export type GraphEntityType =
  | "invoice" | "supplier" | "purchase_order" | "receipt" | "payment"
  | "bank_transaction" | "ledger_entry" | "contract" | "approval" | "user"
  | "source_document" | "audit_evidence";

export type GraphRelationshipType =
  | "issued_by" | "belongs_to" | "references" | "approved_by" | "paid_by"
  | "matched_to" | "recorded_as" | "supported_by" | "derived_from" | "reconciled_with";

export type GraphNode = {
  id: string;
  label: string;
  entity_type: GraphEntityType;
  status: string;
  source_reference: string;
  metadata: Record<string, string>;
};

export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  relationship_type: GraphRelationshipType;
  label: string;
  direction: "directed" | "bidirectional";
};

/** Cytoscape.js-rendered relationship/evidence graph — see
 * backend/app/orchestration/presentation_graph.py. Nodes and edges are
 * strictly validated server-side (closed entity/relationship enums, no
 * duplicate/missing/oversized data); this is plain data, never markup or
 * code, so rendering it can never execute anything. */
export type PresentationGraph = {
  graph_id: string;
  title: string;
  summary: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  layout: "breadthfirst" | "cose" | "concentric";
  confidence: number;
};

export type AnswerPresentation = {
  layout: "concise" | "descriptive" | "comparison" | "step_by_step" | "data_visualization" | "calculation";
  table_count: number;
  has_steps: boolean;
  charts: PresentationChart[];
  guides: PresentationGuide[];
  graphs: PresentationGraph[];
  sections: string[];
  follow_up_questions: string[];
};

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
  resource_ids: string[];
};

export type ComposedAnswer = {
  text: string;
  citations: SourceCitation[];
  limitations: string[];
  calculation_widget?: CalculationWidget | null;
  presentation?: AnswerPresentation | null;
  response_mode?: "concise" | "educational" | "analytical" | "calculation" | "workflow" | "compound";
  blocks?: ResponseBlock[];
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

export type VisualizationTelemetryEventName =
  | "alternative_view_selected"
  | "visualization_exported_png"
  | "visualization_exported_csv"
  | "visualization_saved"
  | "visualization_render_failed"
  // v10 — "View as table" opened; a permitted personalization signal, see
  // backend/app/orchestration/visualization_personalization.py.
  | "table_view_opened";

export type VisualizationTelemetryRequest = {
  event_name: VisualizationTelemetryEventName;
  conversation_id?: string | null;
  query_id?: string | null;
  analytical_intent?: string | null;
  original_chart_type?: string | null;
  active_chart_type?: string | null;
  alternative_count?: number | null;
  selection_source?: SelectionSource | null;
  renderer?: string | null;
  schema_version?: string | null;
  chart_family?: string | null;
};

/** Dynamic Visualization Selection v4 — records one client-originated
 * telemetry event. visualization_selected/alternative_views_shown/
 * visualization_fallback_used are backend-only (emitted automatically at
 * answer-generation time) and deliberately not constructible through this
 * type — see VisualizationTelemetryRequest server-side. Callers should
 * treat this as fire-and-forget (see lib/telemetry.ts); it intentionally
 * has no special error type of its own to catch, since the requirement is
 * "never block the workflow," not "handle telemetry errors specially." */
export async function recordVisualizationEvent(token: string, payload: VisualizationTelemetryRequest): Promise<void> {
  await authedFetch("/orchestration/visualization-events", token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(10_000),
  });
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

export type VisualizationType = "chart" | "graph" | "diagram" | "presentation_chart";

export type SavedVisualization = {
  id: string;
  query_id: string;
  visualization_type: VisualizationType;
  schema_version: string;
  title: string;
  summary: string;
  payload: CalculationWidget | PresentationGraph | PresentationGuide | PresentationChart;
  source_references: string[];
  created_at: string;
};

export type SavedVisualizationCreateRequest = {
  query_id: string;
  visualization_type: VisualizationType;
  schema_version?: string;
  title: string;
  summary?: string;
  payload: CalculationWidget | PresentationGraph | PresentationGuide | PresentationChart;
  source_references?: string[];
};

/** Idempotency-Key makes a repeated click (double submit, retried request)
 * return the original save instead of creating a duplicate row — same
 * mechanism askKriton uses. Callers should generate one key per save
 * attempt and reuse it only when retrying that exact attempt. */
export async function createSavedVisualization(
  token: string,
  payload: SavedVisualizationCreateRequest,
  idempotencyKey: string,
): Promise<SavedVisualization> {
  const res = await authedFetch("/kriton-workspace/saved-visualizations", token, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
    body: JSON.stringify(payload),
  });
  return res.json();
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

// ── Dynamic Visualization Selection v6 — recommendation-quality reporting
// and ranking-configuration governance. Admin-only on the backend
// (require_admin); every rate travels with its own sample_size and
// evidence_status so the dashboard can never render a percentage without
// showing how much data backs it.

export type EvidenceStatus = "insufficient_evidence" | "directional_signal" | "eligible_for_review";

export type RateMetric = {
  rate: number;
  numerator: number;
  sample_size: number;
  evidence_status: EvidenceStatus;
};

export type AnalyticsFilters = {
  dateFrom?: string;
  dateTo?: string;
  analyticalIntent?: string;
  chartFamily?: string;
  originalChartType?: string;
  activeChartType?: string;
  renderer?: string;
  selectionSource?: string;
  rankingVersion?: string;
  groupBy?: string[];
};

function analyticsQueryString(filters: AnalyticsFilters): string {
  const query = new URLSearchParams();
  if (filters.dateFrom) query.set("date_from", filters.dateFrom);
  if (filters.dateTo) query.set("date_to", filters.dateTo);
  if (filters.analyticalIntent) query.set("analytical_intent", filters.analyticalIntent);
  if (filters.chartFamily) query.set("chart_family", filters.chartFamily);
  if (filters.originalChartType) query.set("original_chart_type", filters.originalChartType);
  if (filters.activeChartType) query.set("active_chart_type", filters.activeChartType);
  if (filters.renderer) query.set("renderer", filters.renderer);
  if (filters.selectionSource) query.set("selection_source", filters.selectionSource);
  if (filters.rankingVersion) query.set("ranking_version", filters.rankingVersion);
  for (const dimension of filters.groupBy ?? []) query.append("group_by", dimension);
  const qs = query.toString();
  return qs ? `?${qs}` : "";
}

export type RecommendationQualityRow = {
  group_key: Record<string, string>;
  total_selections: number;
  recommendation_retention_rate: RateMetric;
  alternative_views_shown_rate: RateMetric;
  alternative_switch_rate: RateMetric;
  png_export_rate: RateMetric;
  csv_export_rate: RateMetric;
  visualization_save_rate: RateMetric;
  render_failure_rate: RateMetric;
  fallback_rate: RateMetric;
};

export type RecommendationQualitySummaryResponse = {
  rows: RecommendationQualityRow[];
  date_from: string | null;
  date_to: string | null;
  group_by: string[];
};

export async function getRecommendationQualitySummary(
  token: string, filters: AnalyticsFilters = {},
): Promise<RecommendationQualitySummaryResponse> {
  const res = await authedFetch(`/orchestration/analytics/recommendation-quality${analyticsQueryString(filters)}`, token);
  return res.json();
}

export type ReplacementMatrixCell = {
  original_chart_type: string;
  active_chart_type: string;
  count: number;
  rate: number;
  sample_size: number;
  evidence_status: EvidenceStatus;
};

export type ReplacementMatrixResponse = {
  cells: ReplacementMatrixCell[];
  date_from: string | null;
  date_to: string | null;
};

export async function getReplacementMatrix(token: string, filters: AnalyticsFilters = {}): Promise<ReplacementMatrixResponse> {
  const res = await authedFetch(`/orchestration/analytics/replacement-matrix${analyticsQueryString(filters)}`, token);
  return res.json();
}

export type ChartTypePerformanceRow = {
  group_key: Record<string, string>;
  chart_type: string;
  total_selections: number;
  switch_rate: RateMetric;
  fallback_rate: RateMetric;
  render_failure_rate: RateMetric;
  unusually_high_switch_rate: boolean;
  unusually_high_fallback_rate: boolean;
  unusually_high_render_failure_rate: boolean;
};

export type ChartTypePerformanceResponse = {
  rows: ChartTypePerformanceRow[];
  date_from: string | null;
  date_to: string | null;
  group_by: string[];
};

export async function getChartTypePerformance(
  token: string, filters: AnalyticsFilters = {},
): Promise<ChartTypePerformanceResponse> {
  const res = await authedFetch(`/orchestration/analytics/chart-type-performance${analyticsQueryString(filters)}`, token);
  return res.json();
}

export type WeightAdjustmentProposal = {
  affected_analytical_intent: string | null;
  affected_chart_family: string | null;
  current_chart_preference: string;
  observed_replacement: string;
  sample_size: number;
  retention_or_switch_rate: number;
  proposed_weight_adjustment: Record<string, number>;
  review_required: true;
};

export async function getWeightProposals(
  token: string, filters: { dateFrom?: string; dateTo?: string; groupDimension?: "analytical_intent" | "chart_family" } = {},
): Promise<WeightAdjustmentProposal[]> {
  const query = new URLSearchParams();
  if (filters.dateFrom) query.set("date_from", filters.dateFrom);
  if (filters.dateTo) query.set("date_to", filters.dateTo);
  if (filters.groupDimension) query.set("group_dimension", filters.groupDimension);
  const qs = query.toString();
  const res = await authedFetch(`/orchestration/analytics/weight-proposals${qs ? `?${qs}` : ""}`, token);
  return res.json();
}

export type RankingConfigurationStatus = "draft" | "approved";

export type RankingConfiguration = {
  id: string;
  ranking_version: string;
  effective_from: string;
  weights: Record<string, number>;
  status: RankingConfigurationStatus;
  created_by: string;
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
};

export async function listRankingConfigurations(token: string, status?: RankingConfigurationStatus): Promise<RankingConfiguration[]> {
  const qs = status ? `?status=${status}` : "";
  const res = await authedFetch(`/orchestration/analytics/ranking-configurations${qs}`, token);
  return res.json();
}

export type RankingConfigurationCreateRequest = {
  ranking_version: string;
  effective_from: string;
  weights: Record<string, number>;
};

export async function createRankingConfigurationDraft(
  token: string, payload: RankingConfigurationCreateRequest,
): Promise<RankingConfiguration> {
  const res = await authedFetch("/orchestration/analytics/ranking-configurations", token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`Failed to create ranking configuration draft (${res.status})`);
  return res.json();
}

export async function approveRankingConfiguration(token: string, id: string): Promise<RankingConfiguration> {
  const res = await authedFetch(`/orchestration/analytics/ranking-configurations/${id}/approve`, token, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Failed to approve ranking configuration (${res.status})`);
  return res.json();
}

// ── Dynamic Visualization Selection v7 — controlled ranking experiments
// (A/B). Admin-only on the backend (require_admin). Never exposes raw
// user-level telemetry — results are aggregate control/variant metrics
// only, same RateMetric shape v6 uses, extended with a confidence
// interval on each rate.

export type ExperimentStatus =
  | "draft" | "approved" | "scheduled" | "active" | "paused" | "completed" | "rolled_back" | "cancelled";

export type RankingExperiment = {
  id: string;
  name: string;
  description: string;
  status: ExperimentStatus;
  control_ranking_version: string;
  variant_ranking_version: string;
  control_allocation_percent: number;
  variant_allocation_percent: number;
  targeting_rules: Record<string, string[]>;
  primary_metrics: string[];
  secondary_metrics: string[];
  guardrail_metrics: string[];
  minimum_sample_size: number | null;
  start_at: string | null;
  end_at: string | null;
  created_by: string;
  approved_by: string | null;
  status_reason: string | null;
  created_at: string;
  updated_at: string;
};

export type RankingExperimentCreateRequest = {
  name: string;
  description?: string;
  control_ranking_version: string;
  variant_ranking_version: string;
  control_allocation_percent: number;
  variant_allocation_percent: number;
  targeting_rules?: Record<string, string[]>;
  primary_metrics: string[];
  secondary_metrics?: string[];
  guardrail_metrics: string[];
  minimum_sample_size?: number | null;
  start_at?: string | null;
  end_at?: string | null;
};

export type RateMetricWithConfidenceInterval = RateMetric & {
  confidence_interval_low: number;
  confidence_interval_high: number;
};

export type ExperimentGroupMetrics = {
  group: "control" | "variant";
  ranking_version: string;
  selections: number;
  recommendation_retention_rate: RateMetricWithConfidenceInterval;
  alternative_views_shown_rate: RateMetricWithConfidenceInterval;
  alternative_switch_rate: RateMetricWithConfidenceInterval;
  png_export_rate: RateMetricWithConfidenceInterval;
  csv_export_rate: RateMetricWithConfidenceInterval;
  visualization_save_rate: RateMetricWithConfidenceInterval;
  render_failure_rate: RateMetricWithConfidenceInterval;
  fallback_rate: RateMetricWithConfidenceInterval;
};

export type ExperimentResultStatus =
  | "insufficient_evidence" | "experiment_running" | "directional_result" | "eligible_for_decision" | "guardrail_failed";

export type ExperimentResultsResponse = {
  experiment_id: string;
  status: ExperimentStatus;
  result_status: ExperimentResultStatus;
  minimum_sample_size: number | null;
  control: ExperimentGroupMetrics;
  variant: ExperimentGroupMetrics;
  guardrail_findings: string[];
};

async function _experimentAction(token: string, path: string, body?: Record<string, unknown>): Promise<RankingExperiment> {
  const res = await authedFetch(`/orchestration/experiments${path}`, token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail || `Request failed (${res.status})`);
  }
  return res.json();
}

export async function listExperiments(token: string, status?: ExperimentStatus): Promise<RankingExperiment[]> {
  const qs = status ? `?status=${status}` : "";
  const res = await authedFetch(`/orchestration/experiments${qs}`, token);
  return res.json();
}

export async function getActiveExperiments(token: string): Promise<RankingExperiment[]> {
  const res = await authedFetch("/orchestration/experiments/active", token);
  return res.json();
}

export async function getExperiment(token: string, id: string): Promise<RankingExperiment> {
  const res = await authedFetch(`/orchestration/experiments/${id}`, token);
  return res.json();
}

export async function getExperimentResults(token: string, id: string): Promise<ExperimentResultsResponse> {
  const res = await authedFetch(`/orchestration/experiments/${id}/results`, token);
  return res.json();
}

export async function createExperimentDraft(token: string, payload: RankingExperimentCreateRequest): Promise<RankingExperiment> {
  const res = await authedFetch("/orchestration/experiments", token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail || `Failed to create experiment draft (${res.status})`);
  }
  return res.json();
}

export async function approveExperiment(token: string, id: string): Promise<RankingExperiment> {
  return _experimentAction(token, `/${id}/approve`);
}

export async function activateExperiment(token: string, id: string): Promise<RankingExperiment> {
  return _experimentAction(token, `/${id}/activate`);
}

export async function pauseExperiment(token: string, id: string, reason: string): Promise<RankingExperiment> {
  return _experimentAction(token, `/${id}/pause`, { reason });
}

export async function completeExperiment(token: string, id: string, reason?: string): Promise<RankingExperiment> {
  return _experimentAction(token, `/${id}/complete`, { reason: reason ?? null });
}

export async function rollbackExperiment(token: string, id: string, reason: string): Promise<RankingExperiment> {
  return _experimentAction(token, `/${id}/rollback`, { reason });
}
