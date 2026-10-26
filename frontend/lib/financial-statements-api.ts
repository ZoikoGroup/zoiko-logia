import { getAuthToken } from "@/lib/api";
import { impersonationHeaders } from "@/lib/impersonation";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8010/api/v1";
const BASE = `${API_URL}/financial-statements`;

// Trial-balance intake (backend/app/domains/financial_statements, Document 04).
export type Severity = "HARD_STOP" | "REVIEW" | "INFO";
export type Finding = { code: string; severity: Severity; message: string; rule: string; refs: string[] };
export type MappingStatus = "SUGGESTED" | "NEEDS_EVIDENCE" | "UNMAPPED" | "APPROVED" | "REJECTED";
export type Mapping = {
  id: string; account_key: string; account_name: string; balance: string; status: MappingStatus;
  line_id: string | null; line_label: string | null; candidates: { line_id: string; label: string }[];
  evidence_required: string; basis: string; allocations: { line_id: string; amount: string }[];
  reviewer: string | null; evidence_ref: string; source: string; decided_at: string | null;
};
export type Journal = {
  journal_id: string; kind: string; reason: string; correction_type: string; treatment: string;
  requires_restatement: boolean; lines: { line_id: string; debit: string; credit: string }[];
  evidence_refs: string[]; created_by: string; review_status: string; posting_status: string; reviewer: string | null;
};
export type TrialBalanceSummary = {
  id: string; filename: string; sha256: string; version: number; kind: string; state: string;
  uploaded_by: string; created_at: string | null; supersedes_id: string | null; superseded_by: string | null;
  balanced: boolean | null; hard_stops: number;
};
export type TrialBalance = TrialBalanceSummary & {
  units: string; sign_convention: string; period_end: string | null;
  sheets: { sheets?: string[]; hidden_sheets?: string[] };
  integrity: { total_debits?: string; total_credits?: string; difference?: string; balanced?: boolean; basis?: string; note?: string };
  findings: Finding[]; lines: Record<string, unknown>[]; mappings: Mapping[];
  mapping_counts: Record<string, number>; journals: Journal[];
  supporting: { id: string; kind: string; filename: string; sha256: string; total: string | null; basis: string; finding: Finding }[];
  snapshots: { id: string; content_hash: string; status: string; preparer_id: string; approver_id: string; approved_at: string | null }[];
  history: { action: string; actor_id: string; at: string | null; detail: Record<string, unknown> }[];
  status_note: string; effect?: JournalEffect;
};
export type JournalEffect = {
  journal_id: string; lines: { line_id: string; label: string; before: string; after: string }[];
  profit_before_tax_before: string; profit_before_tax_after: string; posting_status: string;
};
export type Catalogue = {
  lines: { line_id: string; label: string; section: string }[];
  correction_types: { code: string; treatment: string }[];
  supporting_kinds: { code: string; line_id: string; label: string }[];
};
export type Lineage = {
  account_key: string; account_name: string; balance: string; source_rows: Record<string, unknown>[];
  source_file: { filename: string; sha256: string; version: number };
  mapping: { status: string; line_id: string | null; basis: string; reviewer_id: string | null; evidence_ref: string };
  journals: Journal[]; snapshot: { id: string; status: string; content_hash: string } | null;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isForm = init?.body instanceof FormData;
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      ...(isForm ? {} : { "Content-Type": "application/json" }),
      Authorization: `Bearer ${getAuthToken()}`,
      ...init?.headers,
      ...impersonationHeaders(),
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${res.status})`);
  }
  return res.json();
}

export const getCatalogue = () => request<Catalogue>("/catalogue");
export const listTrialBalances = () => request<TrialBalanceSummary[]>("/trial-balances");
export const getTrialBalance = (id: string) => request<TrialBalance>(`/trial-balances/${encodeURIComponent(id)}`);
export const getLineage = (id: string, accountKey: string) =>
  request<Lineage>(`/trial-balances/${encodeURIComponent(id)}/lineage/${encodeURIComponent(accountKey)}`);

export function uploadTrialBalance(file: File, supersedesId?: string) {
  const form = new FormData();
  form.append("file", file);
  if (supersedesId) form.append("supersedes_id", supersedesId);
  return request<TrialBalance>("/trial-balances", { method: "POST", body: form });
}

export function addSupporting(id: string, kind: string, file: File) {
  const form = new FormData();
  form.append("kind", kind);
  form.append("file", file);
  return request<TrialBalance>(`/trial-balances/${encodeURIComponent(id)}/supporting`, { method: "POST", body: form });
}

export const decideMapping = (id: string, mappingId: string, body: {
  action: "approve" | "reject"; line_id?: string; evidence_ref?: string; reason?: string;
  allocations?: { line_id: string; amount: string }[];
}) => request<TrialBalance>(`/trial-balances/${encodeURIComponent(id)}/mappings/${encodeURIComponent(mappingId)}/decision`,
  { method: "POST", body: JSON.stringify(body) });

export const proposeJournal = (id: string, body: {
  kind: string; reason: string; correction_type?: string; evidence_refs?: string[];
  lines: { line_id: string; debit: string; credit: string }[];
}) => request<TrialBalance>(`/trial-balances/${encodeURIComponent(id)}/journals`, { method: "POST", body: JSON.stringify(body) });

export const reviewJournal = (id: string, journalId: string, approve: boolean) =>
  request<TrialBalance>(`/trial-balances/${encodeURIComponent(id)}/journals/${encodeURIComponent(journalId)}/review`,
    { method: "POST", body: JSON.stringify({ approve }) });

export const approveSnapshot = (id: string) =>
  request<TrialBalance>(`/trial-balances/${encodeURIComponent(id)}/approve`, { method: "POST" });

export async function downloadOriginal(id: string, filename: string) {
  const res = await fetch(`${BASE}/trial-balances/${encodeURIComponent(id)}/original`, {
    headers: { Authorization: `Bearer ${getAuthToken()}`, ...impersonationHeaders() },
  });
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  const url = URL.createObjectURL(await res.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
