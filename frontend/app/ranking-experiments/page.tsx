"use client";

import { useEffect, useState } from "react";
import { FlaskConical, RefreshCw, ShieldAlert, PlayCircle, PauseCircle, CheckCircle2, RotateCcw, Target } from "lucide-react";
import { PageShell } from "@/components/governance/PageShell";
import { PanelHeader, PANEL_CLASS } from "@/components/governance/PanelHeader";
import { Pill } from "@/components/governance/Pill";
import {
  getAuthToken,
  listExperiments,
  getExperimentResults,
  listRankingConfigurations,
  approveExperiment,
  activateExperiment,
  pauseExperiment,
  completeExperiment,
  rollbackExperiment,
  type RankingExperiment,
  type RankingConfiguration,
  type ExperimentResultsResponse,
  type ExperimentGroupMetrics,
  type RateMetricWithConfidenceInterval,
} from "@/lib/api";

const STATUS_TONE: Record<string, "ok" | "info" | "warn" | "bad" | "neutral"> = {
  draft: "neutral", approved: "info", scheduled: "info", active: "ok",
  paused: "warn", completed: "ok", rolled_back: "bad", cancelled: "bad",
};

const RESULT_LABEL: Record<string, string> = {
  insufficient_evidence: "Insufficient evidence",
  experiment_running: "Experiment running",
  directional_result: "Directional result",
  eligible_for_decision: "Eligible for decision",
  guardrail_failed: "Guardrail failed",
};

const RESULT_TONE: Record<string, "ok" | "info" | "warn" | "bad" | "neutral"> = {
  insufficient_evidence: "neutral", experiment_running: "info", directional_result: "warn",
  eligible_for_decision: "ok", guardrail_failed: "bad",
};

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "—";
}

function formatPercent(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}

function MetricRow({ label, metric }: { label: string; metric: RateMetricWithConfidenceInterval }) {
  return (
    <tr className="border-t border-line">
      <td className="py-2 text-ink">{label}</td>
      <td className="py-2 text-ink">{formatPercent(metric.rate)}</td>
      <td className="py-2 text-[11px] text-muted">
        [{formatPercent(metric.confidence_interval_low)}, {formatPercent(metric.confidence_interval_high)}]
      </td>
      <td className="py-2 text-[11px] text-muted">n={metric.sample_size}</td>
      <td className="py-2"><Pill tone={metric.evidence_status === "insufficient_evidence" ? "warn" : metric.evidence_status === "directional_signal" ? "info" : "ok"}>{metric.evidence_status.replace(/_/g, " ")}</Pill></td>
    </tr>
  );
}

function GroupMetricsTable({ group }: { group: ExperimentGroupMetrics }) {
  const rows: [string, RateMetricWithConfidenceInterval][] = [
    ["Retention rate", group.recommendation_retention_rate],
    ["Switch rate", group.alternative_switch_rate],
    ["Views-shown rate", group.alternative_views_shown_rate],
    ["PNG export rate", group.png_export_rate],
    ["CSV export rate", group.csv_export_rate],
    ["Save rate", group.visualization_save_rate],
    ["Render-failure rate", group.render_failure_rate],
    ["Fallback rate", group.fallback_rate],
  ];
  return (
    <div>
      <h4 className="text-xs font-bold text-ink mb-2">
        {group.group === "control" ? "Control" : "Variant"} · {group.ranking_version} · {group.selections} selections
      </h4>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[11px] text-muted">
            <th className="font-medium pb-1">Metric</th>
            <th className="font-medium pb-1">Rate</th>
            <th className="font-medium pb-1">95% CI</th>
            <th className="font-medium pb-1">Sample</th>
            <th className="font-medium pb-1">Evidence</th>
          </tr>
        </thead>
        <tbody>{rows.map(([label, metric]) => <MetricRow key={label} label={label} metric={metric} />)}</tbody>
      </table>
    </div>
  );
}

export default function RankingExperimentsPage() {
  const [experiments, setExperiments] = useState<RankingExperiment[]>([]);
  const [configurations, setConfigurations] = useState<RankingConfiguration[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [results, setResults] = useState<ExperimentResultsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [pendingConfirm, setPendingConfirm] = useState<"activate" | "rollback" | null>(null);
  const [reasonDraft, setReasonDraft] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    const token = getAuthToken();
    try {
      const [experimentList, configurationList] = await Promise.all([
        listExperiments(token),
        listRankingConfigurations(token),
      ]);
      setExperiments(experimentList);
      setConfigurations(configurationList);
    } catch {
      setError("Could not load ranking experiments — this view requires Admin access.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setResults(null);
      return;
    }
    getExperimentResults(getAuthToken(), selectedId).then(setResults).catch(() => setResults(null));
  }, [selectedId, experiments]);

  const selected = experiments.find((e) => e.id === selectedId) ?? null;
  const controlConfig = configurations.find((c) => c.ranking_version === selected?.control_ranking_version) ?? null;
  const variantConfig = configurations.find((c) => c.ranking_version === selected?.variant_ranking_version) ?? null;
  const weightDimensions = Array.from(
    new Set([...(controlConfig ? Object.keys(controlConfig.weights) : []), ...(variantConfig ? Object.keys(variantConfig.weights) : [])]),
  ).sort();
  const changedDimensions = weightDimensions.filter(
    (dimension) => (controlConfig?.weights[dimension] ?? 0) !== (variantConfig?.weights[dimension] ?? 0),
  );

  async function runAction(action: () => Promise<RankingExperiment>) {
    setActionError("");
    try {
      await action();
      setPendingConfirm(null);
      setReasonDraft("");
      await load();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Action failed — you may lack the required permission.");
    }
  }

  return (
    <PageShell
      title="Ranking Experiments"
      subtitle="Controlled A/B comparisons of ranking-weight variants against the current control — deterministic assignment, guardrails, and immediate rollback."
      showMetrics={false}
    >
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[320px_1fr]">
        <div className={PANEL_CLASS}>
          <PanelHeader
            icon={FlaskConical}
            title="Experiments"
            action={
              <button onClick={load} className="flex items-center gap-1.5 rounded-lg border border-line bg-panel px-2.5 py-1.5 text-xs font-medium text-ink hover:bg-soft">
                <RefreshCw size={12} /> Refresh
              </button>
            }
          />
          {error && <p className="text-xs text-bad mb-3">{error}</p>}
          {loading ? (
            <p className="text-sm text-muted py-6 text-center">Loading…</p>
          ) : experiments.length === 0 ? (
            <p className="text-sm text-muted py-6 text-center">No experiments have been drafted yet.</p>
          ) : (
            <ul className="space-y-2">
              {experiments.map((experiment) => (
                <li key={experiment.id}>
                  <button
                    onClick={() => { setSelectedId(experiment.id); setPendingConfirm(null); setActionError(""); }}
                    className={`w-full rounded-lg border px-3 py-2 text-left text-sm ${selectedId === experiment.id ? "border-brand bg-brand/5" : "border-line bg-panel hover:bg-soft"}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-semibold text-ink truncate">{experiment.name}</span>
                      <Pill tone={STATUS_TONE[experiment.status]}>{experiment.status.replace(/_/g, " ")}</Pill>
                    </div>
                    <span className="text-[11px] text-muted">{experiment.control_ranking_version} vs {experiment.variant_ranking_version}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="space-y-6">
          {!selected ? (
            <div className={PANEL_CLASS}>
              <p className="text-sm text-muted py-8 text-center">Select an experiment to view its details.</p>
            </div>
          ) : (
            <>
              <div className={PANEL_CLASS}>
                <PanelHeader icon={Target} title={selected.name} subtitle={selected.description || undefined} />
                {actionError && <p className="text-xs text-bad mb-3">{actionError}</p>}
                <div className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-3">
                  <div><span className="text-[10px] text-muted uppercase font-bold">Status</span><div><Pill tone={STATUS_TONE[selected.status]}>{selected.status.replace(/_/g, " ")}</Pill></div></div>
                  <div><span className="text-[10px] text-muted uppercase font-bold">Control version</span><p className="text-ink">{selected.control_ranking_version}</p></div>
                  <div><span className="text-[10px] text-muted uppercase font-bold">Variant version</span><p className="text-ink">{selected.variant_ranking_version}</p></div>
                  <div><span className="text-[10px] text-muted uppercase font-bold">Allocation</span><p className="text-ink">{selected.control_allocation_percent}% control / {selected.variant_allocation_percent}% variant</p></div>
                  <div><span className="text-[10px] text-muted uppercase font-bold">Minimum sample size</span><p className="text-ink">{selected.minimum_sample_size ?? "not set"}</p></div>
                  <div><span className="text-[10px] text-muted uppercase font-bold">Start / End</span><p className="text-ink">{formatDate(selected.start_at)} → {formatDate(selected.end_at)}</p></div>
                  <div className="sm:col-span-3"><span className="text-[10px] text-muted uppercase font-bold">Targeting rules</span><p className="text-ink text-xs">{Object.keys(selected.targeting_rules).length === 0 ? "Applies to all traffic" : JSON.stringify(selected.targeting_rules)}</p></div>
                  <div><span className="text-[10px] text-muted uppercase font-bold">Primary metrics</span><p className="text-ink text-xs">{selected.primary_metrics.join(", ")}</p></div>
                  <div><span className="text-[10px] text-muted uppercase font-bold">Guardrail metrics</span><p className="text-ink text-xs">{selected.guardrail_metrics.join(", ")}</p></div>
                  {selected.status_reason && (
                    <div className="sm:col-span-3">
                      <span className="text-[10px] text-muted uppercase font-bold">Pause / rollback reason</span>
                      <p className="text-bad text-xs">{selected.status_reason}</p>
                    </div>
                  )}
                </div>
              </div>

              {(selected.status === "approved" || selected.status === "scheduled") && pendingConfirm !== "activate" && (
                <div className={PANEL_CLASS}>
                  <PanelHeader icon={ShieldAlert} title="Review before activation" subtitle="Required review — every changed weight, affected scope, hypothesis, and stop conditions." />
                  <div className="grid grid-cols-2 gap-4 text-sm mb-4">
                    <div><span className="text-[10px] text-muted uppercase font-bold">Hypothesis</span><p className="text-ink">{selected.description || "No hypothesis recorded."}</p></div>
                    <div><span className="text-[10px] text-muted uppercase font-bold">Minimum sample size</span><p className="text-ink">{selected.minimum_sample_size ?? "not set"}</p></div>
                    <div><span className="text-[10px] text-muted uppercase font-bold">Success criteria (primary metrics)</span><p className="text-ink text-xs">{selected.primary_metrics.join(", ")}</p></div>
                    <div><span className="text-[10px] text-muted uppercase font-bold">Stop conditions (guardrail metrics)</span><p className="text-ink text-xs">{selected.guardrail_metrics.join(", ")}</p></div>
                    <div className="col-span-2"><span className="text-[10px] text-muted uppercase font-bold">Affected intents / chart families</span><p className="text-ink text-xs">{Object.keys(selected.targeting_rules).length === 0 ? "All intents and chart families" : JSON.stringify(selected.targeting_rules)}</p></div>
                  </div>
                  <table className="w-full text-sm mb-4">
                    <thead>
                      <tr className="text-left text-[11px] text-muted">
                        <th className="font-medium pb-2">Weight dimension</th>
                        <th className="font-medium pb-2">Control</th>
                        <th className="font-medium pb-2">Variant</th>
                        <th className="font-medium pb-2">Change</th>
                      </tr>
                    </thead>
                    <tbody>
                      {weightDimensions.map((dimension) => {
                        const before = controlConfig?.weights[dimension] ?? 0;
                        const after = variantConfig?.weights[dimension] ?? 0;
                        const changed = before !== after;
                        return (
                          <tr key={dimension} className={`border-t border-line ${changed ? "bg-warn/5" : ""}`}>
                            <td className="py-1.5 text-ink">{dimension}</td>
                            <td className="py-1.5 text-muted">{before.toFixed(3)}</td>
                            <td className="py-1.5 text-muted">{after.toFixed(3)}</td>
                            <td className={`py-1.5 font-semibold ${changed ? "text-warn" : "text-muted"}`}>{changed ? `${after > before ? "+" : ""}${(after - before).toFixed(3)}` : "—"}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  {changedDimensions.length === 0 && <p className="text-xs text-muted mb-3">No weight differences found between these two configurations.</p>}
                  <button onClick={() => setPendingConfirm("activate")} className="flex items-center gap-1.5 rounded-lg bg-brand text-white text-sm font-semibold px-4 py-2 hover:bg-brand-2">
                    <PlayCircle size={14} /> Activate…
                  </button>
                </div>
              )}

              {pendingConfirm === "activate" && (
                <div className={`${PANEL_CLASS} border-warn/40`}>
                  <p className="text-sm text-ink mb-3">
                    Confirm activation of <strong>{selected.name}</strong>? This will start routing matching, deterministically-assigned traffic to the variant.
                  </p>
                  <div className="flex gap-2">
                    <button onClick={() => runAction(() => activateExperiment(getAuthToken(), selected.id))} className="rounded-lg bg-brand text-white text-sm font-semibold px-4 py-2 hover:bg-brand-2">
                      Confirm activation
                    </button>
                    <button onClick={() => setPendingConfirm(null)} className="rounded-lg border border-line bg-panel px-4 py-2 text-sm font-medium text-ink hover:bg-soft">Cancel</button>
                  </div>
                </div>
              )}

              <div className={PANEL_CLASS}>
                <PanelHeader icon={ShieldAlert} title="Actions" />
                <div className="flex flex-wrap gap-2 mb-4">
                  {selected.status === "draft" && (
                    <button onClick={() => runAction(() => approveExperiment(getAuthToken(), selected.id))} className="flex items-center gap-1.5 rounded-lg border border-line bg-panel px-3 py-2 text-xs font-medium text-ink hover:bg-soft">
                      <CheckCircle2 size={13} /> Approve
                    </button>
                  )}
                  {(selected.status === "active" || selected.status === "scheduled") && (
                    <div className="flex items-center gap-2">
                      <input value={reasonDraft} onChange={(e) => setReasonDraft(e.target.value)} placeholder="Pause reason…" className="rounded-lg border border-line bg-soft px-2 py-1.5 text-xs text-ink outline-none focus:border-brand" />
                      <button
                        disabled={!reasonDraft.trim()}
                        onClick={() => runAction(() => pauseExperiment(getAuthToken(), selected.id, reasonDraft))}
                        className="flex items-center gap-1.5 rounded-lg border border-line bg-panel px-3 py-2 text-xs font-medium text-ink hover:bg-soft disabled:opacity-40"
                      >
                        <PauseCircle size={13} /> Pause
                      </button>
                    </div>
                  )}
                  {(selected.status === "active" || selected.status === "paused" || selected.status === "scheduled") && (
                    <button onClick={() => runAction(() => completeExperiment(getAuthToken(), selected.id))} className="flex items-center gap-1.5 rounded-lg border border-line bg-panel px-3 py-2 text-xs font-medium text-ink hover:bg-soft">
                      <CheckCircle2 size={13} /> Complete
                    </button>
                  )}
                  {!["completed", "cancelled", "rolled_back"].includes(selected.status) && pendingConfirm !== "rollback" && (
                    <div className="flex items-center gap-2">
                      <input value={reasonDraft} onChange={(e) => setReasonDraft(e.target.value)} placeholder="Rollback reason…" className="rounded-lg border border-line bg-soft px-2 py-1.5 text-xs text-ink outline-none focus:border-brand" />
                      <button
                        disabled={!reasonDraft.trim()}
                        onClick={() => setPendingConfirm("rollback")}
                        className="flex items-center gap-1.5 rounded-lg border border-bad/40 bg-bad/5 px-3 py-2 text-xs font-medium text-bad hover:bg-bad/10 disabled:opacity-40"
                      >
                        <RotateCcw size={13} /> Rollback…
                      </button>
                    </div>
                  )}
                </div>
                {pendingConfirm === "rollback" && (
                  <div className="rounded-lg border border-bad/40 bg-bad/5 p-3">
                    <p className="text-sm text-ink mb-3">
                      Confirm rollback of <strong>{selected.name}</strong>? The variant will stop being applied to new requests immediately. Reason: “{reasonDraft}”.
                    </p>
                    <div className="flex gap-2">
                      <button onClick={() => runAction(() => rollbackExperiment(getAuthToken(), selected.id, reasonDraft))} className="rounded-lg bg-bad text-white text-sm font-semibold px-4 py-2 hover:opacity-90">
                        Confirm rollback
                      </button>
                      <button onClick={() => setPendingConfirm(null)} className="rounded-lg border border-line bg-panel px-4 py-2 text-sm font-medium text-ink hover:bg-soft">Cancel</button>
                    </div>
                  </div>
                )}
              </div>

              <div className={PANEL_CLASS}>
                <PanelHeader icon={FlaskConical} title="Results" subtitle="Aggregate control vs. variant metrics only — no individual conversation or user is ever shown here." />
                {!results ? (
                  <p className="text-sm text-muted py-6 text-center">No results yet.</p>
                ) : (
                  <>
                    <div className="mb-4 flex items-center gap-2">
                      <Pill tone={RESULT_TONE[results.result_status]}>{RESULT_LABEL[results.result_status]}</Pill>
                      {results.guardrail_findings.length > 0 && (
                        <span className="text-[11px] text-bad">{results.guardrail_findings.join("; ")}</span>
                      )}
                    </div>
                    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                      <GroupMetricsTable group={results.control} />
                      <GroupMetricsTable group={results.variant} />
                    </div>
                  </>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </PageShell>
  );
}
