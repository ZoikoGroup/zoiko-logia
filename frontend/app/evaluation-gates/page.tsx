"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { GovernedRegister, type RegisterRecord } from "@/components/governance/GovernedRegister";
import { ContextStrip } from "@/components/overview/OverviewUI";
import { PageShell } from "@/components/governance/PageShell";
import { PanelHeader, PANEL_CLASS } from "@/components/governance/PanelHeader";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import { Pill } from "@/components/governance/Pill";
import { LoadError, errorMessage, formatWhen } from "@/components/governance/LiveStatus";
import { useAuth } from "@/hooks/useAuth";
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
  History,
} from "lucide-react";
import {
  getCurrentConfigHash,
  listDatasets,
  listRuns,
  listThresholdSets,
  promoteRelease,
  runEvaluation,
  type DatasetSummary,
  type MetricFailure,
  type RunHistoryEntry,
  type ThresholdSet,
  ZERO_TOLERANCE_METRICS,
} from "@/lib/evaluation-api";

// ─── Spec-defined metric display names (ZL-T0-10 §3) ─────────────────────────

const METRIC_META: Record<string, { label: string; unit: string; higherIsBetter: boolean; description: string }> = {
  citation_precision:    { label: "Citation Precision",      unit: "%",  higherIsBetter: true,  description: "Share of cases with expected sources whose gold answer cites at least one of them." },
  source_recall:         { label: "Source Recall",           unit: "%",  higherIsBetter: true,  description: "Share of all expected source references that the gold answers actually cite." },
  tool_accuracy:         { label: "Tool Accuracy",           unit: "%",  higherIsBetter: true,  description: "Percentage of tool/API calls that returned correct, expected results." },
  latency_p95:           { label: "P95 Latency",             unit: "s",  higherIsBetter: false, description: "95th percentile time to classify and boundary-check one case." },
  over_refusal_rate:     { label: "Over-Refusal Rate",       unit: "%",  higherIsBetter: false, description: "Share of non-restricted cases the classifier blocked." },
  pii_leak:              { label: "PII Leak Rate",           unit: "%",  higherIsBetter: false, description: "ZERO-TOLERANCE: Any leakage of Personally Identifiable Information blocks release." },
  secrets_leak:          { label: "Secrets Leak Rate",       unit: "%",  higherIsBetter: false, description: "ZERO-TOLERANCE: Any leakage of credentials or API keys blocks release." },
  cross_tenant_leak:     { label: "Cross-Tenant Leak",       unit: "%",  higherIsBetter: false, description: "ZERO-TOLERANCE: Any leakage of one tenant's data to another blocks release." },
  restricted_block_rate: { label: "Restricted Block Rate",   unit: "%",  higherIsBetter: true,  description: "Share of RESTRICTED cases the classifier blocked." },
  boundary_pass_rate:    { label: "Boundary Pass Rate",      unit: "%",  higherIsBetter: true,  description: "Share of gold answers that pass the professional boundary check." },
};

function fmt(key: string, val: number | null | undefined): string {
  if (val === null || val === undefined || Number.isNaN(val)) return "—";
  const meta = METRIC_META[key];
  if (meta?.unit === "%") return `${(val * 100).toFixed(1)}%`;
  if (meta?.unit === "s") return `${val.toFixed(2)}s`;
  return String(val);
}


/** One run as the page shows it — either just executed or picked from history. */
type RunView = {
  id: string;
  datasetId: string;
  thresholdSetId: string;
  configHash: string;
  configMatches: boolean;
  createdAt: string | null;
  metrics: Record<string, number>;
  failures: MetricFailure[];
  unmeasured: string[];
  caseCount: number | null;
  pack: { id: string; contamination_scan_status: string; zero_tolerance_passed: boolean; promotion_eligible: boolean } | null;
  promotion: { decision: string; approver_id: string; residual_risk_accepted: boolean; created_at: string } | null;
};

function fromHistory(entry: RunHistoryEntry): RunView {
  return {
    id: entry.id,
    datasetId: entry.dataset_id,
    thresholdSetId: entry.threshold_set_id,
    configHash: entry.config_hash,
    configMatches: entry.matches_current_config,
    createdAt: entry.created_at,
    metrics: entry.metrics_summary ?? {},
    failures: entry.failures,
    unmeasured: entry.unmeasured_metrics ?? [],
    caseCount: null,
    pack: entry.result_pack,
    promotion: entry.promotion,
  };
}

const PANEL = `${PANEL_CLASS} space-y-4`;
const INPUT = "w-full rounded-lg border border-line bg-soft/40 px-3 py-2 text-xs text-ink font-mono focus:outline-none focus:ring-2 focus:ring-brand/40 transition-all";

export default function EvaluationGatesPage() {
  const { profile, user } = useAuth();
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [thresholdSets, setThresholdSets] = useState<ThresholdSet[]>([]);
  const [history, setHistory] = useState<RunHistoryEntry[]>([]);
  const [deployedHash, setDeployedHash] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");

  const [datasetId, setDatasetId] = useState("");
  const [thresholdId, setThresholdId] = useState("");
  const [configHash, setConfigHash] = useState("");

  const [running, setRunning] = useState(false);
  const [promoting, setPromoting] = useState(false);
  const [actionError, setActionError] = useState("");
  const [selected, setSelected] = useState<RunView | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextDatasets, nextThresholds, nextRuns, hash] = await Promise.all([
        listDatasets(),
        listThresholdSets(),
        listRuns(),
        getCurrentConfigHash(),
      ]);
      setDatasets(nextDatasets);
      setThresholdSets(nextThresholds);
      setHistory(nextRuns);
      setDeployedHash(hash);
      setDatasetId((current) => current || nextDatasets.find((d) => d.case_count > 0)?.id || "");
      setThresholdId((current) => current || nextThresholds[0]?.id || "");
      setConfigHash((current) => current || hash);
      setSelected((current) => current ?? (nextRuns[0] ? fromHistory(nextRuns[0]) : null));
      setLoadError("");
    } catch (err) {
      setLoadError(errorMessage(err, "evaluation data"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch
    void load();
  }, [load]);

  const thresholdsById = useMemo(() => Object.fromEntries(thresholdSets.map((t) => [t.id, t])), [thresholdSets]);
  const selectedDataset = datasets.find((d) => d.id === datasetId);

  async function handleRun() {
    setRunning(true);
    setActionError("");
    try {
      const res = await runEvaluation(datasetId, thresholdId, configHash.trim());
      setSelected({
        id: res.run.id,
        datasetId: res.run.dataset_id,
        thresholdSetId: res.run.threshold_set_id,
        configHash: res.run.config_hash,
        configMatches: res.config_hash_valid,
        createdAt: res.run.created_at,
        metrics: res.run.metrics_summary ?? {},
        failures: res.failures,
        unmeasured: res.unmeasured_metrics,
        caseCount: res.case_count,
        pack: res.result_pack,
        promotion: null,
      });
      setHistory(await listRuns());
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "The evaluation run did not complete.");
    } finally {
      setRunning(false);
    }
  }

  async function handlePromote(decision: "APPROVED" | "REJECTED") {
    if (!selected?.pack) return;
    setPromoting(true);
    setActionError("");
    try {
      const auth = await promoteRelease(selected.pack.id, decision, false);
      setSelected({
        ...selected,
        promotion: { decision: auth.decision, approver_id: auth.approver_id, residual_risk_accepted: auth.residual_risk_accepted, created_at: auth.created_at },
      });
      setHistory(await listRuns());
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "The promotion decision was not recorded.");
    } finally {
      setPromoting(false);
    }
  }

  const threshold = selected ? thresholdsById[selected.thresholdSetId] : undefined;
  const zeroTolerance = threshold?.zero_tolerance_metrics ?? ZERO_TOLERANCE_METRICS;
  const failedMetrics = new Set(selected?.failures.map((f) => f.metric) ?? []);
  const metricKeys = selected
    ? Array.from(new Set([...Object.keys(threshold?.metrics ?? {}), ...Object.keys(selected.metrics)]))
    : [];
  const eligible = selected?.pack?.promotion_eligible ?? false;
  const gateRecords: RegisterRecord[] = metricKeys.map(key => {
    const failure = selected?.failures.find(f => f.metric === key);
    const missing = selected?.unmeasured.includes(key) || selected?.metrics[key] == null;
    const state = failure ? "Failed" : missing ? "Unmeasured" : threshold?.metrics[key] == null ? "Observed" : "Passed";
    return { id: key, title: METRIC_META[key]?.label || key, category: zeroTolerance.includes(key) ? "Zero tolerance" : "Quality metric", state, scope: selected?.datasetId, owner: threshold?.owner,
      facts: { "Run": selected?.id || "Not selected", "Result": fmt(key, selected?.metrics[key]), "Threshold": fmt(key, threshold?.metrics[key]), "Severity": failure?.severity || (zeroTolerance.includes(key) ? "Zero tolerance" : "Quality"), "Threshold owner": threshold?.owner || "Not recorded", "Independent approver": threshold?.approver || "Not recorded" },
      evidence: [METRIC_META[key]?.description || key, failure?.reason || (state === "Passed" ? "No failure reported for this measured threshold." : "Review measurement and threshold evidence."), `Configuration match: ${selected?.configMatches ? "current" : "stale / unverified"}`],
      history: selected ? [`Run recorded ${selected.createdAt || "without timestamp"}`, `Configuration hash: ${selected.configHash}`, `Promotion decision: ${selected.promotion?.decision || "Not recorded"}`] : [],
    };
  });


  return (
    <PageShell
      title="Evaluation Gates"
      subtitle="QA benchmark runs, red-team gates, citation checks, and release promotion authorizations — ZL-T0-10 §3, ZL-T0-11."
    >

      <LiveSourceStatus loading={loading} error={loadError} signedOut={false} reload={load} />

      <ContextStrip jurisdiction={selected?.datasetId || "Select an evaluation run below"} framework="Recorded threshold set" period={selected?.createdAt?.slice(0, 10) || "No snapshot selected"} />
      {selected && <div className={`rounded-lg border p-4 text-xs font-bold ${eligible ? "border-ok/25 bg-ok/5 text-ok" : "border-bad/25 bg-bad/5 text-bad"}`}>{eligible ? "Evaluation pack eligible for independent release review" : "RELEASE HOLD · Evaluation evidence does not authorize promotion"}</div>}
      {!loadError && <GovernedRegister title="Mandatory gate register" inspector="Gate inspector" records={gateRecords} tabs={["Gate checks", "Test evidence", "Decision trail"]} doctrine="Release decisions require every mandatory gate, current configuration evidence, and independent authorization. Aggregate scores cannot override a failed or unmeasured gate." empty="Choose a run from the evaluation console below to inspect its metric gates." metrics={[
        { label: "Metric gates", value: selected ? gateRecords.length : "—", detail: "Selected run and threshold set" },
        { label: "Gates passed", value: selected ? gateRecords.filter(r => r.state === "Passed").length : "—", detail: "Measured thresholds without reported failures", tone: "green" },
        { label: "Failed gates", value: selected ? gateRecords.filter(r => r.state === "Failed").length : "—", detail: "Review blocking evidence", tone: "red" },
        { label: "Unmeasured gates", value: selected ? gateRecords.filter(r => r.state === "Unmeasured").length : "—", detail: "Missing measurements cannot establish a pass", tone: "amber" },
        { label: "Saved evaluation runs", value: history.length, detail: "Available run history" },
      ]} />}
      <div className="space-y-6">

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start max-w-7xl">
        <div className="lg:col-span-8 space-y-6">
          {/* ── Run console ─────────────────────────────────────────────── */}
          <div className={`${PANEL} space-y-5`}>
            <PanelHeader icon={FlaskConical} tone="brand" title="Benchmark Run Console (ZL-T0-10 §3)" subtitle="Runs every visible case in the dataset through the risk classifier and boundary checks." />

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-1">
                <label htmlFor="eval-dataset" className="text-[10px] font-bold text-muted uppercase tracking-wider">Dataset</label>
                <select id="eval-dataset" value={datasetId} onChange={(e) => setDatasetId(e.target.value)} className={INPUT} disabled={!datasets.length}>
                  {!datasets.length && <option value="">{loading ? "Loading…" : "No datasets"}</option>}
                  {datasets.map((d) => (
                    <option key={d.id} value={d.id} disabled={d.case_count === 0}>
                      {d.id} · v{d.version} · {d.case_count} case{d.case_count === 1 ? "" : "s"}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1">
                <label htmlFor="eval-threshold" className="text-[10px] font-bold text-muted uppercase tracking-wider">Threshold Set</label>
                <select id="eval-threshold" value={thresholdId} onChange={(e) => setThresholdId(e.target.value)} className={INPUT} disabled={!thresholdSets.length}>
                  {!thresholdSets.length && <option value="">{loading ? "Loading…" : "No threshold sets"}</option>}
                  {thresholdSets.map((t) => (
                    <option key={t.id} value={t.id}>{t.id} · owner {t.owner}</option>
                  ))}
                </select>
              </div>
              <div className="md:col-span-2 space-y-1">
                <label htmlFor="eval-hash" className="text-[10px] font-bold text-muted uppercase tracking-wider flex items-center gap-1">
                  <Hash size={10} /> Config Hash (immutable snapshot)
                </label>
                <div className="flex gap-2">
                  <input id="eval-hash" value={configHash} onChange={(e) => setConfigHash(e.target.value)} className={INPUT} placeholder="sha256…" />
                  {deployedHash && configHash.trim() !== deployedHash && (
                    <button type="button" onClick={() => setConfigHash(deployedHash)} className="shrink-0 rounded-lg border border-line bg-panel px-3 text-[11px] font-semibold text-ink hover:bg-soft">
                      Use deployed
                    </button>
                  )}
                </div>
                <p className={`text-[10px] ${deployedHash && configHash.trim() !== deployedHash ? "text-warn" : "text-muted"}`}>
                  {deployedHash && configHash.trim() !== deployedHash
                    ? "This is not the deployed configuration — the run will record but cannot be promoted."
                    : "Matches the code and model settings running now (also shown at /health/version)."}
                </p>
              </div>
            </div>

            {selectedDataset && thresholdsById[thresholdId] && thresholdsById[thresholdId].dataset_id !== selectedDataset.id && (
              <p className="flex items-center gap-2 rounded-lg border border-warn/30 bg-warn/5 px-3 py-2 text-[10px] text-warn">
                <AlertTriangle size={12} /> Threshold set {thresholdId} was ratified for {thresholdsById[thresholdId].dataset_id}, not this dataset.
              </p>
            )}

            <button
              id="run-evaluation-btn"
              type="button"
              onClick={handleRun}
              disabled={running || !datasetId || !thresholdId || !configHash.trim()}
              className="flex items-center gap-2 rounded-xl bg-brand px-5 py-2.5 text-xs font-bold text-white shadow-lg shadow-brand/20 hover:bg-brand/90 active:scale-95 transition-all disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {running ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
              {running ? "Running Evaluation…" : "Execute Evaluation Run"}
            </button>

            {actionError && <LoadError message={actionError} />}
          </div>

          {/* ── Selected run ────────────────────────────────────────────── */}
          {selected && (
            <div className={PANEL}>
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line/50 pb-4">
                <div className="flex items-center gap-2">
                  <div className="p-1.5 rounded-lg bg-brand/10 border border-brand/20">
                    <BarChart3 size={14} className="text-brand" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-ink">Metric Results</h3>
                    <p className="text-[11px] text-muted">
                      <code className="font-mono text-[10px]">{selected.id}</code> · {selected.datasetId} · {formatWhen(selected.createdAt)}
                      {selected.caseCount !== null && ` · ${selected.caseCount} cases`}
                      {threshold && ` · thresholds ${threshold.id} (owner ${threshold.owner}, approver ${threshold.approver})`}
                    </p>
                  </div>
                </div>
                <div className={`flex items-center gap-2 rounded-xl border px-3 py-1.5 ${eligible ? "bg-ok/10 border-ok/30 text-ok" : "bg-bad/10 border-bad/30 text-bad"}`}>
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
                    {metricKeys.map((key) => {
                      const meta = METRIC_META[key] ?? { label: key, unit: "", higherIsBetter: true, description: "" };
                      const target = threshold?.metrics[key];
                      const value = selected.metrics[key];
                      const isZt = zeroTolerance.includes(key);
                      const failed = failedMetrics.has(key);
                      const unmeasured = selected.unmeasured.includes(key);
                      return (
                        <tr key={key} className={failed && isZt ? "bg-bad/10" : ""}>
                          <td className="py-3 pr-4">
                            <div className="flex items-center gap-2">
                              {isZt && <span title="Zero-tolerance metric" className="text-[9px] font-bold bg-bad/20 text-bad border border-bad/30 px-1 rounded">ZT</span>}
                              <div>
                                <div className="flex items-center gap-1.5 text-xs font-semibold text-ink">
                                  {meta.label}
                                  {unmeasured && <Pill tone="warn">Not measured</Pill>}
                                </div>
                                <div className="text-[10px] text-muted">
                                  {unmeasured ? "This run cannot measure it yet, so it is left out — a threshold that requires it fails." : meta.description}
                                </div>
                              </div>
                            </div>
                          </td>
                          <td className="py-3 text-right">
                            <span className={`text-sm font-extrabold font-mono ${value === undefined ? "text-muted" : failed ? "text-bad" : unmeasured ? "text-muted" : "text-ok"}`}>{fmt(key, value)}</span>
                          </td>
                          <td className="py-3 text-right text-xs text-muted font-mono">
                            {target === undefined ? "no threshold" : `${meta.higherIsBetter ? "≥" : "≤"} ${fmt(key, target)}`}
                          </td>
                          <td className="py-3 text-right">
                            {target === undefined ? <span className="text-[10px] text-muted">—</span>
                              : failed ? <XCircle size={16} className="text-bad ml-auto" />
                              : <CheckCircle2 size={16} className="text-ok ml-auto" />}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {selected.pack && (
                <div className="grid gap-2 md:grid-cols-3">
                  <div className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs ${selected.pack.contamination_scan_status === "PASSED" ? "bg-ok/5 border-ok/20 text-ok" : "bg-bad/5 border-bad/20 text-bad"}`}>
                    <Activity size={14} /> Contamination: {selected.pack.contamination_scan_status}
                  </div>
                  <div className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs ${selected.pack.zero_tolerance_passed ? "bg-ok/5 border-ok/20 text-ok" : "bg-bad/5 border-bad/20 text-bad"}`}>
                    {selected.pack.zero_tolerance_passed ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
                    Zero-tolerance: {selected.pack.zero_tolerance_passed ? "passed" : "failed"}
                  </div>
                  <div className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs ${selected.configMatches ? "bg-ok/5 border-ok/20 text-ok" : "bg-warn/5 border-warn/20 text-warn"}`}>
                    <Hash size={14} /> {selected.configMatches ? "Deployed config" : "Not the deployed config"}
                  </div>
                </div>
              )}
              <div className="flex items-center gap-2 rounded-lg border border-line/50 bg-soft/30 px-3 py-2 text-[10px] text-muted font-mono break-all">
                <Hash size={11} className="shrink-0" />
                Result Pack: <strong>{selected.pack?.id ?? "—"}</strong> · Hash: <strong>{selected.configHash}</strong>
              </div>

              {selected.promotion ? (
                <div className={`flex flex-wrap items-center gap-2 rounded-xl border px-4 py-3 text-sm font-bold ${selected.promotion.decision === "APPROVED" ? "bg-ok/10 border-ok/30 text-ok" : "bg-bad/10 border-bad/30 text-bad"}`}>
                  {selected.promotion.decision === "APPROVED" ? <ShieldCheck size={16} /> : <Lock size={16} />}
                  Release {selected.promotion.decision.toLowerCase()} by {selected.promotion.approver_id}
                  <span className="text-[11px] font-normal">· {formatWhen(selected.promotion.created_at)}</span>
                </div>
              ) : selected.pack ? (
                <div className="flex flex-wrap items-center gap-3 pt-2 border-t border-line/50">
                  <p className="flex-1 text-[11px] text-muted">
                    Decision recorded as <strong className="text-ink">{profile?.email ?? user?.email ?? "you"}</strong>.
                    {!eligible && " Approval is disabled because this run did not pass every gate."}
                  </p>
                  <div className="flex gap-2">
                    <button
                      id="approve-release-btn"
                      type="button"
                      onClick={() => handlePromote("APPROVED")}
                      disabled={!eligible || promoting}
                      className="flex items-center gap-1.5 rounded-xl bg-ok px-4 py-2.5 text-xs font-bold text-white hover:bg-ok/90 active:scale-95 transition-all disabled:opacity-40 disabled:cursor-not-allowed shadow-lg shadow-ok/20"
                    >
                      {promoting ? <Loader2 size={12} className="animate-spin" /> : <Unlock size={12} />}
                      Approve Release
                    </button>
                    <button
                      id="reject-release-btn"
                      type="button"
                      onClick={() => handlePromote("REJECTED")}
                      disabled={promoting}
                      className="flex items-center gap-1.5 rounded-xl border border-bad/40 bg-bad/10 px-4 py-2.5 text-xs font-bold text-bad hover:bg-bad/20 active:scale-95 transition-all disabled:opacity-40"
                    >
                      <Lock size={12} />
                      Reject
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          )}

          {/* ── Run history ─────────────────────────────────────────────── */}
          <div className={PANEL}>
            <PanelHeader icon={History} tone="info" title="Run History" subtitle="Select a run to see its metrics and record a decision" />
            {loading && history.length === 0 ? (
              <div className="flex items-center justify-center py-8 text-muted"><Loader2 className="animate-spin" size={16} /></div>
            ) : history.length === 0 ? (
              <p className="py-6 text-center text-xs text-muted">No evaluation runs yet.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-[10px] text-muted uppercase tracking-wider border-b border-line/50">
                      <th className="font-bold pb-2.5 pr-3">When</th>
                      <th className="font-bold pb-2.5 pr-3">Dataset</th>
                      <th className="font-bold pb-2.5 pr-3">Failed metrics</th>
                      <th className="font-bold pb-2.5 pr-3">Gate</th>
                      <th className="font-bold pb-2.5">Decision</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line/40">
                    {history.map((entry) => (
                      <tr
                        key={entry.id}
                        onClick={() => setSelected(fromHistory(entry))}
                        className={`cursor-pointer hover:bg-soft/40 ${selected?.id === entry.id ? "bg-brand/5" : ""}`}
                      >
                        <td className="py-2.5 pr-3 whitespace-nowrap text-ink">{formatWhen(entry.created_at)}</td>
                        <td className="py-2.5 pr-3 text-ink">
                          <div className="max-w-[16rem] truncate" title={entry.dataset_id}>{entry.dataset_id}</div>
                          {!entry.matches_current_config && <div className="text-[10px] text-warn">older config</div>}
                        </td>
                        <td className="py-2.5 pr-3 text-muted">
                          {entry.failures.length ? entry.failures.map((f) => METRIC_META[f.metric]?.label ?? f.metric).join(", ") : "None"}
                        </td>
                        <td className="py-2.5 pr-3">
                          <Pill tone={entry.result_pack?.promotion_eligible ? "ok" : "bad"}>{entry.result_pack?.promotion_eligible ? "GO" : "NO-GO"}</Pill>
                        </td>
                        <td className="py-2.5">
                          {entry.promotion
                            ? <Pill tone={entry.promotion.decision === "APPROVED" ? "ok" : "bad"}>{entry.promotion.decision}</Pill>
                            : <span className="text-[10px] text-muted">Pending</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        {/* ── Right column: gate requirements ──────────────────────────── */}
        <div className="lg:col-span-4 space-y-6">
          <div className={PANEL}>
            <PanelHeader icon={GitBranch} tone="warn" title="Gate Requirements (ZL-T0-10)" />
            <div className="space-y-3">
              {[
                { title: "Named Approver", desc: "Release decisions are recorded against the signed-in user, never a typed name.", tone: "warn" as const },
                { title: "Dataset Coupling", desc: "Each threshold set is ratified for one dataset version; the console warns when they do not match.", tone: "bad" as const },
                { title: "Zero-Tolerance Metrics", desc: "PII leak, secrets leak, and cross-tenant leak must all be exactly 0.00%. Any failure blocks promotion.", tone: "bad" as const },
                { title: "Contamination Scan", desc: "Fails when any gold question or answer appears verbatim in the runtime code.", tone: "bad" as const },
                { title: "Immutable Config Hash", desc: "Only a run made against the deployed configuration hash can be promoted.", tone: "info" as const },
                { title: "Real Cases Only", desc: "A dataset with no visible cases is rejected — no simulated metrics.", tone: "info" as const },
              ].map((gate) => (
                <div key={gate.title} className="rounded-xl border border-line/60 bg-soft/20 p-3.5 space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-ink">{gate.title}</span>
                    <Pill tone={gate.tone}>{gate.tone === "bad" ? "Hard Gate" : gate.tone === "warn" ? "Required" : "Enforced"}</Pill>
                  </div>
                  <p className="text-[11px] text-muted leading-relaxed">{gate.desc}</p>
                </div>
              ))}
            </div>
          </div>

        </div>
      </div>
      </div>
    </PageShell>
  );
}
