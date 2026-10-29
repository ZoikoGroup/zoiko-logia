import { fetchWithSession } from "@/lib/auth-fetch";
import { supabase } from "@/lib/supabase";
import { getCurrentAccessToken } from "@/lib/session-token";
import { clearImpersonation, getImpersonation, impersonationHeaders } from "@/lib/impersonation";
import type { GovernanceDashboardViewModel } from "@/lib/governance-dashboard-types";
import type { CommandCenterViewModel, MyWorkspaceViewModel } from "@/lib/command-center-types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8010/api/v1";

export type UserPublic = {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  full_name: string;
  role: string;
  tenant_id: string;
  // Platform control plane role, separate from the tenant role. "super_admin" or null.
  platform_role?: string | null;
};

export type ProvisionRequest = {
  first_name?: string;
  last_name?: string;
  company_name?: string;
  /** Only used on the first call: "individual" → private Learner workspace,
   * "company" (default) → company workspace with the caller as Admin. */
  account_type?: "individual" | "company";
  adult_confirmed?: boolean;
};

/** FastAPI sends `detail` as a string, or for a validation error (422) as a
 * list of {loc, msg}. A list passed straight to Error() rendered as
 * "[object Object]" in the chat. */
export function describeDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => {
      if (typeof item === "string") return item;
      const entry = item as { loc?: unknown[]; msg?: string } | null;
      const field = entry?.loc?.filter((part) => part !== "body").join(".");
      return entry?.msg ? (field ? `${field}: ${entry.msg}` : entry.msg) : "";
    }).filter(Boolean);
    if (messages.length) return messages.join("; ");
  }
  if (detail && typeof detail === "object") {
    const message = (detail as { message?: unknown; msg?: unknown }).message ?? (detail as { msg?: unknown }).msg;
    if (typeof message === "string") return message;
  }
  return "The request could not be completed.";
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: unknown) {
    super(describeDetail(message));
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

// ── Forgot password (backend identity/password_reset_router.py) ───────────
// No sign-in required. The backend emails a 6-digit code from ZoikoLogia's
// own sender, then sets the new password in Supabase once the code checks out.

async function postPublic<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    const detail = typeof data?.detail === "string" ? data.detail
      : res.status === 429 ? "Too many attempts. Please wait a few minutes and try again." : "Something went wrong. Please try again.";
    throw new ApiError(res.status, detail);
  }
  return res.json();
}

export async function requestPasswordResetCode(email: string) {
  return postPublic<{ message: string; expires_in_minutes: number; code_length: number }>("/auth/password/forgot", { email });
}
export async function verifyPasswordResetCode(email: string, code: string) {
  return postPublic<{ message: string }>("/auth/password/verify", { email, code });
}
export async function resetPasswordWithCode(email: string, code: string, password: string) {
  return postPublic<{ message: string }>("/auth/password/reset", { email, code, password });
}

/** While an Admin is viewing as someone, this returns that user's profile, so
 * the role-gated navigation renders exactly what they would see. */
export async function getMe(token: string): Promise<UserPublic> {
  const res = await fetchWithSession(`${API_URL}/auth/me`, token, {
    headers: { Authorization: `Bearer ${token}`, ...impersonationHeaders() },
    // Bounded so an unreachable backend can't hold the role-gated nav on its
    // loading state indefinitely; a timeout falls back like any other failure.
    signal: AbortSignal.timeout(8000),
  });

  if (res.status === 403 && getImpersonation()) {
    // The view-as session ended or expired server-side: drop it and fall
    // back to the Admin's own profile.
    clearImpersonation();
    return getMe(token);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, describeDetail(body?.detail) || "Could not fetch current user");
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
  /** Omit to invite the user by email; they choose their own password. */
  password?: string;
  full_name: string;
  role: string;
};

export type UserCreatedResponse = UserListItem & { invited: boolean };

const IMPERSONATION_ENDED = "This impersonation session has ended.";

async function authedFetch(
  path: string,
  token: string,
  init?: RequestInit,
  { asSelf = false }: { asSelf?: boolean } = {},
): Promise<Response> {
  const send = () => fetchWithSession(`${API_URL}${path}`, token, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      // Every call made while viewing as someone carries the session, so the
      // backend answers as that user and refuses writes. Only the call that
      // ends the session itself is made as the Admin (asSelf).
      ...(asSelf ? {} : impersonationHeaders()),
    },
  });
  let res = await send();
  // 503 = the backend couldn't get a database connection in time (the shared
  // pooler's client limit or a network blip). A read is safe to repeat, so
  // retry it once after a short pause instead of showing an error for a
  // one-second blip. Writes are never retried automatically.
  const method = (init?.method ?? "GET").toUpperCase();
  if (res.status === 503 && method === "GET" && !init?.signal?.aborted) {
    const wait = Math.min(Number(res.headers.get("Retry-After")) || 1.5, 5) * 1000;
    await new Promise((resolve) => setTimeout(resolve, wait));
    if (!init?.signal?.aborted) res = await send();
  }
  if (res.status === 401 && typeof window !== "undefined") {
    // Sign out only when the login itself is gone. A renewal that failed
    // because the network had just reconnected left a valid session behind,
    // and signing out there threw the user to the login page for nothing.
    const { data } = await supabase.auth.getSession().catch(() => ({ data: { session: null } }));
    if (!data.session) {
      supabase.auth.signOut();
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
      throw new ApiError(401, "Session expired — please log in again.");
    }
    throw new ApiError(401, "Your session is being renewed. Please try again in a moment.");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    if (res.status === 403 && body?.detail === IMPERSONATION_ENDED) {
      clearImpersonation();
    }
    throw new ApiError(res.status, errorText(body?.detail) ?? `Request to ${path} failed`);
  }
  return res;
}

/** A readable message from an error `detail`. A validation error (422) sends
 * a list of objects, and an object passed as an Error message shows as
 * "[object Object]". */
export function errorText(detail: unknown): string | undefined {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => (typeof item === "string" ? item : item?.msg)).filter(Boolean);
    if (messages.length) return `The request was not accepted: ${messages.join("; ")}`;
  }
  if (detail && typeof detail === "object" && typeof (detail as { message?: unknown }).message === "string") {
    return (detail as { message: string }).message;
  }
  return undefined;
}

export async function getGovernanceDashboard(
  token: string,
  options: { environment: string; jurisdiction: string; windowDays: number },
  signal?: AbortSignal,
  fresh = false,
): Promise<GovernanceDashboardViewModel> {
  const query = new URLSearchParams({
    environment: options.environment,
    jurisdiction: options.jurisdiction,
    window_days: String(options.windowDays),
    ...(fresh ? { fresh: "1" } : {}),
  });
  const res = await authedFetch(`/governance-dashboard?${query}`, token, { signal });
  return res.json();
}

export type GateState = "passed" | "blocked" | "partial" | "not_assessed";
export type ReleaseGate = { gate: string; state: GateState; reason: string };

/** Release gate states measured from live evidence (Release Gates page). */
export async function getReleaseReadiness(token: string, signal?: AbortSignal): Promise<ReleaseGate[]> {
  const res = await authedFetch("/governance-dashboard/release-readiness", token, { signal });
  return res.json();
}

export async function getCommandCenter(
  token: string,
  context: { jurisdiction: string; framework: string; period: string },
  signal?: AbortSignal,
  fresh = false,
): Promise<CommandCenterViewModel> {
  const query = new URLSearchParams({ ...context, ...(fresh ? { fresh: "1" } : {}) });
  const res = await authedFetch(`/command-center?${query}`, token, { signal });
  return res.json();
}

export async function getMyWorkspace(token: string, signal?: AbortSignal, fresh = false): Promise<MyWorkspaceViewModel> {
  const res = await authedFetch(`/command-center/workspace${fresh ? "?fresh=1" : ""}`, token, { signal });
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

export async function createUser(token: string, payload: UserCreateRequest): Promise<UserCreatedResponse> {
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

/** Admin-only. The backend refuses a role outside the permission registry,
 * an Admin changing their own role, and demoting the last active Admin. */
export async function setUserRole(token: string, id: string, role: string): Promise<UserListItem> {
  const res = await authedFetch(`/users/${id}/role`, token, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role }),
  });
  return res.json();
}

export type MfaStatus = {
  required_for_privileged: boolean;
  privileged_role: boolean;
  current_aal: string;
};

export async function getMfaStatus(token: string): Promise<MfaStatus> {
  const res = await authedFetch("/auth/mfa/status", token);
  return res.json();
}

/** Audit hook after a factor is verified; the backend accepts it only from
 * a session that is already aal2. */
export async function recordMfaEnrolled(token: string): Promise<void> {
  await authedFetch("/auth/mfa/enrolled", token, { method: "POST" });
}

/** Revokes every session the user holds, on every device, server-side. */
export async function signOutAllSessions(token: string): Promise<void> {
  await authedFetch("/auth/sign-out-all-sessions", token, { method: "POST" });
}

/** Admin-only: removes a user's authenticator apps and ends their sessions. */
export async function resetUserMfa(token: string, userId: string): Promise<void> {
  await authedFetch(`/users/${userId}/mfa/reset`, token, { method: "POST" });
}

// ── Elevated-access governance ──────────────────────────────────────────────

export type ImpersonationSession = {
  id: string;
  target_user_id: string;
  target_name: string;
  target_email: string;
  target_role: string;
  reason: string;
  started_at: string;
  expires_at: string;
  ended_at: string | null;
};

export async function startImpersonation(
  token: string,
  payload: { target_user_id: string; reason: string; minutes: number },
): Promise<ImpersonationSession> {
  const res = await authedFetch("/auth/impersonation", token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }, { asSelf: true });
  return res.json();
}

export async function endImpersonation(token: string, sessionId: string): Promise<void> {
  await authedFetch(`/auth/impersonation/${sessionId}/end`, token, { method: "POST" }, { asSelf: true });
}

export type BreakGlassGrant = {
  id: string;
  user_id: string;
  user_name: string;
  permissions: string[];
  reason: string;
  duration_minutes: number;
  status: "requested" | "active" | "expired" | "revoked" | "rejected";
  requested_at: string;
  approved_by: string | null;
  activated_at: string | null;
  expires_at: string | null;
  ended_at: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_notes: string | null;
  needs_review: boolean;
};

export async function listBreakGlassPermissions(token: string): Promise<string[]> {
  return (await authedFetch("/break-glass/permissions", token)).json();
}

export async function listBreakGlass(token: string): Promise<BreakGlassGrant[]> {
  return (await authedFetch("/break-glass", token)).json();
}

export async function requestBreakGlass(
  token: string,
  payload: { permissions: string[]; reason: string; duration_minutes: number },
): Promise<BreakGlassGrant> {
  const res = await authedFetch("/break-glass", token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

export async function actOnBreakGlass(
  token: string,
  grantId: string,
  action: "approve" | "reject" | "revoke" | "review",
  notes?: string,
): Promise<BreakGlassGrant> {
  const res = await authedFetch(`/break-glass/${grantId}/${action}`, token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: action === "review" ? JSON.stringify({ notes }) : undefined,
  });
  return res.json();
}

export type ServiceAccountKey = {
  id: string;
  key_prefix: string;
  created_at: string;
  expires_at: string;
  revoked_at: string | null;
  last_used_at: string | null;
};

export type ServiceAccount = {
  id: string;
  name: string;
  description: string;
  role: string;
  owner_user_id: string;
  owner_name: string;
  is_active: boolean;
  created_at: string;
  keys: ServiceAccountKey[];
};

export async function listServiceAccounts(token: string): Promise<ServiceAccount[]> {
  return (await authedFetch("/service-accounts", token)).json();
}

export async function createServiceAccount(
  token: string,
  payload: { name: string; description: string; role: string; owner_user_id: string },
): Promise<ServiceAccount> {
  const res = await authedFetch("/service-accounts", token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

/** The returned `key` is shown once and never retrievable again. */
export async function issueServiceAccountKey(
  token: string,
  accountId: string,
  expiresInDays: number,
): Promise<{ key: string; key_info: ServiceAccountKey }> {
  const res = await authedFetch(`/service-accounts/${accountId}/keys`, token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ expires_in_days: expiresInDays }),
    cache: "no-store",
  });
  return res.json();
}

export async function revokeServiceAccountKey(token: string, accountId: string, keyId: string): Promise<void> {
  await authedFetch(`/service-accounts/${accountId}/keys/${keyId}/revoke`, token, { method: "POST" });
}

// ── Operations (backend app/domains/operations) ─────────────────────────────
// Every value is measured (live checks, stored health samples, real request
// timings) or entered in the registers; secret values never leave the
// backend, only whether they are set.

async function sendJson<T>(path: string, token: string, method: string, body: unknown): Promise<T> {
  const res = await authedFetch(path, token, {
    method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  return res.json();
}

export type HealthState = "operational" | "degraded" | "down" | "not_configured";

export type MonitoredService = {
  key: string; name: string; component: string; category: string; location: string;
  state: HealthState; latencyMs: number | null; detail: string;
  availability24h: number | null; samples24h: number; p95LatencyMs24h: number | null; errorRate24h: number | null;
  lastSampleAt: string | null; ownerId: string | null; owner: string | null;
  openAlerts: { ref: string; state: string }[]; dependsOn: string[];
};

export type DependencyNode = {
  key: string; name: string; state: HealthState | "impacted"; children: DependencyNode[];
};

export type StatusOverview = {
  checkedAt: string;
  summary: {
    platformState: "operational" | "degraded" | "down"; impacted: string[];
    availability24h: number | null; availabilityObjective: number;
    apiP95Ms: number | null; apiP95ObjectiveMs: number;
    activeAlerts: number; unavailable: number; blockedJobs: number;
  };
  services: MonitoredService[];
  hourly: { hour: string; availability: number | null; p50: number | null; p95: number | null }[];
  dependencyMap: DependencyNode;
  events: { at: string; serviceKey: string; service: string; from: string; to: string; detail: string }[];
  slo: { key: string; name: string; samples: number; availability: number; objective: number;
    budgetRemainingPct: number | null; met: boolean }[];
  jobs: {
    sampler: { enabled: boolean; intervalSeconds: number; retentionDays: number; lastSampleAt: string | null };
    documents: { available: boolean; stuck: number; processing: number; failed24h: number };
    queue: { state: HealthState; detail: string };
  };
};

export async function getOperationsStatus(token: string, signal?: AbortSignal): Promise<StatusOverview> {
  return (await authedFetch("/operations/status", token, { signal })).json();
}

export async function setServiceOwner(token: string, serviceKey: string, ownerUserId: string) {
  return sendJson<{ serviceKey: string; ownerId: string; owner: string }>(
    `/operations/services/${serviceKey}/owner`, token, "PUT", { owner_user_id: ownerUserId });
}

export type Assignee = { id: string; name: string; role: string };

export async function getAssignees(token: string, signal?: AbortSignal): Promise<Assignee[]> {
  return (await authedFetch("/operations/assignees", token, { signal })).json();
}

export type AlertState = "unacknowledged" | "acknowledged" | "investigating" | "contained" | "resolved" | "suppressed";
export type AlertSeverity = "Critical" | "High" | "Medium" | "Low";
export type HistoryEntry = { at: string; action: string; actorId: string | null; actor: string; note: string };

export type OperationsAlert = {
  id: string; ref: string; origin: "governance" | "health" | "manual"; category: string; severity: AlertSeverity;
  title: string; detail: string; href: string; serviceKey: string | null; state: AlertState;
  ownerId: string | null; owner: string | null; detectedAt: string; lastSeenAt: string;
  acknowledgedAt: string | null; acknowledgedBy: string | null; resolvedAt: string | null; resolvedBy: string | null;
  history: HistoryEntry[];
};

export type AlertsView = {
  alerts: OperationsAlert[];
  summary: {
    active: number; critical: number; unacknowledged: number; unowned: number; safetyBlocks: number;
    bySeverity: Record<AlertSeverity, number>; byCategory: { category: string; count: number }[];
  };
  delivery: { channelConfigured: boolean; channel: string };
  generatedAt: string;
};

export async function getOperationsAlerts(token: string, signal?: AbortSignal, fresh = false): Promise<AlertsView> {
  return (await authedFetch(`/operations/alerts${fresh ? "?fresh=true" : ""}`, token, { signal })).json();
}

export type AlertAction = "acknowledge" | "investigate" | "assign" | "escalate" | "contain" | "resolve" | "suppress" | "reopen";

export async function actOnAlert(
  token: string, alertId: string, payload: { action: AlertAction; note?: string; owner_user_id?: string },
): Promise<OperationsAlert> {
  return sendJson(`/operations/alerts/${alertId}/actions`, token, "POST", payload);
}

export async function raiseAlert(
  token: string,
  payload: { title: string; severity: AlertSeverity; category: string; detail: string; service_key?: string | null },
): Promise<OperationsAlert> {
  return sendJson("/operations/alerts", token, "POST", payload);
}

export type GateStatus = "pass" | "open" | "fail";
export type Gate = {
  key: string; label: string; description?: string; derived?: boolean; status: GateStatus;
  note?: string; byName?: string; at?: string | null;
};
export type Level = "critical" | "high" | "medium" | "low";

export type ProviderDecision = "approved_scoped" | "conditional" | "under_review" | "on_hold" | "suspended";
export type ProviderRecord = {
  id: string; ref: string; name: string; category: string; categoryLabel: string; service: string;
  configKey: string | null; inUse: boolean; decision: ProviderDecision; criticality: Level; region: string;
  approvedUse: string; dataClassification: string; contractState: string; ownerId: string | null; owner: string | null;
  nextReviewAt: string | null; reviewDue: boolean; gates: Gate[]; gatesPassed: number; gatesTotal: number;
  createdBy: string | null; createdAt: string; decidedBy: string | null; decidedAt: string | null; history: HistoryEntry[];
};
export type ProviderRegister = {
  providers: ProviderRecord[];
  detected: { configKey: string; name: string; category: string; service: string }[];
  summary: { registered: number; approved: number; inReview: number; conditional: number; underReview: number;
    blocked: number; reviewActions: number };
  resilience: { critical: number; fallbackDocumented: number; untestedExits: number };
  categories: Record<string, string>;
  generatedAt: string;
};
export type ProviderInput = {
  name: string; category: string; service?: string; config_key?: string | null; criticality?: Level; region?: string;
  approved_use?: string; data_classification?: string; contract_state?: string; owner_user_id?: string | null;
  next_review_at?: string | null;
};

export async function getProviderRegister(token: string, signal?: AbortSignal): Promise<ProviderRegister> {
  return (await authedFetch("/operations/providers", token, { signal })).json();
}
export async function registerProvider(token: string, payload: ProviderInput): Promise<ProviderRecord> {
  return sendJson("/operations/providers", token, "POST", payload);
}
export async function updateProvider(token: string, id: string, payload: Partial<ProviderInput>): Promise<ProviderRecord> {
  return sendJson(`/operations/providers/${id}`, token, "PATCH", payload);
}
export async function setProviderGate(token: string, id: string, gate: string, status: GateStatus, note: string): Promise<ProviderRecord> {
  return sendJson(`/operations/providers/${id}/gates/${gate}`, token, "PUT", { status, note });
}
export async function decideProvider(token: string, id: string, decision: ProviderDecision, note: string): Promise<ProviderRecord> {
  return sendJson(`/operations/providers/${id}/decision`, token, "POST", { decision, note });
}

export type IntegrationAuthorization = "approved_scoped" | "pending" | "under_review" | "on_hold" | "suspended";
export type IntegrationRecord = {
  id: string; ref: string; name: string; category: string; categoryLabel: string; providerId: string | null;
  provider: string | null; healthKey: string | null; health: HealthState | "not_enabled" | "not_monitored";
  healthDetail: string; healthCheckedAt: string | null; authorization: IntegrationAuthorization;
  dataFlow: "inbound" | "outbound" | "bidirectional"; region: string; riskTier: Level; authMethod: string;
  scopesRequested: string[]; scopesApproved: string[]; ownerId: string | null; owner: string | null;
  gates: Gate[]; gatesPassed: number; gatesTotal: number; scopeException: boolean;
  createdBy: string | null; createdAt: string; decidedBy: string | null; decidedAt: string | null; history: HistoryEntry[];
};
export type IntegrationRegister = {
  integrations: IntegrationRecord[];
  detected: { healthKey: string; name: string; category: string }[];
  summary: { registered: number; approved: number; pending: number; degraded: number; blocked: number; scopeExceptions: number };
  controls: Record<"least_privilege" | "secret_vault" | "replay_idempotency" | "residency_privacy", { passed: number; total: number }>;
  exceptions: { id: string; ref: string; title: string; action: "HOLD" | "REVIEW" | "BLOCK" }[];
  categories: Record<string, string>;
  providers: { id: string; label: string }[];
  generatedAt: string;
};
export type IntegrationInput = {
  name: string; category: string; provider_id?: string | null; health_key?: string | null;
  data_flow?: "inbound" | "outbound" | "bidirectional"; region?: string; risk_tier?: Level; auth_method?: string;
  scopes_requested?: string[]; scopes_approved?: string[]; owner_user_id?: string | null;
};

export async function getIntegrationRegister(token: string, signal?: AbortSignal): Promise<IntegrationRegister> {
  return (await authedFetch("/operations/integrations", token, { signal })).json();
}
export async function registerIntegration(token: string, payload: IntegrationInput): Promise<IntegrationRecord> {
  return sendJson("/operations/integrations", token, "POST", payload);
}
export async function updateIntegration(token: string, id: string, payload: Partial<IntegrationInput>): Promise<IntegrationRecord> {
  return sendJson(`/operations/integrations/${id}`, token, "PATCH", payload);
}
export async function setIntegrationGate(token: string, id: string, gate: string, status: GateStatus, note: string): Promise<IntegrationRecord> {
  return sendJson(`/operations/integrations/${id}/gates/${gate}`, token, "PUT", { status, note });
}
export async function decideIntegration(token: string, id: string, decision: IntegrationAuthorization, note: string): Promise<IntegrationRecord> {
  return sendJson(`/operations/integrations/${id}/decision`, token, "POST", { decision, note });
}

// ── Review, Escalation & Audit (backend app/domains/review_console) ────────

export type ReviewPerson = { id: string; name: string; role: string; expert: boolean };

export async function getReviewPeople(token: string, signal?: AbortSignal): Promise<ReviewPerson[]> {
  return (await authedFetch("/review/people", token, { signal })).json();
}

export type EscalationRow = {
  id: string; queryId: string; question: string; topic: string; severity: "Critical" | "High" | "Medium" | "Low";
  riskLevel: string; subClass: string | null; trigger: string; jurisdiction: string;
  status: "open" | "expert_review" | "escalated" | "resolved" | "refused"; rawStatus: string; origin: string;
  requesterId: string | null; requester: string | null; assigneeId: string | null; assignee: string | null;
  reviewerRole: string | null; decidedBy: string | null; decision: string | null; slaDeadline: string | null;
  sla: "overdue" | "due_today" | "due_tomorrow" | "within" | "closed" | "none"; createdAt: string | null;
  resolvedAt: string | null; detail: string; routeReason: string; evidenceRefs: unknown[];
  reviewCase: { id: string; status: string; decision: string | null; source: string } | null;
  closureRestricted: boolean; closureReason: string; nextSteps: string[]; history: HistoryEntry[];
};
export type EscalationQueue = {
  escalations: EscalationRow[];
  summary: { open: number; critical: number; overdue: number; expertReview: number; closureRestricted: number;
    unassigned: number; linkedToReview: number; bySeverity: Record<string, number> };
  overrides: { id: string; scope: string; reason: string; originalRoute: string; newRoute: string; actor: string;
    role: string; expiresAt: string | null }[];
  generatedAt: string;
};

export async function getEscalationQueue(token: string, signal?: AbortSignal): Promise<EscalationQueue> {
  return (await authedFetch("/review/escalations", token, { signal })).json();
}
export async function actOnEscalationCase(token: string, id: string, payload: { action: string; note?: string; assignee_id?: string }) {
  return sendJson<{ id: string; status: string }>(`/review/escalations/${id}/actions`, token, "POST", payload);
}
export async function raiseEscalation(token: string, payload: { topic: string; detail: string; risk_level: string; jurisdiction: string }) {
  return sendJson<{ id: string }>("/review/escalations", token, "POST", payload);
}

export type TicketMessage = { at: string; kind: "reply" | "note" | "customer" | "system"; actorId: string | null; actor: string; body: string };
export type SupportTicketRow = {
  id: string; ref: string; subject: string; description: string; category: string; priority: "P1" | "P2" | "P3" | "P4";
  priorityLabel: string; status: "open" | "in_progress" | "investigating" | "waiting_customer" | "escalated" | "resolved";
  jurisdiction: string; requesterId: string; requester: string; ownerId: string | null; owner: string | null;
  queryId: string | null; sourceId: string | null; createdAt: string | null; firstResponseAt: string | null;
  resolvedAt: string | null; resolutionNote: string; escalationId: string | null; incidentId: string | null;
  sla: { state: "on_track" | "at_risk" | "breached" | "paused" | "met"; dueAt: string; remainingSeconds: number;
    firstResponseDueAt: string; firstResponseMet: boolean | null; targetHours: number; firstResponseHours: number };
  messages: TicketMessage[];
};
export type TicketRegister = {
  tickets: SupportTicketRow[];
  summary: { open: number; atRisk: number; breaches: number; waitingCustomer: number; escalated: number; unassigned: number;
    firstResponsePct: number | null; resolutionPct: number | null; byPriority: Record<string, number> };
  policy: { priority: string; label: string; firstResponseHours: number; resolutionHours: number }[];
  categories: string[];
  activity: (TicketMessage & { ticketId: string; ref: string })[];
  generatedAt: string;
};

export async function getTicketRegister(token: string, signal?: AbortSignal): Promise<TicketRegister> {
  return (await authedFetch("/review/tickets", token, { signal })).json();
}
export async function createSupportTicket(token: string, payload: { subject: string; description: string; category: string; priority: string; jurisdiction?: string }) {
  return sendJson<{ id: string }>("/review/tickets", token, "POST", payload);
}
export async function actOnTicket(token: string, id: string, payload: { action: string; body?: string; owner_id?: string; status?: string }) {
  return sendJson<SupportTicketRow>(`/review/tickets/${id}/actions`, token, "POST", payload);
}

export type IncidentRow = {
  id: string; title: string; severity: "Critical" | "High" | "Medium" | "Low"; status: "OPEN" | "CONTAINED" | "RESOLVED";
  source: string; sourceLabel: string; queryId: string | null; subClass: string | null; ownerId: string | null; owner: string | null;
  openedAt: string | null; resolvedAt: string | null; resolutionNote: string; hoursOpen: number | null;
  linkedEventIds: string[]; ticketId: string | null;
  timeline: { timestamp: string; actor: string; actorId?: string | null; action: string; note: string }[];
};
export type IncidentRegister = {
  incidents: IncidentRow[];
  summary: { open: number; contained: number; critical: number; high: number; unowned: number; resolved30d: number;
    mttrHours: number | null; bySeverity: Record<string, number> };
  sources30d: { source: string; count: number }[];
  generatedAt: string;
};

export async function getIncidentRegister(token: string, signal?: AbortSignal): Promise<IncidentRegister> {
  return (await authedFetch("/review/incidents", token, { signal })).json();
}
export async function openIncident(token: string, payload: { title: string; severity: string; note: string; event_id?: string }) {
  return sendJson<{ id: string }>("/review/incidents", token, "POST", payload);
}
export async function actOnIncident(token: string, id: string, payload: { action: string; note?: string; owner_id?: string; event_id?: string; severity?: string }) {
  return sendJson<IncidentRow>(`/review/incidents/${id}/actions`, token, "POST", payload);
}

export type AuditFamily = "ai" | "access" | "privileged" | "source" | "user";
export type AuditEventRow = {
  id: string; event: string; family: AuditFamily; familyLabel: string; risk: "critical" | "high" | "medium" | "low";
  outcome: "denied" | "blocked" | "failed" | "pending" | "recorded"; at: string | null; ingestedAt: string | null;
  actorId: string | null; actor: string; actorType: string; service: string; subjectType: string; subjectId: string;
  correlationId: string | null; chainHashed: boolean; classification: string; payload: Record<string, unknown>;
};
export type AuditExport = {
  id: string; ref: string; purpose: string; filters: Record<string, string>; status: "pending" | "approved" | "rejected";
  requestedBy: string; requestedById: string; requestedAt: string | null; decidedBy: string | null; decidedAt: string | null;
  decisionNote: string; expiresAt: string | null; downloadable: boolean; downloads: number;
};
export type AuditOverview = {
  summary: { total: number; last30d: number; denied30d: number; deniedHighRisk30d: number; openInvestigations: number;
    investigationsWithEvidence: number; chainPassed: boolean; eventsChecked: number; brokenAt: string | null;
    chainVerifiedAt: string; exportsPending: number; ingestionLagP95Seconds: number | null };
  families: { key: AuditFamily; label: string; count: number; pct: number }[];
  priority: AuditEventRow[];
  exports: AuditExport[];
  generatedAt: string;
};
export type AuditEventPage = { events: AuditEventRow[]; total: number; offset: number; families: Record<string, string>; windowDays: number; generatedAt: string };

export async function getAuditOverview(token: string, signal?: AbortSignal, fresh = false): Promise<AuditOverview> {
  return (await authedFetch(`/review/audit/overview${fresh ? "?fresh=true" : ""}`, token, { signal })).json();
}
export async function getAuditEvents(
  token: string, filters: { family?: string; risk?: string; outcome?: string; q?: string; days?: number; offset?: number; limit?: number },
  signal?: AbortSignal,
): Promise<AuditEventPage> {
  const qs = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => { if (v !== undefined && v !== "") qs.set(k, String(v)); });
  return (await authedFetch(`/review/audit/events?${qs.toString()}`, token, { signal })).json();
}
export type TraceRow = {
  correlationId: string; title: string; kind: string; events: number; firstAt: string | null; lastAt: string | null;
  integrity: "verified" | "exception"; complete: boolean; state: "verified" | "partial" | "restricted" | "review_open" | "refused";
  reviewCase: string | null; reviewStatus: string | null; incident: string | null; refused: boolean; humanReview: boolean;
};
export type TraceRegister = {
  traces: TraceRow[];
  summary: { recorded30d: number; shown: number; replayReady: number; holds: number; humanReviewsOpen: number; exportHolds: number };
  integrity: { hashed: number; complete: number; reviewed: number; total: number };
  generatedAt: string;
};
export async function getTraceRegister(token: string, signal?: AbortSignal): Promise<TraceRegister> {
  return (await authedFetch("/review/audit/traces", token, { signal })).json();
}
export async function requestAuditExport(token: string, purpose: string, filters: Record<string, string | number>) {
  return sendJson<{ id: string; ref: string }>("/review/audit/exports", token, "POST", { purpose, filters });
}
export async function decideAuditExport(token: string, id: string, approve: boolean, note: string) {
  return sendJson<{ id: string; status: string }>(`/review/audit/exports/${id}/decision`, token, "POST", { approve, note });
}
/** Downloads an approved export as a CSV file in the browser. */
export async function downloadAuditExport(token: string, id: string): Promise<void> {
  const res = await authedFetch(`/review/audit/exports/${id}/download`, token);
  const blob = await res.blob();
  const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "")?.[1] ?? "audit-export.csv";
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Billing & Usage (backend app/domains/billing) ───────────────────────────

export type BillingMeter = { key: string; label: string; unit: string; event: string };
export type ChargeLine = {
  key: string; label: string; unit: string; quantity: number; included: number; billable: number;
  rateCents: number; amountCents: number;
  status: "contracted" | "measured" | "disputed" | "waived" | "unpriced" | "approved_credit"; excluded: boolean;
};
export type BillingPlan = {
  id: string; version: number; status: "proposed" | "active" | "superseded" | "rejected"; name: string; currency: string;
  commitmentCents: number; included: Record<string, number>; rates: Record<string, number>; softBudgetCents: number;
  hardCapCents: number; effectiveFrom: string; note: string; proposedBy: string; proposedById: string; proposedAt: string | null;
  decidedBy: string | null; decidedAt: string | null;
};
export type BillingAdjustmentRow = {
  id: string; period: string; kind: "credit" | "dispute"; meter: string | null; amountCents: number; reason: string;
  status: string; createdBy: string; createdById: string; createdAt: string | null; decidedBy: string | null; decisionNote: string;
};
export type BillingStatementRow = {
  id: string; ref: string; period: string; currency: string; planVersion: number; subtotalCents: number; creditsCents: number;
  totalCents: number; status: "issued" | "paid"; issuedBy: string; issuedAt: string | null; paidAt: string | null;
  paymentReference: string; lines: ChargeLine[];
};
export type BillingOverview = {
  period: string; now: string; meters: BillingMeter[];
  current: {
    period: string; planVersion: number | null; currency: string; lines: ChargeLine[]; subtotalCents: number;
    creditsCents: number; totalCents: number; variableCents: number; excludedCents: number; priced: boolean;
    usage: { totals: Record<string, number>; daily: Record<string, Record<string, number>>; engagements: Record<string, number> };
  };
  summary: {
    estimatedCents: number; commitmentCents: number; variableCents: number; interactions: number; softBudgetCents: number;
    hardCapCents: number; budgetUsedPct: number | null; projectedCents: number | null; openDisputes: number;
    excludedCents: number; priced: boolean;
  };
  trend: { period: string; totalCents: number; interactions: number; estimate: boolean; priced: boolean }[];
  allocation: { engagementId: string | null; name: string; interactions: number; share: number; amountCents: number }[];
  plan: BillingPlan | null; pendingPlan: BillingPlan | null; planHistory: BillingPlan[];
  adjustments: BillingAdjustmentRow[]; statements: BillingStatementRow[]; closablePeriods: string[];
  trail: { id: string; event: string; at: string | null; actor: string; detail: Record<string, unknown> }[];
};

export async function getBillingOverview(token: string, signal?: AbortSignal): Promise<BillingOverview> {
  return (await authedFetch("/billing/overview", token, { signal })).json();
}
export async function proposeBillingPlan(token: string, payload: {
  name: string; currency: string; commitment_cents: number; included: Record<string, number>; rates: Record<string, number>;
  soft_budget_cents: number; hard_cap_cents: number; effective_from: string; note: string;
}) {
  return sendJson<{ id: string; version: number }>("/billing/plans", token, "POST", payload);
}
export async function decideBillingPlan(token: string, id: string, approve: boolean, note: string) {
  return sendJson<{ id: string; status: string }>(`/billing/plans/${id}/decision`, token, "POST", { approve, note });
}
export async function addBillingAdjustment(token: string, payload: { kind: "credit" | "dispute"; period: string; reason: string; amount_cents?: number; meter?: string }) {
  return sendJson<{ id: string; status: string }>("/billing/adjustments", token, "POST", payload);
}
export async function decideBillingAdjustment(token: string, id: string, decision: string, note: string) {
  return sendJson<{ id: string; status: string }>(`/billing/adjustments/${id}/decision`, token, "POST", { decision, note });
}
export async function closeBillingPeriod(token: string, period: string) {
  return sendJson<{ id: string; ref: string }>("/billing/statements", token, "POST", { period });
}
export async function markStatementPaid(token: string, id: string, reference: string) {
  return sendJson<{ id: string; status: string }>(`/billing/statements/${id}/paid`, token, "POST", { reference });
}
export async function downloadBillingReport(token: string, period: string): Promise<void> {
  const res = await authedFetch(`/billing/report?period=${encodeURIComponent(period)}`, token);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = `billing-${period}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Administration (backend app/domains/admin_governance) ──────────────────

export type ActivityEvent = {
  id: string; event: string; at: string; actor: string; subjectType: string; subjectId: string;
  detail: Record<string, unknown>;
};

export async function getAdminActivity(token: string, subjectId: string, signal?: AbortSignal): Promise<ActivityEvent[]> {
  return (await authedFetch(`/admin/activity?subject_id=${encodeURIComponent(subjectId)}`, token, { signal })).json();
}

// Tenant Settings
export type ControlAuthority = "global_locked" | "deployment" | "tenant_scoped";
export type ControlState = "enforced" | "staged" | "review_due" | "blocked" | "not_configured";
export type SettingRequest = {
  id: string; ref: string; key: string; setting: string; from: string; to: string; reason: string;
  status: "pending" | "applied" | "rejected" | "withdrawn"; requestedBy: string; requestedById: string;
  requestedAt: string | null; decidedBy: string | null; decidedAt: string | null; decisionNote: string;
};
export type TenantControl = {
  id: string; key: string | null; name: string; domain: string; authority: ControlAuthority; state: ControlState;
  risk: "critical" | "high" | "medium" | "low"; value: string; deploymentValue: string; tenantValue: string | null;
  rawEffective: boolean | number | null; kind: "bool" | "int" | null; unit: string; description: string; rule: string;
  tightened: boolean; changedAt: string | null; changeAuthority: string; pendingRequest: string | null;
  history: SettingRequest[];
};
export type TenantSettingsConsole = {
  tenant: { name: string; id: string; policyVersion: string; evaluatedAt: string; region: string };
  controls: TenantControl[];
  requests: SettingRequest[];
  hierarchy: { level: number; title: string; detail: string }[];
  summary: { effectiveControls: number; totalControls: number; stagedRequests: number; prohibitedOverrides: number;
    reviewsDue: number; tightened: number; activeExceptions: number };
  activity: ActivityEvent[];
  generatedAt: string;
};

export async function getTenantSettingsConsole(token: string, signal?: AbortSignal): Promise<TenantSettingsConsole> {
  return (await authedFetch("/admin/tenant-settings", token, { signal })).json();
}
export async function requestSettingChange(token: string, key: string, value: boolean | number, reason: string) {
  return sendJson<{ id: string; ref: string; status: string }>("/admin/settings/changes", token, "POST", { key, value, reason });
}
export async function decideSettingChange(token: string, id: string, approve: boolean, note: string) {
  return sendJson<{ id: string; ref: string; status: string }>(`/admin/settings/changes/${id}/decision`, token, "POST", { approve, note });
}

// Users & Teams
export type GateCheck = { label: string; status: "pass" | "open" | "fail"; note?: string; detail?: string };
export type MemberRow = {
  id: string; name: string; email: string; role: string; privileged: boolean; teams: string[];
  status: "active" | "invited" | "inactive" | "offboarding"; isActive: boolean;
  identity: "mfa" | "password_only" | "invite_pending" | "unknown"; providers: string[];
  lastSignInAt: string | null; invitedAt: string | null; createdAt: string | null;
  reviewDueAt: string; reviewOverdue: boolean;
  lastReview: { at: string | null; decision: string; reviewer: string; role: string } | null;
  blockers: { kind: string; label: string }[]; offboardingGates: GateCheck[];
};
export type TeamRow = {
  id: string; name: string; description: string; ownerId: string | null; owner: string | null;
  memberIds: string[]; members: number; createdAt: string | null;
};
export type UsersOverview = {
  members: MemberRow[]; teams: TeamRow[];
  summary: { activeMembers: number; openInvitations: number; staleInvitations: number; activeTeams: number;
    ownedTeams: number; reviewsDue: number; reviewsDueSoon: number; offboardingCases: number; inactive: number };
  priorities: { kind: string; userId: string; title: string; detail: string }[];
  controls: GateCheck[];
  authStatusAvailable: boolean;
  generatedAt: string;
};

export async function getUsersOverview(token: string, signal?: AbortSignal): Promise<UsersOverview> {
  return (await authedFetch("/admin/users-overview", token, { signal })).json();
}
export async function createTeam(token: string, payload: { name: string; description?: string; owner_user_id?: string | null }) {
  return sendJson<{ id: string; name: string }>("/admin/teams", token, "POST", payload);
}
export async function updateTeam(token: string, id: string, payload: { owner_user_id?: string | null; add?: string[]; remove?: string[] }) {
  return sendJson<{ id: string; name: string }>(`/admin/teams/${id}`, token, "PATCH", payload);
}
export async function recordAccessReview(token: string, payload: { user_id: string; decision: "certified" | "role_changed" | "deactivated"; note: string }) {
  return sendJson<{ id: string; decision: string }>("/admin/access-reviews", token, "POST", payload);
}

// Roles & Permissions
export type RoleRow = {
  name: string; purpose: string; scope: string; permissions: string[]; people: number; serviceAccounts: number;
  privileged: boolean; stepUp: string[]; boundary: string; assignableToServiceAccounts: boolean;
  sodConflicts: { permissions: string[]; reason: string }[]; reviewInterval: number;
};
export type RolesConsole = {
  roles: RoleRow[];
  permissions: { key: string; label: string; stepUp: boolean }[];
  sodRules: { permissions: string[]; reason: string; roles: string[] }[];
  policyTests: { label: string; passed: boolean; detail: string }[];
  unrecognisedRoles: { name: string; people: number }[];
  summary: { roles: number; privilegedRoles: number; identities: number; people: number; serviceAccounts: number;
    sodConflicts: number; peopleWithConflicts: number; reviewsDue: number; reviewsCompleted: number;
    activeBreakGlass: number; testsPassed: number; testsTotal: number };
  events: ActivityEvent[];
  generatedAt: string;
};

export async function getRolesConsole(token: string, signal?: AbortSignal): Promise<RolesConsole> {
  return (await authedFetch("/admin/roles-console", token, { signal })).json();
}
export async function simulateAccess(token: string, payload: { role: string; permission: string; session_mfa: boolean }) {
  return sendJson<{ decision: "allow" | "deny" | "step_up"; reason: string }>("/admin/roles/simulate", token, "POST", payload);
}

// Service Accounts
export type ServiceAccountRow = {
  id: string; name: string; description: string; role: string; permissions: string[]; ownerId: string; owner: string;
  ownerActive: boolean; createdBy: string; createdAt: string | null; isActive: boolean;
  state: "active" | "restricted" | "quarantined" | "dormant" | "no_credential" | "disabled";
  risk: "critical" | "high" | "medium" | "low"; liveKeys: number; expiringKeys: number; nextExpiry: string | null;
  lastUsedAt: string | null; checks: GateCheck[]; checksPassed: number;
  sodConflicts: { permissions: string[]; reason: string }[];
  keys: { id: string; prefix: string; createdAt: string | null; expiresAt: string | null; revokedAt: string | null; lastUsedAt: string | null }[];
};
export type ServiceAccountsOverview = {
  accounts: ServiceAccountRow[];
  summary: { accounts: number; liveKeys: number; renewals: number; scopeExceptions: number; ownershipReviews: number;
    quarantined: number; states: Record<string, number> };
  generatedAt: string;
};

export async function getServiceAccountsOverview(token: string, signal?: AbortSignal): Promise<ServiceAccountsOverview> {
  return (await authedFetch("/admin/service-accounts-overview", token, { signal })).json();
}
export async function transferServiceAccount(token: string, id: string, ownerUserId: string) {
  return sendJson<{ id: string; ownerId: string }>(`/admin/service-accounts/${id}/owner`, token, "PUT", { owner_user_id: ownerUserId });
}

// Entities / Clients
export type EngagementRow = {
  id: string; name: string; status: string; rightsVersion: string; createdAt: string | null;
  activeMembers: number; revokedMembers: number;
  members: { userId: string; name: string; role: string; status: string; grantedAt: string | null; revokedAt: string | null; operations: string[] }[];
};
export type EntitiesOverview = {
  engagements: EngagementRow[];
  summary: { engagements: number; active: number; members: number; revoked: number; withoutMembers: number };
  legalEntityRegister: { available: boolean; reason: string };
  generatedAt: string;
};

export async function getEntitiesOverview(token: string, signal?: AbortSignal): Promise<EntitiesOverview> {
  return (await authedFetch("/admin/entities", token, { signal })).json();
}
// POST /engagements returns EngagementPublic (id, name, status, rights_version).
export async function createEngagement(token: string, name: string): Promise<Engagement> {
  return sendJson<Engagement>("/engagements", token, "POST", { name });
}
export async function addEngagementMember(token: string, engagementId: string, userId: string) {
  return sendJson<{ id: string }>(`/engagements/${engagementId}/members`, token, "POST", { user_id: userId });
}
export async function revokeEngagementMember(token: string, engagementId: string, userId: string): Promise<void> {
  await authedFetch(`/engagements/${engagementId}/members/${userId}`, token, { method: "DELETE" });
}

// Release Gates
export type ReleaseStatus = "validating" | "on_hold" | "approval_queue" | "approved" | "deployed" | "rolled_back";
export type ReleaseGateRow = {
  key: string; number: number; label: string; description: string; derived: boolean;
  status: "pass" | "open" | "fail"; note: string; byName?: string; at?: string | null;
};
export type ReleaseCandidate = {
  id: string; ref: string; name: string; version: string; component: string; changeRef: string; description: string;
  risk: "critical" | "high" | "medium" | "low"; ownerId: string | null; owner: string | null; status: ReleaseStatus;
  stage: string; gates: ReleaseGateRow[]; passed: number; failed: number; pending: number;
  rollout: { step: string; detail: string; status: string }[];
  createdBy: string; createdById: string; createdAt: string | null; approvedBy: string | null; approvedAt: string | null;
  deployedAt: string | null; rolledBackAt: string | null; history: HistoryEntry[];
};
export type ReleaseRegister = {
  releases: ReleaseCandidate[];
  summary: { records: number; onHold: number; validating: number; awaitingApproval: number; approved: number;
    deployed: number; rolledBack: number };
  readiness: ReleaseGate[];
  components: string[];
  generatedAt: string;
};

export async function getReleaseRegister(token: string, signal?: AbortSignal): Promise<ReleaseRegister> {
  return (await authedFetch("/admin/releases", token, { signal })).json();
}
export async function createRelease(token: string, payload: {
  name: string; version: string; component: string; change_ref?: string; description?: string;
  risk?: "critical" | "high" | "medium" | "low"; owner_user_id?: string | null;
}) {
  return sendJson<{ id: string; ref: string }>("/admin/releases", token, "POST", payload);
}
export async function setReleaseGate(token: string, id: string, gate: string, status: GateStatus, note: string) {
  return sendJson<{ id: string; ref: string }>(`/admin/releases/${id}/gates/${gate}`, token, "PUT", { status, note });
}
export async function actOnRelease(token: string, id: string, action: "approve" | "deploy" | "rollback", note = "") {
  return sendJson<{ id: string; ref: string; status: string }>(`/admin/releases/${id}/actions`, token, "POST", { action, note });
}

export type RoleMatrixEntry = { name: string; purpose: string; permissions: string[]; activeUsers: number };

export async function getRolesMatrix(
  token: string, signal?: AbortSignal,
): Promise<{ roles: RoleMatrixEntry[]; unrecognisedRoles: { name: string; activeUsers: number }[] }> {
  return (await authedFetch("/admin/roles-matrix", token, { signal })).json();
}

export type UsageView = {
  totals: {
    questions_all_time: number; questions_this_month: number; active_users_this_month: number;
    saved_answers: number; drafts: number; documents: number; generated_files: number;
  };
  questionsByMonth: { month: string; label: string; questions: number }[];
  billing: { connected: boolean; reason: string };
  generatedAt: string;
};

export async function getUsage(token: string, signal?: AbortSignal): Promise<UsageView> {
  return (await authedFetch("/admin/usage", token, { signal })).json();
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

export async function listSyllabusPathways(token: string, signal?: AbortSignal): Promise<SyllabusPathway[]> {
  const res = await authedFetch("/learning/pathways", token, { signal });
  return res.json();
}

export async function listTopicMapNodes(token: string, signal?: AbortSignal): Promise<TopicMapNode[]> {
  const res = await authedFetch("/learning/topics", token, { signal });
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
  file_path?: string | null;
  source_url?: string | null;
  quality_state?: string;
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
  rights?: Record<string, boolean>;
  terms_reference?: string;
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

export async function listSources(token: string, category?: string, signal?: AbortSignal): Promise<Source[]> {
  const query = category ? `?category=${encodeURIComponent(category)}` : "";
  const res = await authedFetch(`/sources${query}`, token, { signal });
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
  form.set("rights_json", JSON.stringify(payload.rights ?? {}));
  form.set("terms_reference", payload.terms_reference ?? "");
  if (payload.file) form.set("file", payload.file);
  const res = await authedFetch("/sources", token, {
    method: "POST",
    body: form,
  });
  return res.json();
}

export async function getExpiringSource(token: string, signal?: AbortSignal): Promise<ExpiringSource | null> {
  const res = await authedFetch("/sources/expiring", token, { signal });
  return res.json();
}

export async function getJurisdictionSummary(token: string, signal?: AbortSignal): Promise<JurisdictionSummary[]> {
  const res = await authedFetch("/sources/jurisdiction-summary", token, { signal });
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

export type RuntimeModel = {
  role: string;
  provider: string;
  model: string;
  setting: string;
  source: string;
  provider_approved: boolean;
  key_configured: boolean;
  active: boolean;
  used_by: string;
};

export type RegistryOverview = {
  active_adapter: string;
  approved_providers: string[];
  runtime_models: RuntimeModel[];
  registry_matches: Record<string, string[]>;
  unused_registry_models: string[];
  prompt_count: number;
  usage: {
    by_provider: { provider: string; runs: number; last_run: string | null }[];
    by_prompt: Record<string, { runs: number; last_run: string | null }>;
  };
};

export type SystemInstruction = {
  name: string;
  used_by: string;
  sha256: string;
  characters: number;
  text: string;
};

export type RegistryChange = {
  time: string | null;
  kind: "prompt_approved";
  summary: string;
  actor: string | null;
};

export async function getRegistryOverview(token: string): Promise<RegistryOverview> {
  return (await authedFetch("/model-gateway/registry", token)).json();
}

export async function getSystemInstructions(token: string): Promise<SystemInstruction[]> {
  return (await authedFetch("/model-gateway/system-instructions", token)).json();
}

export async function getRegistryChangeHistory(token: string): Promise<RegistryChange[]> {
  return (await authedFetch("/model-gateway/change-history", token)).json();
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

// â”€â”€ Ask Kritonâ„¢ — ZL-ENG-02 Â§12 Canonical Response Contract â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

export type AskKritonRequest = {
  turn_id?: string;
  request_id?: string;
  query: string;
  source_scope?: "WEB_ONLY" | "DOCUMENTS_ONLY" | "DOCUMENTS_THEN_WEB" | "COMBINED";
  /** Immediately preceding user query, used to resolve contextual follow-ups. */
  previous_query?: string;
  jurisdiction?: string;
  mode?: string;
  clarification_cycle?: number;
  /** The query_id of the clarification this message answers; previous_query
   * then carries the request being clarified (lib/clarification-reply.ts). */
  reply_to?: string;
  /** Correlates requests in the same chat; never grants access. */
  conversation_id?: string;
  conversation_history?: { role: "user" | "assistant"; content: string }[];
  /** Documents attached to this turn. Ids of successfully indexed uploads
   * only; the backend re-verifies ownership and readiness, so sending an id
   * the caller does not own simply retrieves nothing. */
  document_ids?: string[];
  task_context?: TaskContextSelection;
};

export type TaskType =
  | "general_question"
  | "policy_research"
  | "document_evidence_extraction"
  | "reconciliation";

export type Engagement = {
  id: string;
  name: string;
  status: string;
  rights_version: string;
};

export async function listEngagements(token: string): Promise<Engagement[]> {
  const res = await authedFetch("/engagements", token);
  return res.json();
}

export type TaskContextSelection = {
  /** Omit for automatic capability-based detection. */
  task_type?: TaskType;
  engagement_id?: string | null;
  purpose?: string | null;
  jurisdiction?: string | null;
  framework?: string | null;
  entity?: string | null;
  period_start?: string | null;
  period_end?: string | null;
  currency?: string | null;
  language?: string;
  intended_use?: "research" | "draft_workpaper" | "internal_review";
};

export type TaskContext = {
  schema_version: "1.0";
  task_type: TaskType;
  task_spec_version: string;
  actor_id: string;
  tenant_id: string;
  actor_role: string;
  engagement_id: string | null;
  purpose: string;
  jurisdiction: string | null;
  framework: string | null;
  entity: string | null;
  period_start: string | null;
  period_end: string | null;
  currency: string | null;
  language: string;
  data_classification: "PUBLIC" | "INTERNAL" | "CONFIDENTIAL" | "RESTRICTED";
  intended_use: "research" | "draft_workpaper" | "internal_review";
};

export type ContextDecision = {
  status: "complete" | "clarification_required" | "unsupported" | "unauthorized";
  missing_fields: string[];
  invalid_fields: string[];
  reason_codes: string[];
  clarification_questions: string[];
  resolved_context: TaskContext | null;
};

export type CapabilityStep = {
  capability: "document.retrieve" | "document.extract" | "source.research" |
    "policy.lookup" | "numeric.calculate" | "numeric.compare" |
    "evidence.cite" | "chart.generate" | "response.compose";
  reason: string;
};

export type WorkflowPlan = {
  version: "1.0";
  task_type: TaskType;
  detection: "automatic" | "explicit_override";
  confidence: number;
  reason_codes: string[];
  steps: CapabilityStep[];
};

// ---- Top-level response ----

export type OutcomeType =
  | "answered"
  | "unavailable"
  | "refused"
  | "clarification_required"
  /** A context statement or correction noted for the conversation; nothing was asked. */
  | "acknowledged"
  | "escalated"
  | "limited_response"
  | "rejected";

export type RouteType =
  | "LLM"
  | "CALCULATION"
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

/** Â§12 SafetyState — frontend renders from this, not by parsing answer text */
export type RiskLevel = "ZERO" | "LOW" | "MEDIUM" | "HIGH" | "RESTRICTED";

export type SafetyState = {
  risk_level: RiskLevel;
  policy_state: "allowed" | "blocked" | "needs_more_context";
  disclaimer_required: boolean;
  refusal_text?: string;
};

export type NextAction = {
  type: string;  // ask_clarifying_question | escalate | refusal | security_incident | composition_failed
  message: string;
  suggestions?: string[];
};

/** Â§12 — opaque audit reference; never exposes internal hashes */
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

/** Â§7.2 SourceBundle — six confidence states */
export type SourceBundle = {
  source_bundle_id: string;
  retrieval_method: string;             // "keyword_mvp" (not RAG until Â§7 criteria met)
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
  /** External URL, internal doc link, or null. */
  url: string | null;
  /** Exact supporting excerpt — not yet returned by the backend. */
  evidence_preview?: string;
  /** Which connector produced this source (e.g. "finnhub", "companies_house").
   * Absent for plain web-search hits, which have no named provider. */
  provider?: string | null;
  /** ISO timestamp of when the backend fetched it. */
  fetched_at?: string | null;
  /** How current the figure is. The distinction between a live tick, a delayed
   * quote and yesterday's close changes what an answer may claim, so it is
   * shown rather than left for the reader to assume. */
  freshness?: "realtime" | "delayed" | "historical" | "filing" | null;
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

export type NumericInput = {
  name: string;
  value: string;
  unit: string;
  currency?: string | null;
  period?: string | null;
  evidence_id?: string | null;
};

export type CalculationResult = {
  calculation_id: string;
  operation: "arithmetic" | "sum" | "difference" | "percentage" | "percentage_change" | "variance" | "straight_line_depreciation" | "loan_emi";
  rule_version: string;
  inputs: NumericInput[];
  output_value: string;
  output_unit: string;
  rounding_mode: "ROUND_HALF_UP";
  scale: number;
};

export type VerifiedChartSpec = {
  chart_id: string;
  type: "bar" | "line" | "kpi";
  title: string;
  categories: string[];
  series: Array<{ name: string; values: string[]; unit: string; source_ids: string[] }>;
  calculation_id: string;
  verified: true;
};

export type LiveObservation = {
  observation_id: string;
  indicator: string;
  value: string;
  unit: string;
  period: string;
  provider: string;
  source_url: string;
  freshness: string;
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
  // metadata layered on across v3â€“v10; never required for rendering.
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

/** Arithmetic, sources and assumptions are verified separately: correct arithmetic is not proof of the rules
 * or of the transaction's assumptions. Absent on answers stored before it. */
export type VerificationBreakdown = {
  arithmetic: "verified" | "mismatch" | "not_applicable";
  sources: "verified" | "partial" | "unsupported" | "not_applicable";
  assumptions: "confirmed" | "stated" | "not_applicable";
  /** Accounting-treatment claims (entries, recognition, standards): "cited_checks_passed" is a citation and
   * evidence-check status, never "treatment verified"; "not_verified" means insufficient evidence, not wrong.
   * Absent on older answers. */
  treatment?: "cited_checks_passed" | "not_verified" | "issue_found" | "not_applicable";
  overall: "fully_verified" | "partially_verified" | "not_verified";
  calculation_id?: string | null;
};

export type ComposedAnswer = {
  text: string;
  citations: SourceCitation[];
  limitations: string[];
  calculation_widget?: CalculationWidget | null;
  calculation_result?: CalculationResult | null;
  verified_charts?: VerifiedChartSpec[];
  observations?: LiveObservation[];
  /** No citations, but the figures are the question's or conversation's own, computed or charted exactly. */
  computed_from_question?: boolean;
  response_kind?: "calculation" | "chart" | "chart_explanation" | null;
  /** Set by the backend and recorded in the audit trail; absent on older cached answers. */
  completeness?: "complete" | "partial" | "none" | null;
  /** What was verified, part by part; recorded in the audit trail with the same calculation_id. */
  verification?: VerificationBreakdown | null;
  presentation?: AnswerPresentation | null;
  response_mode?: "concise" | "educational" | "analytical" | "calculation" | "workflow" | "compound";
  /** Preferred, ordered rendering path — not yet returned by the backend. */
  blocks?: ResponseBlock[];
  /** @deprecated use text — retained for backward compatibility */
  output_text?: string;
};

/**
 * Deterministic, evidence-backed visualization decided server-side by
 * orchestration/visualization/orchestrator.py — never LLM-authored, never
 * executable code. Only ever set on "answered" outcomes. See that module's
 * docstring for current scope: LINE/BAR/KPI (statistical), EVIDENCE_GRAPH
 * (renderer=GRAPH_ADAPTER, resolves to Cytoscape or G6), PROCESS_FLOW
 * (renderer=FLOW_ADAPTER, resolves to X6 or Mermaid). Graph/flow specs are only ever
 * populated from entities/relationships the USER explicitly supplied in
 * their own query text (see backend/app/orchestration/extraction.py) —
 * never fabricated.
 */
export type VisualizationEncodingField = {
  field: string;
  type: "temporal" | "quantitative" | "nominal" | "ordinal";
  unit?: string | null;
};

export type VisualizationDataPoint = { x: string; y: number };

export type VisualizationGraphNode = { id: string; label: string; type: string };
export type VisualizationGraphEdge = { source: string; target: string; type: string; directed: boolean };
export type VisualizationHeatmapCell = { x: string; y: string; value: number };
export type VisualizationBoxSummary = {
  label: string;
  minimum: number;
  q1: number;
  median: number;
  q3: number;
  maximum: number;
  outliers: number[];
};
export type VisualizationScatterPoint = { label: string; x: number; y: number };
/** DONUT only — value is always a band midpoint (e.g. Companies House PSC
 * "25-50%" ownership), never an exact filed percentage; is_estimated flags
 * that per slice rather than spec-wide, so a future exact-percentage source
 * could mix in real slices without every slice appearing falsely precise. */
export type VisualizationDonutSlice = { label: string; value: number; is_estimated: boolean };
/** CANDLESTICK only — one real trading-period bar, never synthesized. */
export type VisualizationOHLCBar = {
  dimension: string; open: number; high: number; low: number; close: number; volume: number | null;
};
/** GROUPED_BAR only — one labeled series; `variant === "STACKED_BAR_CHART"`
 * flips the frontend to stacked rendering of the SAME series data. */
export type VisualizationNamedSeries = { name: string; data: VisualizationDataPoint[] };

export type VisualizationSpec = {
  user_requested_type?: string | null;
  version: string;
  id: string;
  type:
    | "LINE" | "BAR" | "HISTOGRAM" | "BOX" | "SCATTER" | "KPI" | "EVIDENCE_GRAPH" | "HEATMAP"
    | "PROCESS_FLOW" | "TABLE" | "DONUT" | "CANDLESTICK" | "GROUPED_BAR" | "GAUGE";
  family: string;
  capability_id?: string | null;
  canonical?: string | null;
  variant?: string | null;
  /** Same-family fallback types the backend would degrade to if this one
   * failed — real, backend-declared alternatives for the "View" menu. */
  fallback_order: string[];
  domain_context?: {
    domain: string;
    subdomain: string;
    intent?: string | null;
  };
  renderer: "RECHARTS" | "ECHARTS" | "KPI_TILE" | "GRAPH_ADAPTER" | "FLOW_ADAPTER" | "TABLE_ADAPTER";
  title?: string | null;
  summary?: string | null;
  unit?: string | null;
  encoding?: { x: VisualizationEncodingField; y: VisualizationEncodingField } | null;
  data: VisualizationDataPoint[];
  value?: number | null;
  label?: string | null;
  /** GAUGE only — the target `value` is measured against, and its label.
   * Both are stated in the question; the dial never invents a benchmark. */
  target?: number | null;
  target_label?: string | null;
  nodes: VisualizationGraphNode[];
  edges: VisualizationGraphEdge[];
  /** PROCESS_FLOW only — true routes to X6, false to Mermaid. Meaningless for other types. */
  interactive: boolean;
  /** Optional explicit graph/flow engine requested by the user. */
  graph_engine?: "auto" | "cytoscape" | "g6" | null;
  flow_engine?: "mermaid" | "x6" | null;
  cells: VisualizationHeatmapCell[];
  /** BOX only — real min/Q1/median/Q3/max computed from the same values HISTOGRAM bins. */
  box?: VisualizationBoxSummary | null;
  /** SCATTER only — real paired values from two independently-fetched, period-aligned series. */
  scatter: VisualizationScatterPoint[];
  correlation_coefficient?: number | null;
  /** DONUT only — real, named holders and their percent share. */
  donut: VisualizationDonutSlice[];
  /** CANDLESTICK only — real OHLC trading bars. */
  candlestick: VisualizationOHLCBar[];
  /** GROUPED_BAR only — real, period-aligned series (reinterprets the same
   * pair SCATTER uses when explicitly requested as a bar chart). */
  series: VisualizationNamedSeries[];
  /** TABLE only — real rows, column order given by `columns`. */
  columns: string[];
  rows: Record<string, string>[];
  sources: string[];
};

export type GeneratedArtifact = {
  id: string;
  filename: string;
  mime_type: string;
  download_url: string;
  expires_at?: string | null;
};

/** Deterministic accounting-formula result — the self-contained calculation
 * engine's own record, returned alongside the composed answer rather than
 * inside it. Distinct from `CalculationResult` above, which is the verified
 * single-operation record carried on `ComposedAnswer.calculation_result`. */
export type FormulaCalculationResult = {
  matched: boolean;
  status: "success" | "undefined" | "clarification_required" | "not_matched";
  formula_ids: string[];
  formula_version: string;
  inputs: Array<{
    name: string;
    value: string;
    display_value: string;
    kind: "money" | "percentage" | "number" | "years" | "units";
    currency?: string | null;
    source_type: "user";
    source_location: string;
  }>;
  outputs: Array<{
    name: string;
    value?: string | null;
    display_value?: string | null;
    kind: "money" | "percentage" | "ratio" | "number" | "units";
  }>;
  steps: string[];
  verification_status: "passed" | "not_run";
  error_code?: string | null;
  message: string;
};

/** Â§12 Canonical response contract — frontend renders from route/outcome ONLY */
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
  artifacts: GeneratedArtifact[];
  artifact_error?: string | null;
  effective_context?: TaskContext | null;
  context_decision?: ContextDecision | null;
  workflow_plan?: WorkflowPlan | null;
  /** Opaque — never expose audit_chain_id internals to UI rendering logic */
  audit_reference: AuditReference;
  visualization?: VisualizationSpec | null;
  /** Complementary visuals (spec Â§17) — a different lens on the SAME
   * evidence as `visualization` (e.g. current-value KPI beside a trend
   * line), never a redundant alternate chart type. */
  secondary_visualizations?: VisualizationSpec[];
  calculation?: FormulaCalculationResult | null;
  /** A chart Kriton suggests for this answer's figures; drawn only if the
   * user accepts (sends `question`). Absent when nothing is worth charting. */
  chart_offer?: ChartOffer | null;
};

export type ChartOffer = {
  chart_type: "line" | "bar" | "pie";
  title: string;
  question: string;
  reason: string;
  /** The chart itself, built from the answer's table: shown under the
   *  answer on request, with no new question. */
  chart?: VisualizationSpec | null;
};

export async function downloadKritonArtifact(token: string, artifact: GeneratedArtifact): Promise<void> {
  const res = await authedFetch(artifact.download_url, token);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = artifact.filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

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
    if (error instanceof Error && error.name === "AbortError") {
      throw new ApiError(408, "Kriton did not finish within two minutes. Please try again.");
    }
    if (error instanceof TypeError) {
      throw new ApiError(0, "Could not connect to Kriton. Please check that the backend is running and try again.");
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

export type KritonProgress = { stage: string; message: string };

export async function askKritonStream(
  token: string,
  payload: AskKritonRequest,
  idempotencyKey: string | undefined,
  onProgress: (progress: KritonProgress) => void,
): Promise<AskKritonResponse> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/x-ndjson",
  };
  if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;

  const controller = new AbortController();
  // The backend owns the processing deadline. This longer timer only protects
  // against a connection that stops delivering even heartbeats, so it restarts
  // whenever data arrives — as a fixed two-minute cap it cut off answers that
  // were still streaming progress (the first question after a backend restart).
  let timeout = window.setTimeout(() => controller.abort(), 120_000);
  const stillAlive = () => {
    window.clearTimeout(timeout);
    timeout = window.setTimeout(() => controller.abort(), 120_000);
  };
  try {
    const res = await authedFetch("/orchestration/ask/stream", token, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    if (!res.body) throw new ApiError(502, "Kriton returned an empty response stream.");

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      stillAlive();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line) as
          | { type: "progress"; stage: string; message: string }
          | { type: "heartbeat" }
          | { type: "result"; data: AskKritonResponse }
          | { type: "error"; status: number; message: string };
        if (event.type === "progress") onProgress(event);
        if (event.type === "result") return event.data;
        if (event.type === "error") throw new ApiError(event.status, event.message);
      }
      if (done) break;
    }
    throw new ApiError(502, "Kriton's response stream ended before completion.");
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw new ApiError(408, "Kriton's response connection timed out. Please try again.");
    }
    if (error instanceof TypeError) {
      throw new ApiError(0, "Could not connect to Kriton. Please check that the backend is running and try again.");
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

export type AttachmentUploadResult = { document_id: string; filename: string; chunk_count: number; status: string };
export type WorkspaceDocument = {
  id: string;
  filename: string;
  mime_type: string;
  status: string;
  processing_error: string | null;
  chunk_count: number;
  created_at: string;
  expires_at?: string | null;
};

/** XHR (not fetch) because upload progress events need `xhr.upload.onprogress`. */
export function uploadKritonAttachment(
  token: string,
  file: File,
  onProgress?: (fraction: number) => void,
  engagementId?: string,
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
    if (engagementId) form.append("engagement_id", engagementId);
    xhr.send(form);
  });
}

export async function listKritonAttachments(token: string, engagementId?: string): Promise<WorkspaceDocument[]> {
  const query = engagementId ? `?engagement_id=${encodeURIComponent(engagementId)}` : "";
  const res = await authedFetch(`/kriton-workspace/attachments${query}`, token);
  return res.json();
}

export async function getKritonAttachment(token: string, documentId: string): Promise<WorkspaceDocument> {
  const res = await authedFetch(`/kriton-workspace/attachments/${encodeURIComponent(documentId)}`, token);
  return res.json();
}

export async function deleteKritonAttachment(token: string, documentId: string, engagementId?: string): Promise<void> {
  const query = engagementId ? `?engagement_id=${encodeURIComponent(engagementId)}` : "";
  await authedFetch(`/kriton-workspace/attachments/${encodeURIComponent(documentId)}${query}`, token, {
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

// ── Review loop: answer feedback and the review queue ───────────────────────

export type FeedbackReason =
  | "wrong_answer" | "wrong_calculation" | "wrong_source" | "outdated" | "wrong_jurisdiction"
  | "missing_evidence" | "missing_citation" | "poor_explanation" | "other";

export type AnswerFeedbackRequest = {
  query_id: string;
  rating: "up" | "down";
  reasons: FeedbackReason[];
  comment: string;
  question: string;
  answer_text: string;
};

export async function submitAnswerFeedback(
  token: string,
  payload: AnswerFeedbackRequest,
): Promise<{
  id: string;
  rating: string;
  review_case_id: string | null;
  learned?: boolean;
  self_correction_started?: boolean;
}> {
  const res = await authedFetch("/orchestration/feedback", token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

export type ReviewCase = {
  id: string;
  query_id: string;
  question: string;
  draft_answer: string;
  reason: string;
  risk_level: string;
  source: "escalation" | "user_feedback" | string;
  status: "open" | "needs_evidence" | "resolved" | string;
  created_at: string;
  reviewer_decision: "approved" | "corrected" | "rejected" | "needs_evidence" | null;
  review_note: string;
  resolved_at: string | null;
};

export async function listReviewCases(
  token: string,
  status: "open" | "needs_evidence" | "resolved" | "released" | "all" = "open",
): Promise<{ cases: ReviewCase[]; counts: Record<string, number> }> {
  const res = await authedFetch(`/orchestration/review-cases?status_filter=${status}`, token);
  return res.json();
}

/** received → triaged (ZL-ENG-AGT-01 §08.3). */
export async function triageReviewCase(token: string, caseId: string, note = ""): Promise<ReviewCase> {
  const res = await authedFetch(`/orchestration/review-cases/${caseId}/triage`, token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note }),
  });
  return res.json();
}

/** Re-test an approved answer and release it for reuse. Must be done by a
 * different reviewer from the one who approved it. */
export async function releaseReviewedAnswer(token: string, caseId: string): Promise<{ case: ReviewCase; gold_case_id: string | null }> {
  const res = await authedFetch(`/orchestration/review-cases/${caseId}/release`, token, { method: "POST" });
  return res.json();
}

export async function resolveReviewCase(
  token: string,
  caseId: string,
  payload: {
    decision: "approved" | "corrected" | "rejected" | "needs_evidence";
    note: string;
    corrected_answer: string;
    key_facts: string[];
    category?: string;
  },
): Promise<{ case: ReviewCase; gold_case_id: string | null }> {
  const res = await authedFetch(`/orchestration/review-cases/${caseId}/resolve`, token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}


export type ReviewEvidence = {
  bundle_id: string; passage_id: string; source_version_id: string;
  title: string; locator: string; url: string | null;
  effective_from: string | null; effective_to: string | null;
  content: string | null; withheld_reason: string | null;
};

export async function getReviewEvidence(token: string, caseId: string): Promise<ReviewEvidence[]> {
  const res = await authedFetch(`/orchestration/review-cases/${encodeURIComponent(caseId)}/evidence`, token);
  return res.json();
}

export type SourceBundleRecord = { id: string; created_at: string; confidence_state: string; jurisdiction: string; sources: { id: string; title: string }[]; };
export async function listSourceBundles(token: string, signal?: AbortSignal): Promise<SourceBundleRecord[]> {
  const res = await authedFetch("/sources/bundles", token, { signal });
  return res.json();
}

// ─── Notifications & settings ───────────────────────────────────────────────

export type NotificationSeverity = "info" | "warn" | "bad";

export type AppNotification = {
  id: string;
  kind: string;
  severity: NotificationSeverity;
  title: string;
  body: string;
  link: string;
  created_at: string | null;
  read: boolean;
};

export type ActionItem = { key: string; count: number; label: string; link: string; severity: NotificationSeverity };

export type NotificationSummary = { unread: number; action_items: ActionItem[] };

export type MySettings = {
  default_jurisdiction: string;
  muted_notifications: string[];
  notification_kinds: { kind: string; label: string }[];
  jurisdictions: string[];
};

export async function getNotificationSummary(token: string, signal?: AbortSignal): Promise<NotificationSummary> {
  return (await authedFetch("/notifications/summary", token, { signal })).json();
}

export async function listNotifications(
  token: string,
  options: { unreadOnly?: boolean; kind?: string; before?: string; limit?: number } = {},
  signal?: AbortSignal,
): Promise<AppNotification[]> {
  const query = new URLSearchParams();
  if (options.unreadOnly) query.set("unread_only", "true");
  if (options.kind) query.set("kind", options.kind);
  if (options.before) query.set("before", options.before);
  query.set("limit", String(options.limit ?? 30));
  return (await authedFetch(`/notifications?${query}`, token, { signal })).json();
}

export async function markNotificationRead(token: string, id: string): Promise<void> {
  await authedFetch(`/notifications/${encodeURIComponent(id)}/read`, token, { method: "POST" });
}

export async function markAllNotificationsRead(token: string): Promise<void> {
  await authedFetch("/notifications/read-all", token, { method: "POST" });
}

export async function getMySettings(token: string, signal?: AbortSignal): Promise<MySettings> {
  return (await authedFetch("/me/settings", token, { signal })).json();
}

export async function updateMySettings(
  token: string,
  changes: Partial<Pick<MySettings, "default_jurisdiction" | "muted_notifications">>,
): Promise<MySettings> {
  const res = await authedFetch("/me/settings", token, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(changes),
  });
  return res.json();
}

export async function updateMyProfile(token: string, changes: { first_name?: string; last_name?: string }): Promise<UserPublic> {
  const res = await authedFetch("/auth/me", token, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(changes),
  });
  return res.json();
}

/** Admin only. The creator becomes a member with every operation, so the
 * new engagement shows up straight away (e.g. as a Kriton project). */

// ── Platform control plane (backend app/domains/platform) ────────────────────

export type PlatformControlState = "pass" | "review" | "fail" | "unknown" | "pending";
export type PlatformDecision = {
  id: string; ref: string; priority: "Critical" | "High" | "Medium"; title: string; area: string;
  owner: string; tenant: string; since: string | null; state: string;
};
export type PlatformCommand = {
  generatedAt: string;
  summary: {
    criticalIncidents: number; openIncidents: number; unassignedIncidents: number;
    releaseHolds: number; openReleases: number; decisions: number; decisionsByPriority: Record<string, number>;
    isolation: PlatformControlState; availabilityPct: number | null; objectivePct: number;
    privilegedRequests: number; privilegedAwaitingApproval: number; controlExceptions: number;
  };
  decisions: PlatformDecision[];
  controls: { key: string; label: string; state: PlatformControlState; detail: string }[];
  health: {
    services: { key: string; name: string; state: string; core: boolean; latencyMs: number | null; checkedAt: string | null }[];
    sampled: boolean; availabilityPct: number | null; objectivePct: number; p95LatencyMs: number | null;
    degraded: number; measured: number; coreDown: string[];
  };
  evaluation: {
    state: PlatformControlState; latest: { id: string; status: string; at: string | null } | null;
    metrics: { name: string; value: number }[]; recent: { completed: number; failed: number };
  };
  releases: { open: number; held: number; items: { ref: string; name: string; version: string; held: boolean; tenant: string }[] };
  tenants: { total: number; withUsers: number; active30d: number; users: number; withApprovedPlan: number };
  commercial: {
    month: string; invoiced: Record<string, number>; collected: Record<string, number>; receivable: Record<string, number>;
    unpaidStatements: number; openDisputes: number; pendingCredits: number;
  };
  privileged: {
    awaitingApproval: number; active: number; awaitingReview: number;
    activeGrants: { ref: string; tenant: string; expiresAt: string | null }[];
  };
  audit: { events24h: number; exportsPending: number; deniedAttempts30d: number };
};

export async function getPlatformCommand(token: string, signal?: AbortSignal): Promise<PlatformCommand> {
  return (await authedFetch("/platform/command", token, { signal }, { asSelf: true })).json();
}

export type PlatformAccountStatus =
  "active" | "never_signed_in" | "unconfirmed" | "no_login" | "suspended" | "deactivated";
export type PlatformAccount = {
  id: string; name: string; email: string; role: string; platformRole: string | null;
  tenantId: string; tenant: string; status: PlatformAccountStatus; createdAt: string | null;
  emailConfirmed: boolean | null; lastSignInAt: string | null; lastSeenAt: string | null; lastActivityAt: string | null;
  online: boolean; activeSessions: number; mfa: boolean | null; providers: string[];
};
export type PlatformCompany = {
  id: string; name: string; type: "company" | "personal"; state: "online" | "active" | "dormant" | "empty";
  createdAt: string | null; members: number; activeMembers: number; online: number; signedIn24h: number; signedIn7d: number;
  roles: Record<string, number>; admins: { name: string; email: string }[];
  lastSignInAt: string | null; lastActivityAt: string | null; billingPlan: boolean; issues: number;
};
export type PlatformDirectory = {
  generatedAt: string;
  signInDataAvailable: boolean;
  summary: {
    companies: number; personalWorkspaces: number; companiesOnline: number; companiesSignedIn24h: number;
    companiesActive30d: number; accounts: number; online: number; signedIn24h: number; signedIn7d: number;
    statuses: Partial<Record<PlatformAccountStatus, number>>; roles: Record<string, number>; withMfa: number;
  };
  companies: PlatformCompany[];
  accounts: PlatformAccount[];
};

export async function getPlatformDirectory(token: string, signal?: AbortSignal): Promise<PlatformDirectory> {
  return (await authedFetch("/platform/directory", token, { signal }, { asSelf: true })).json();
}
