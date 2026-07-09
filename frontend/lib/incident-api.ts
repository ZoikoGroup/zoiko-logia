import { getAuthToken } from "@/lib/api";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
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
  return remote || MOCK_INCIDENTS.filter(i => !status || i.containment_status === status);
}

export async function getIncidentStats(): Promise<IncidentStats | null> {
  const remote = await tryBackend<IncidentStats>("/stats");
  if (remote) return remote;
  
  // Fallback mock stats
  return {
    total: MOCK_INCIDENTS.length,
    open: MOCK_INCIDENTS.filter(i => i.containment_status === "OPEN").length,
    contained: MOCK_INCIDENTS.filter(i => i.containment_status === "CONTAINED").length,
    resolved: MOCK_INCIDENTS.filter(i => i.containment_status === "RESOLVED").length,
    critical: MOCK_INCIDENTS.filter(i => i.severity === "Critical").length,
    high: MOCK_INCIDENTS.filter(i => i.severity === "High").length,
  };
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

// ─── Mocks ───────────────────────────────────────────────────────────────────

const MOCK_INCIDENTS: SecurityIncident[] = [
  {
    id: "inc-mock1",
    tenant_id: "tenant-default",
    title: "Suspicious prompt bypass attempt detected",
    severity: "Critical",
    containment_status: "OPEN",
    source: "RESTRICTED_CONTROL_BYPASS",
    query_id: "q-demo-bypass",
    restricted_sub_class: "RESTRICTED_CONTROL_BYPASS",
    assigned_to: null,
    timeline: [
      {
        timestamp: new Date().toISOString(),
        actor: "system",
        action: "created",
        note: "Incident auto-created due to control bypass attempt"
      }
    ],
    opened_at: new Date(Date.now() - 3600000).toISOString(), // 1 hour ago
    resolved_at: null,
    resolution_note: null,
  }
];
