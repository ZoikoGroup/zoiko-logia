import { getAuthToken } from "@/lib/api";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010/api/v1";
const BACKEND = `${API_URL}/support/incidents`;

export type IncidentTimelineEntry = {
  timestamp: string;
  actor: string;
  action: string;
  note: string;
};

export type SecurityIncident = {
  id: string;
  tenant_id: string;
  title: string;
  severity: "Critical" | "High" | "Medium" | "Low";
  containment_status: "OPEN" | "CONTAINED" | "RESOLVED";
  source: string;
  query_id: string | null;
  restricted_sub_class: string | null;
  assigned_to: string | null;
  timeline: IncidentTimelineEntry[];
  opened_at: string;
  resolved_at: string | null;
  resolution_note: string | null;
};

export type IncidentStats = {
  total: number;
  open: number;
  contained: number;
  resolved: number;
  critical: number;
  high: number;
};

/** A failed request, with the HTTP status (0 when the server was unreachable). */
export class IncidentApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

// Errors are thrown, not swallowed: returning an empty list on failure made a
// 403 or a server outage look like "No incidents found", and a failed action
// look like it had worked.
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BACKEND}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${getAuthToken()}`,
        ...options?.headers,
      },
    });
  } catch {
    throw new IncidentApiError(0, "The server could not be reached.");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new IncidentApiError(res.status, body?.detail ?? `Request failed (${res.status})`);
  }
  return (await res.json()) as T;
}

export async function getIncidents(status?: string): Promise<SecurityIncident[]> {
  return request<SecurityIncident[]>(status ? `?status=${encodeURIComponent(status)}` : "");
}

export async function getIncidentStats(): Promise<IncidentStats> {
  return request<IncidentStats>("/stats");
}

// The backend records the signed-in user as the actor, so none is sent.
export async function updateIncident(incidentId: string, action: string, note: string): Promise<SecurityIncident> {
  return request<SecurityIncident>(`/${incidentId}/action`, {
    method: "POST",
    body: JSON.stringify({ action, note }),
  });
}

export async function closeIncident(incidentId: string, resolutionNote: string): Promise<SecurityIncident> {
  return request<SecurityIncident>(`/${incidentId}/close`, {
    method: "POST",
    body: JSON.stringify({ resolution_note: resolutionNote }),
  });
}
