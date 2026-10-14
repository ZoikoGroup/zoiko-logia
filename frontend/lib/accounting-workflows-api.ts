import { getAuthToken } from "@/lib/api";
import { impersonationHeaders } from "@/lib/impersonation";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010/api/v1";
const WORKSPACE = `${API_URL}/kriton-workspace`;

function headers(): HeadersInit {
  return { Authorization: `Bearer ${getAuthToken()}`, ...impersonationHeaders() };
}

async function failure(res: Response, fallback: string): Promise<Error> {
  const body = await res.json().catch(() => null);
  return new Error(typeof body?.detail === "string" ? body.detail : `${fallback} (${res.status})`);
}

// ── Evidence Packs (backend/app/domains/kriton_workspace/evidence_pack.py) ──
export type EvidencePackKind = "saved-answer" | "draft";

/** Download the ZIP evidence pack for a saved answer or draft. */
export async function downloadEvidencePack(kind: EvidencePackKind, id: string): Promise<void> {
  const res = await fetch(`${WORKSPACE}/evidence-packs/${kind}/${encodeURIComponent(id)}`, { headers: headers() });
  if (!res.ok) throw await failure(res, "Could not build the evidence pack");
  const match = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "");
  const url = URL.createObjectURL(await res.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = match?.[1] ?? "evidence-pack.zip";
  link.click();
  URL.revokeObjectURL(url);
}

// ── Compliance Calendar (backend/app/domains/kriton_workspace/compliance_calendar.py) ──
export type Deadline = {
  id: string;
  rule: string;
  jurisdiction: string;
  title: string;
  category: string;
  dueDate: string;
  daysLeft: number;
  assumes: string;
  source: string;
  weekendNote: string | null;
};
export type ComplianceCalendar = { from: string; to: string; jurisdictions: string[]; deadlines: Deadline[]; disclaimer: string };

export async function getComplianceCalendar(days: number, jurisdiction: string, signal?: AbortSignal): Promise<ComplianceCalendar> {
  const query = new URLSearchParams({ days: String(days), jurisdiction });
  const res = await fetch(`${WORKSPACE}/compliance-calendar?${query}`, { headers: headers(), signal });
  if (!res.ok) throw await failure(res, "Could not load the compliance calendar");
  return res.json();
}
