import { getAuthToken } from "@/lib/api";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010/api/v1";

// Shape returned by GET /api/v1/command-center/my-workspace
// (backend/app/domains/command_center/workspace.py).
export type WorkspaceActivity = {
  id: string;
  kind: "saved_answer" | "draft" | "review" | "escalation" | "audit";
  label: string;
  at: string | null;
  href: string;
};

export type WorkspaceTask = {
  id: string;
  kind: "review" | "escalation" | "draft" | "source_approval" | "prompt_approval";
  label: string;
  status: string;
  tone: "bad" | "warn" | "info";
  dueAt: string | null;
  href: string;
};

export type MyWorkspace = { recentActivity: WorkspaceActivity[]; pendingTasks: WorkspaceTask[]; generatedAt: string };

export async function getMyWorkspace(signal?: AbortSignal): Promise<MyWorkspace> {
  const res = await fetch(`${API_URL}/command-center/my-workspace`, {
    headers: { Authorization: `Bearer ${getAuthToken()}` },
    signal,
  });
  if (!res.ok) throw new Error(`My Workspace request failed (${res.status})`);
  return res.json();
}
