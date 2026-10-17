/**
 * Evaluation Gates & LLM Benchmarking API client.
 *
 * Calls the configured backend (NEXT_PUBLIC_API_URL, same as lib/api.ts).
 */

import { impersonationHeaders } from "@/lib/impersonation";
import { getCurrentAccessToken } from "@/lib/session-token";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8010/api/v1";
const BACKEND = `${API_URL}/evaluation`;

// ─── Types ────────────────────────────────────────────────────────────────────

export type EvaluationDataset = {
  id: string;
  version: string;
  status: string;
  domain: string;
  created_at: string;
  cases: BenchmarkCase[];
};

export type BenchmarkCase = {
  id: string;
  query_text: string;
  gold_answer: string;
  risk_scope: string;
  jurisdiction: string | null;
  source_refs: string[] | null;
  created_at: string;
};

export type ThresholdSet = {
  id: string;
  dataset_id: string;
  dataset_version_id: string;
  metrics: Record<string, number>;
  zero_tolerance_metrics: string[] | null;
  owner: string;
  approver: string;
  created_at: string;
};

export type EvaluationRun = {
  id: string;
  dataset_id: string;
  threshold_set_id: string;
  config_hash: string;
  status: string;
  metrics_summary: Record<string, number> | null;
  created_at: string;
};

export type ResultPack = {
  id: string;
  run_id: string;
  exact_config_hash: string;
  contamination_scan_status: string;
  zero_tolerance_passed: boolean;
  promotion_eligible: boolean;
  created_at: string;
};

export type PromotionAuthorization = {
  id: string;
  result_pack_id: string;
  decision: string;
  approver_id: string;
  residual_risk_accepted: boolean;
  created_at: string;
};

export type EvaluationRunResult = {
  run: EvaluationRun;
  result_pack: ResultPack;
};

export type MetricFailure = {
  metric: string;
  run_value: number | null;
  target: number;
  reason: string;
  severity: string;
};

export type RunChecks = {
  failures: MetricFailure[];
  config_hash_valid: boolean;
  unmeasured_metrics: string[];
  case_count: number;
};

export type DatasetSummary = {
  id: string;
  version: string;
  status: string;
  domain: string;
  created_at: string;
  case_count: number;
};

export type RunHistoryEntry = {
  id: string;
  dataset_id: string;
  threshold_set_id: string;
  config_hash: string;
  matches_current_config: boolean;
  status: string;
  metrics_summary: Record<string, number> | null;
  created_at: string;
  failures: MetricFailure[];
  /** Gated metrics this run could not measure (left out, so they fail as missing). */
  unmeasured_metrics: string[];
  result_pack: {
    id: string;
    contamination_scan_status: string;
    zero_tolerance_passed: boolean;
    promotion_eligible: boolean;
  } | null;
  promotion: {
    decision: string;
    approver_id: string;
    residual_risk_accepted: boolean;
    created_at: string;
  } | null;
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

// Every evaluation route requires a signed-in user with evaluation
// permissions. This client used to send no Authorization header, so every
// call came back 401 and the page reported the backend as unreachable.
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BACKEND}${path}`, {
    ...options,
    headers: {
      ...options?.headers,
      "Content-Type": "application/json",
      ...impersonationHeaders(),
      Authorization: `Bearer ${getCurrentAccessToken()}`,
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : null;
    if (res.status === 401) throw new Error("Your session has expired. Please sign in again.");
    if (res.status === 403) throw new Error(detail ?? "Your role cannot use evaluation gates.");
    throw new Error(detail ?? `Evaluation request failed (${res.status}).`);
  }
  return (await res.json()) as T;
}

// ─── Public API ───────────────────────────────────────────────────────────────

export function listDatasets(): Promise<DatasetSummary[]> {
  return request<DatasetSummary[]>("/datasets");
}

export function listThresholdSets(): Promise<ThresholdSet[]> {
  return request<ThresholdSet[]>("/thresholds");
}

export function listRuns(limit = 20): Promise<RunHistoryEntry[]> {
  return request<RunHistoryEntry[]>(`/runs?limit=${limit}`);
}

export async function getCurrentConfigHash(): Promise<string> {
  return (await request<{ config_hash: string }>("/config-hash")).config_hash;
}

export function runEvaluation(
  datasetId: string,
  thresholdSetId: string,
  configHash: string
): Promise<EvaluationRunResult & RunChecks> {
  return request<EvaluationRunResult & RunChecks>("/run", {
    method: "POST",
    body: JSON.stringify({
      dataset_id: datasetId,
      threshold_set_id: thresholdSetId,
      config_hash: configHash,
    }),
  });
}

/** The approver is the signed-in user; the backend ignores any other name. */
export function promoteRelease(
  resultPackId: string,
  decision: "APPROVED" | "REJECTED",
  residualRiskAccepted: boolean = false
): Promise<PromotionAuthorization> {
  return request<PromotionAuthorization>("/promote", {
    method: "POST",
    body: JSON.stringify({
      result_pack_id: resultPackId,
      decision,
      approver_id: "signed-in-user",
      residual_risk_accepted: residualRiskAccepted,
    }),
  });
}

// ─── Zero-Tolerance Metric Config ────────────────────────────────────────────

export const ZERO_TOLERANCE_METRICS = ["pii_leak", "secrets_leak", "cross_tenant_leak"];
