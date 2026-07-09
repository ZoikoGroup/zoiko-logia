/**
 * Evaluation Gates & LLM Benchmarking API client.
 *
 * Calls the backend at http://localhost:8000/api/v1/evaluation.
 * When the backend is unreachable it falls back to mock data so
 * the dashboard remains functional for demo/development.
 */

const BACKEND = "http://localhost:8000/api/v1/evaluation";

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

// ─── Helpers ─────────────────────────────────────────────────────────────────

async function tryBackend<T>(path: string, options?: RequestInit): Promise<T | null> {
  try {
    const res = await fetch(`${BACKEND}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

// ─── Public API ───────────────────────────────────────────────────────────────

export async function getDataset(datasetId: string): Promise<EvaluationDataset | null> {
  return tryBackend<EvaluationDataset>(`/datasets/${datasetId}`);
}

export async function getThresholdSet(tsId: string): Promise<ThresholdSet | null> {
  return tryBackend<ThresholdSet>(`/thresholds/${tsId}`);
}

export async function runEvaluation(
  datasetId: string,
  thresholdSetId: string,
  configHash: string
): Promise<EvaluationRunResult | null> {
  return tryBackend<EvaluationRunResult>("/run", {
    method: "POST",
    body: JSON.stringify({
      dataset_id: datasetId,
      threshold_set_id: thresholdSetId,
      config_hash: configHash,
    }),
  });
}

export async function promoteRelease(
  resultPackId: string,
  decision: "APPROVED" | "REJECTED",
  approverId: string,
  residualRiskAccepted: boolean = false
): Promise<PromotionAuthorization | null> {
  return tryBackend<PromotionAuthorization>("/promote", {
    method: "POST",
    body: JSON.stringify({
      result_pack_id: resultPackId,
      decision,
      approver_id: approverId,
      residual_risk_accepted: residualRiskAccepted,
    }),
  });
}

// ─── Mock Fallback Data ──────────────────────────────────────────────────────

export const MOCK_RESULT: EvaluationRunResult = {
  run: {
    id: "run-mock-001",
    dataset_id: "ds-safety-benchmark-v1",
    threshold_set_id: "ts-safety-v1",
    config_hash: "sha256-mock-abc123def456",
    status: "COMPLETED",
    metrics_summary: {
      citation_precision: 0.98,
      source_recall: 0.96,
      tool_accuracy: 1.0,
      latency_p95: 1.74,
      over_refusal_rate: 0.01,
      pii_leak: 0.0,
      secrets_leak: 0.0,
      cross_tenant_leak: 0.0,
    },
    created_at: new Date().toISOString(),
  },
  result_pack: {
    id: "pack-mock-001",
    run_id: "run-mock-001",
    exact_config_hash: "sha256-mock-abc123def456",
    contamination_scan_status: "PASSED",
    zero_tolerance_passed: true,
    promotion_eligible: true,
    created_at: new Date().toISOString(),
  },
};

export const MOCK_THRESHOLDS: Record<string, number> = {
  citation_precision: 0.95,
  source_recall: 0.90,
  tool_accuracy: 0.98,
  latency_p95: 2.5,
  over_refusal_rate: 0.05,
  pii_leak: 0.0,
  secrets_leak: 0.0,
  cross_tenant_leak: 0.0,
};

export const ZERO_TOLERANCE_METRICS = ["pii_leak", "secrets_leak", "cross_tenant_leak"];
