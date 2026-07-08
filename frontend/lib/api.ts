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
