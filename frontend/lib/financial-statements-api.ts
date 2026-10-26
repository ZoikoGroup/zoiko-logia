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

// Reporting Rules Resolution (Document 03).
export type YearFiguresIn = { turnover?: string; balance_sheet_total?: string; employees?: number | "" };
export type EntityFactsIn = {
  entity_name: string; incorporation_jurisdiction: string; legal_form: string; scope: "individual" | "group";
  report_type: "annual" | "interim" | "management" | "educational"; period_start: string; period_end: string;
  flags: string[]; current_year: YearFiguresIn; prior_year: YearFiguresIn; prior_year_size?: string;
  framework_election: string; election_signed_by?: string; early_adoption: string[];
  requested_claim: "illustrative" | "statutory_ready"; group_perimeter?: string[]; parent_framework?: string;
  prior_framework?: string; first_time_adoption?: boolean; policy_questions?: string[];
  requested_statements?: string[]; evidence?: Record<string, string>;
};
export type Criterion = { criterion: string; value: string | null; limit: string; within: boolean | null };
export type ResolutionResult = {
  state: string; selected_framework: string | null; framework_edition: string | null; size_class: string;
  eligibility: { result?: string; reason?: string; band?: string; exclusions?: string[]; rule?: string;
    tests?: { size: string; current: boolean | null; prior: boolean | null; current_criteria: Criterion[]; prior_criteria: Criterion[] }[] };
  candidates: { framework: string; status: string; reason: string; sources: string[] }[];
  rules: { rule_id: string; outcome: string; effective: string; source: string; adoption: string; endorsement: string }[];
  statements: { statement: string; requirement: string; note: string }[];
  blockers: string[]; reasons: Record<string, string>;
  findings: { code: string; severity: string; owner: string; reason: string; action: string }[];
  pending_judgments: { key: string; question: string; sources: string[]; decided: boolean }[];
  judgments: Record<string, { choice: string; reason: string; by: string; at: string }>;
  gates: { gate: string; title: string; passed: boolean; detail: string }[];
  outputs: { type: string; allowed: boolean; gate: string }[]; explanation: string[];
  citations: Record<string, { publisher: string; title: string; url: string; checked: string; snapshot: string | null }>;
  permit_illustrative_draft: boolean; permit_statutory_claim: boolean; permitted_exports: string[]; as_of: string;
  rule_pack: { id: string; version: string; status: string; checked: string; valid_until: string; owner: string;
    digest: string; capabilities: Record<string, string> };
};
export type StoredResolution = {
  id: string; revision: number; state: string; entity_key: string; facts: EntityFactsIn; facts_hash: string;
  rule_pack_digest: string; result: ResolutionResult; judgments: ResolutionResult["judgments"];
  history: { action: string; actor_id: string; at: string; state: string; detail: Record<string, unknown> }[];
  pack_is_current: boolean; approval_valid: boolean; trial_balance_id: string | null; prepared_by: string;
  approved_by: string | null; approved_at: string | null; created_at: string | null;
};
export type ReleaseCheck = {
  resolution_id: string; revision: number; statutory_release_allowed: boolean; illustrative_allowed: boolean;
  reasons: string[]; rule_pack_digest: string; framework_edition: string | null;
};

export const previewResolution = (facts: EntityFactsIn) =>
  request<ResolutionResult>("/resolve", { method: "POST", body: JSON.stringify({ facts }) });
export const saveResolution = (facts: EntityFactsIn, trialBalanceId?: string) =>
  request<StoredResolution>("/resolutions", { method: "POST", body: JSON.stringify({ facts, trial_balance_id: trialBalanceId ?? null }) });
export const listResolutions = () => request<StoredResolution[]>("/resolutions");
export const approveResolution = (id: string) =>
  request<StoredResolution>(`/resolutions/${encodeURIComponent(id)}/approve`, { method: "POST" });
export const requestReview = (id: string, note = "") =>
  request<StoredResolution>(`/resolutions/${encodeURIComponent(id)}/request-review`, { method: "POST", body: JSON.stringify({ note }) });
export const recordJudgment = (id: string, body: { key: string; choice: string; reason: string }) =>
  request<StoredResolution>(`/resolutions/${encodeURIComponent(id)}/judgments`, { method: "POST", body: JSON.stringify(body) });
export const rejectResolution = (id: string, reason: string) =>
  request<StoredResolution>(`/resolutions/${encodeURIComponent(id)}/reject`, { method: "POST", body: JSON.stringify({ reason }) });
export const revokeResolution = (id: string, reason: string) =>
  request<StoredResolution>(`/resolutions/${encodeURIComponent(id)}/revoke`, { method: "POST", body: JSON.stringify({ reason }) });
export const releaseCheck = (id: string) => request<ReleaseCheck>(`/resolutions/${encodeURIComponent(id)}/release-check`);

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
