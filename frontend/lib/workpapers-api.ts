import { getAuthToken } from "@/lib/api";
import { impersonationHeaders } from "@/lib/impersonation";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8010/api/v1";
const WORKPAPERS = `${API_URL}/kriton-workspace/workpapers`;

// Shapes of /api/v1/kriton-workspace/workpapers (backend/app/domains/kriton_workspace/workpapers.py).
export type WorkpaperStatus = "open" | "in_review" | "signed_off";
export type WorkpaperItemKind = "saved_answer" | "draft" | "document";
export type WorkpaperItem = { id: string; kind: WorkpaperItemKind; itemId: string; title: string; note: string; missing: boolean; addedAt: string | null };
export type Workpaper = {
  id: string; title: string; period: string; status: WorkpaperStatus;
  engagementId: string | null; engagementName: string | null;
  ownerId: string; ownerName: string | null; reviewerId: string | null; reviewerName: string | null;
  signedOffBy: string | null; signedOffAt: string | null; itemCount: number;
  createdAt: string | null; updatedAt: string | null; canEdit: boolean; canReview: boolean;
  notes?: string; reviewNote?: string; items?: WorkpaperItem[];
};
export type Reviewer = { id: string; name: string; role: string };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${WORKPAPERS}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${getAuthToken()}`, ...init?.headers, ...impersonationHeaders() },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${res.status})`);
  }
  return res.json();
}

const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });

export const listWorkpapers = () => request<Workpaper[]>("");
export const listReviewers = () => request<Reviewer[]>("/reviewers");
export const getWorkpaper = (id: string) => request<Workpaper>(`/${id}`);
export const createWorkpaper = (body: { title: string; period: string; engagement_id: string | null; reviewer_id: string | null }) =>
  request<Workpaper>("", json("POST", body));
export const updateWorkpaper = (id: string, body: Partial<{ title: string; period: string; notes: string; reviewer_id: string | null }>) =>
  request<Workpaper>(`/${id}`, json("PATCH", body));
export const submitWorkpaper = (id: string) => request<Workpaper>(`/${id}/submit`, { method: "POST" });
export const reviewWorkpaper = (id: string, decision: "sign_off" | "return", note: string) =>
  request<Workpaper>(`/${id}/review`, json("POST", { decision, note }));
export const addWorkpaperItem = (id: string, kind: WorkpaperItemKind, itemId: string) =>
  request<Workpaper>(`/${id}/items`, json("POST", { kind, item_id: itemId }));
export const removeWorkpaperItem = (id: string, rowId: string) => request<Workpaper>(`/${id}/items/${rowId}`, { method: "DELETE" });

/** Download the workpaper's ZIP: its record plus an evidence pack per answer or draft. */
export async function downloadWorkpaperPack(id: string): Promise<void> {
  const res = await fetch(`${WORKPAPERS}/${id}/evidence-pack`, { headers: { Authorization: `Bearer ${getAuthToken()}`, ...impersonationHeaders() } });
  if (!res.ok) throw new Error(`Could not build the workpaper pack (${res.status})`);
  const match = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "");
  const url = URL.createObjectURL(await res.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = match?.[1] ?? "workpaper.zip";
  link.click();
  URL.revokeObjectURL(url);
}
