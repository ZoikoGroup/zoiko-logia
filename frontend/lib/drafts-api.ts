import { getAuthToken } from "@/lib/api";
import { impersonationHeaders } from "@/lib/impersonation";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010/api/v1";
const DRAFTS = `${API_URL}/kriton-workspace/drafts`;

// Drafts & Reports additions (backend/app/domains/kriton_workspace/draft_tools.py).
export type DraftSource = { title: string; url: string };
export type DraftExportFormat = "docx" | "pdf" | "md";

async function request(path: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(`${DRAFTS}${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${getAuthToken()}`, ...init?.headers, ...impersonationHeaders() },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${res.status})`);
  }
  return res;
}

export async function deleteDraft(id: string): Promise<void> {
  await request(`/${id}`, { method: "DELETE" });
}

export async function listDraftSources(id: string): Promise<DraftSource[]> {
  return (await request(`/${id}/sources`)).json();
}

/** Download the draft as a Word, PDF or Markdown file. */
export async function exportDraft(id: string, format: DraftExportFormat): Promise<void> {
  const res = await request(`/${id}/export?format=${format}`);
  const match = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "");
  const url = URL.createObjectURL(await res.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = match?.[1] ?? `draft.${format}`;
  link.click();
  URL.revokeObjectURL(url);
}
