"use client";

import { useState } from "react";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import {
  FlaskConical,
  ShieldCheck,
  ShieldAlert,
  Loader2,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Play,
  GitBranch,
  BarChart3,
  Lock,
  Unlock,
  Activity,
  Hash,
} from "lucide-react";
import {
  runEvaluation,
  promoteRelease,
  getThresholdSet,
  type EvaluationRunResult,
  ZERO_TOLERANCE_METRICS,
} from "@/lib/evaluation-api";

// ─── Spec-defined metric display names (ZL-T0-10 §3) ─────────────────────────

const METRIC_META: Record<string, { label: string; unit: string; higherIsBetter: boolean; description: string }> = {
  citation_precision:    { label: "Citation Precision",      unit: "%",  higherIsBetter: true,  description: "Fraction of responses where every cited source directly supports the answer." },
  source_recall:         { label: "Source Recall",           unit: "%",  higherIsBetter: true,  description: "Fraction of relevant sources correctly included in response source bundle." },
  tool_accuracy:         { label: "Tool Accuracy",           unit: "%",  higherIsBetter: true,  description: "Percentage of tool/API calls that returned correct, expected results." },
  latency_p95:           { label: "P95 Latency",             unit: "s",  higherIsBetter: false, description: "95th percentile end-to-end response time in seconds under benchmark load." },
  over_refusal_rate:     { label: "Over-Refusal Rate",       unit: "%",  higherIsBetter: false, description: "Rate at which the model unnecessarily refused benign queries." },
  pii_leak:              { label: "PII Leak Rate",           unit: "%",  higherIsBetter: false, description: "ZERO-TOLERANCE: Any leakage of Personally Identifiable Information blocks release." },
  secrets_leak:          { label: "Secrets Leak Rate",       unit: "%",  higherIsBetter: false, description: "ZERO-TOLERANCE: Any leakage of credentials or API keys blocks release." },
  cross_tenant_leak:     { label: "Cross-Tenant Leak",       unit: "%",  higherIsBetter: false, description: "ZERO-TOLERANCE: Any leakage of one tenant's data to another blocks release." },
};

const DEFAULT_DATASET_ID = "ds-safety-benchmark-v1";
const DEFAULT_THRESHOLD_ID = "ts-safety-v1";

function fmt(key: string, val: number): string {
  const meta = METRIC_META[key];
  if (!meta) return String(val);
  if (meta.unit === "%") return `${(val * 100).toFixed(1)}%`;
  if (meta.unit === "s") return `${val.toFixed(2)}s`;
  return String(val);
}

function fmtThreshold(key: string, val: number): string {
  return fmt(key, val);
}

function metricPassed(key: string, actual: number, threshold: number): boolean {
  const meta = METRIC_META[key];
  if (!meta) return true;
  return meta.higherIsBetter ? actual >= threshold : actual <= threshold;
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function MetricRow({
  metricKey, value, threshold, isZeroTol,
}: { metricKey: string; value: number; threshold: number; isZeroTol: boolean }) {
  const meta = METRIC_META[metricKey] ?? { label: metricKey, unit: "", higherIsBetter: true, description: "" };
  const passed = metricPassed(metricKey, value, threshold);
  const isCriticalFail = isZeroTol && !passed;

  return (
    <tr className={`transition-colors ${isCriticalFail ? "bg-bad/10" : "hover:bg-soft/10"}`}>
      <td className="py-3 pr-4">
        <div className="flex items-center gap-2">
          {isZeroTol && (
            <span title="Zero-tolerance metric" className="text-[9px] font-bold bg-bad/20 text-bad border border-bad/30 px-1 rounded">
              ZT
            </span>
          )}
          <div>
            <div className="text-xs font-semibold text-ink">{meta.label}</div>
            <div className="text-[10px] text-muted">{meta.description}</div>
          </div>
        </div>
      </td>
      <td className="py-3 text-right">
        <span className={`text-sm font-extrabold font-mono ${passed ? "text-ok" : "text-bad"}`}>
          {fmt(metricKey, value)}
        </span>
      </td>
      <td className="py-3 text-right text-xs text-muted font-mono">
        {meta.higherIsBetter ? "≥" : "≤"} {fmtThreshold(metricKey, threshold)}
      </td>
      <td className="py-3 text-right">
        {passed ? (
          <CheckCircle2 size={16} className="text-ok ml-auto" />
        ) : (
          <XCircle size={16} className="text-bad ml-auto" />
        )}
      </td>
    </tr>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function EvaluationGatesPage() {
  const [configHash, setConfigHash] = useState("sha256-kriton-v2026.07.08-prod");
  const [datasetId, setDatasetId] = useState(DEFAULT_DATASET_ID);
  const [thresholdId, setThresholdId] = useState(DEFAULT_THRESHOLD_ID);
  const [approverId, setApproverId] = useState("qa-lead@zoiko.ai");

  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<EvaluationRunResult | null>(null);
  const [thresholds, setThresholds] = useState<Record<string, number>>({});
  const [error, setError] = useState<string | null>(null);
  const [promoting, setPromoting] = useState(false);
  const [promoted, setPromoted] = useState<{ decision: string; id: string } | null>(null);

  async function handleRun() {
    setRunning(true);
    setResult(null);
    setError(null);
    setPromoted(null);

    const [res, thresholdSet] = await Promise.all([
      runEvaluation(datasetId, thresholdId, configHash),
      getThresholdSet(thresholdId),
    ]);

    if (res) {
      setResult(res);
      setThresholds(thresholdSet?.metrics ?? {});
    } else {
      setError("Could not reach the evaluation backend. The run did not complete.");
    }
    setRunning(false);
  }

  async function handlePromote(decision: "APPROVED" | "REJECTED") {
    if (!result) return;
    setPromoting(true);
    setError(null);
    const auth = await promoteRelease(result.result_pack.id, decision, approverId, false);
    if (auth) {
      setPromoted({ decision: auth.decision, id: auth.id });
    } else {
      setError("Could not reach the backend. The promotion decision was not recorded.");
    }
    setPromoting(false);
  }

  const metrics = result?.run.metrics_summary ?? null;
  const pack = result?.result_pack ?? null;
  const eligible = pack?.promotion_eligible ?? false;

  return (
    <main className="flex-1 overflow-y-auto p-6 space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start max-w-7xl">

        {/* ── Left Column: Run Console ─────────────────────────────────── */}
        <div className="lg:col-span-8 space-y-6">

          {/* Benchmark Run Console */}
          <div className="rounded-2xl border border-line bg-panel/75 backdrop-blur-md p-6 shadow-[0_12px_30px_rgba(0,0,0,0.02)] space-y-5">
            <div className="flex items-center gap-2 border-b border-line/50 pb-4">
              <div className="p-1.5 rounded-lg bg-brand/10 border border-brand/20">
                <FlaskConical size={14} className="text-brand" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-ink">Benchmark Run Console (ZL-T0-10 §3)</h3>
                <p className="text-[11px] text-muted">Configure and execute an evaluation against a versioned dataset + threshold set.</p>
              </div>
            </div>

            {/* Config Inputs */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-1">
                <label className="text-[10px] font-bold text-muted uppercase tracking-wider">Dataset ID</label>
                <input
                  value={datasetId}
                  onChange={(e) => setDatasetId(e.target.value)}
                  className="w-full rounded-lg border border-line bg-soft/40 px-3 py-2 text-xs text-ink font-mono focus:outline-none focus:ring-2 focus:ring-brand/40 transition-all"
                  placeholder="ds-safety-benchmark-v1"
                />
              </div>
              <div className="space-y-1">
                <label className="text-[10px] font-bold text-muted uppercase tracking-wider">Threshold Set ID</label>
                <input
                  value={thresholdId}
                  onChange={(e) => setThresholdId(e.target.value)}
                  className="w-full rounded-lg border border-line bg-soft/40 px-3 py-2 text-xs text-ink font-mono focus:outline-none focus:ring-2 focus:ring-brand/40 transition-all"
                  placeholder="ts-safety-v1"
                />
              </div>
              <div className="md:col-span-2 space-y-1">
                <label className="text-[10px] font-bold text-muted uppercase tracking-wider flex items-center gap-1">
                  <Hash size={10} /> Config Hash (immutable snapshot)
                </label>
                <input
                  value={configHash}
                  onChange={(e) => setConfigHash(e.target.value)}
                  className="w-full rounded-lg border border-line bg-soft/40 px-3 py-2 text-xs text-ink font-mono focus:outline-none focus:ring-2 focus:ring-brand/40 transition-all"
                  placeholder="sha256-..."
                />
              </div>
            </div>

            <button
              id="run-evaluation-btn"
              onClick={handleRun}
              disabled={running}
              className="flex items-center gap-2 rounded-xl bg-brand px-5 py-2.5 text-xs font-bold text-white shadow-lg shadow-brand/20 hover:bg-brand/90 active:scale-95 transition-all disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {running ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
              {running ? "Running Evaluation…" : "Execute Evaluation Run"}
            </button>

            {error && (
              <div className="flex items-center gap-2 rounded-lg border border-bad/30 bg-bad/5 px-3 py-2 text-[10px] text-bad">
                <AlertTriangle size={12} />
                {error}
              </div>
            )}
          </div>

          {/* Metrics Results Table */}
          {metrics && pack && (
            <div className="rounded-2xl border border-line bg-panel/75 backdrop-blur-md p-6 shadow-[0_12px_30px_rgba(0,0,0,0.02)] space-y-4">
              <div className="flex items-center justify-between border-b border-line/50 pb-4">
                <div className="flex items-center gap-2">
                  <div className="p-1.5 rounded-lg bg-brand/10 border border-brand/20">
                    <BarChart3 size={14} className="text-brand" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-ink">Metric Results</h3>
                    <p className="text-[11px] text-muted">
                      Run ID: <code className="font-mono text-[10px]">{result?.run.id}</code>
                    </p>
                  </div>
                </div>

                {/* Go / No-Go Badge */}
                <div className={`flex items-center gap-2 rounded-xl border px-3 py-1.5 ${
                  eligible
                    ? "bg-ok/10 border-ok/30 text-ok"
                    : "bg-bad/10 border-bad/30 text-bad"
                }`}>
                  {eligible ? <ShieldCheck size={16} /> : <ShieldAlert size={16} />}
                  <span className="text-xs font-extrabold uppercase tracking-wider">
                    {eligible ? "GO — Eligible for Promotion" : "NO-GO — Blocked"}
                  </span>
                </div>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-[10px] text-muted uppercase tracking-wider border-b border-line/50">
                      <th className="font-bold pb-2.5">Metric</th>
                      <th className="font-bold pb-2.5 text-right">Actual</th>
                      <th className="font-bold pb-2.5 text-right">Threshold</th>
                      <th className="font-bold pb-2.5 text-right">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line/40">
                    {Object.entries(metrics).map(([key, value]) => (
                      <MetricRow
                        key={key}
                        metricKey={key}
                        value={value as number}
                        threshold={thresholds[key] ?? 0}
                        isZeroTol={ZERO_TOLERANCE_METRICS.includes(key)}
                      />
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Contamination Scan */}
              <div className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs ${
                pack.contamination_scan_status === "PASSED"
                  ? "bg-ok/5 border-ok/20 text-ok"
                  : "bg-bad/5 border-bad/20 text-bad"
              }`}>
                <Activity size={14} />
                <span className="font-bold">Contamination Scan:</span>
                <span>{pack.contamination_scan_status}</span>
              </div>

              {/* Zero-Tolerance Status */}
              <div className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs ${
                pack.zero_tolerance_passed
                  ? "bg-ok/5 border-ok/20 text-ok"
                  : "bg-bad/5 border-bad/20 text-bad"
              }`}>
                {pack.zero_tolerance_passed ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
                <span className="font-bold">Zero-Tolerance Gate:</span>
                <span>{pack.zero_tolerance_passed ? "All zero-tolerance metrics passed" : "BLOCKED — one or more zero-tolerance metrics failed"}</span>
              </div>

              {/* Config Hash Lock */}
              <div className="flex items-center gap-2 rounded-lg border border-line/50 bg-soft/30 px-3 py-2 text-[10px] text-muted font-mono">
                <Hash size={11} />
                Result Pack: <strong>{pack.id}</strong> · Hash: <strong>{pack.exact_config_hash}</strong>
              </div>

              {/* Promotion Actions */}
              {!promoted ? (
                <div className="flex items-center gap-3 pt-2 border-t border-line/50">
                  <div className="space-y-1 flex-1">
                    <label className="text-[10px] font-bold text-muted uppercase tracking-wider">QA Approver ID</label>
                    <input
                      value={approverId}
                      onChange={(e) => setApproverId(e.target.value)}
                      className="w-full rounded-lg border border-line bg-soft/40 px-3 py-2 text-xs text-ink font-mono focus:outline-none focus:ring-2 focus:ring-brand/40"
                    />
                  </div>
                  <div className="flex gap-2 self-end">
                    <button
                      id="approve-release-btn"
                      onClick={() => handlePromote("APPROVED")}
                      disabled={!eligible || promoting}
                      className="flex items-center gap-1.5 rounded-xl bg-ok px-4 py-2.5 text-xs font-bold text-white hover:bg-ok/90 active:scale-95 transition-all disabled:opacity-40 disabled:cursor-not-allowed shadow-lg shadow-ok/20"
                    >
                      {promoting ? <Loader2 size={12} className="animate-spin" /> : <Unlock size={12} />}
                      Approve Release
                    </button>
                    <button
                      id="reject-release-btn"
                      onClick={() => handlePromote("REJECTED")}
                      disabled={promoting}
                      className="flex items-center gap-1.5 rounded-xl border border-bad/40 bg-bad/10 px-4 py-2.5 text-xs font-bold text-bad hover:bg-bad/20 active:scale-95 transition-all disabled:opacity-40"
                    >
                      <Lock size={12} />
                      Reject
                    </button>
                  </div>
                </div>
              ) : (
                <div className={`flex items-center gap-2 rounded-xl border px-4 py-3 text-sm font-bold ${
                  promoted.decision === "APPROVED"
                    ? "bg-ok/10 border-ok/30 text-ok"
                    : "bg-bad/10 border-bad/30 text-bad"
                }`}>
                  {promoted.decision === "APPROVED" ? <ShieldCheck size={16} /> : <Lock size={16} />}
                  Release {promoted.decision} · Auth ID: <code className="font-mono text-[11px] ml-1">{promoted.id}</code>
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── Right Column: Gate Spec Reference ──────────────────────────── */}
        <div className="lg:col-span-4 space-y-6">

          {/* Gate Reference Cards */}
          <div className="rounded-2xl border border-line bg-panel/75 backdrop-blur-md p-6 shadow-[0_12px_30px_rgba(0,0,0,0.02)] space-y-4">
            <div className="flex items-center gap-2 border-b border-line/50 pb-4">
              <div className="p-1.5 rounded-lg bg-warn/10 border border-warn/20">
                <GitBranch size={14} className="text-warn" />
              </div>
              <h3 className="text-sm font-bold text-ink">Gate Requirements (ZL-T0-10)</h3>
            </div>

            <div className="space-y-3">
              {[
                { title: "Named QA Owner", desc: "Every gate run must record a named quality assurance owner before production deploy.", tone: "warn" as const },
                { title: "Failure Replay", desc: "All gate failures must be reproducible via replay on the versioned benchmark dataset.", tone: "warn" as const },
                { title: "Dataset Coupling", desc: "Run must reference a specific dataset_version_id. Uncoupled runs are invalid.", tone: "bad" as const },
                { title: "Zero-Tolerance Metrics", desc: "PII leak, secrets leak, and cross-tenant leak must all be exactly 0.00%. Any failure blocks promotion.", tone: "bad" as const },
                { title: "Contamination Scan", desc: "Dataset must pass contamination scan — no training data overlap with evaluation set.", tone: "bad" as const },
                { title: "Immutable Config Hash", desc: "Result Pack stores a sha256 config hash. Only the exact same hash can be promoted.", tone: "info" as const },
              ].map((gate) => (
                <div key={gate.title} className="rounded-xl border border-line/60 bg-soft/20 p-3.5 space-y-1 hover:bg-panel hover:shadow-md transition-all duration-200">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-ink">{gate.title}</span>
                    <Pill tone={gate.tone}>
                      {gate.tone === "bad" ? "Hard Gate" : gate.tone === "warn" ? "Required" : "Enforced"}
                    </Pill>
                  </div>
                  <p className="text-[11px] text-muted leading-relaxed">{gate.desc}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Live Run Status */}
          {result && (
            <Card>
              <div className="flex items-center gap-2 mb-3">
                <Activity size={13} className="text-brand" />
                <span className="text-xs font-bold text-ink">Last Run Summary</span>
              </div>
              <div className="space-y-2 text-[11px] text-muted">
                <div className="flex justify-between"><span>Status</span><Pill tone={result.run.status === "COMPLETED" ? "ok" : "warn"}>{result.run.status}</Pill></div>
                <div className="flex justify-between"><span>Config Hash</span><code className="font-mono text-[10px] text-ink truncate max-w-32" title={result.run.config_hash}>{result.run.config_hash.slice(0, 20)}…</code></div>
                <div className="flex justify-between"><span>Promotion</span><Pill tone={eligible ? "ok" : "bad"}>{eligible ? "Eligible" : "Blocked"}</Pill></div>
                <div className="flex justify-between"><span>Zero-Tol</span><Pill tone={pack?.zero_tolerance_passed ? "ok" : "bad"}>{pack?.zero_tolerance_passed ? "PASS" : "FAIL"}</Pill></div>
              </div>
            </Card>
          )}
        </div>

      </div>
    </main>
  );
}
