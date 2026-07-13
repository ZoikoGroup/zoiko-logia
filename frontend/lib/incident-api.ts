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

async function tryBackend<T>(path: string, options?: RequestInit): Promise<T | null> {
  try {
    const res = await fetch(`${BACKEND}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${getAuthToken()}`,
        ...options?.headers,
      },
    });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

export async function getIncidents(status?: string): Promise<SecurityIncident[]> {
  const url = status ? `/?status=${status}` : "";
  const remote = await tryBackend<SecurityIncident[]>(url);
  return remote ?? [];
}

export async function getIncidentStats(): Promise<IncidentStats | null> {
  return tryBackend<IncidentStats>("/stats");
}

export async function updateIncident(
  incidentId: string,
  action: string,
  actor: string,
  note: string
): Promise<SecurityIncident | null> {
  return tryBackend<SecurityIncident>(`/${incidentId}/action`, {
    method: "POST",
    body: JSON.stringify({ action, actor, note }),
  });
}

export async function closeIncident(
  incidentId: string,
  resolver: string,
  resolutionNote: string
): Promise<SecurityIncident | null> {
  return tryBackend<SecurityIncident>(`/${incidentId}/close`, {
    method: "POST",
    body: JSON.stringify({ resolver, resolution_note: resolutionNote }),
  });
}
