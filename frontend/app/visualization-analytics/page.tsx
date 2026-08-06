"use client";

import { useEffect, useState } from "react";
import {
  BarChart3, CheckCircle2, Download, FileDown, RefreshCw, Save, AlertTriangle, Repeat, ShieldAlert, Sparkles,
} from "lucide-react";
import { PageShell } from "@/components/governance/PageShell";
import { PanelHeader, PANEL_CLASS } from "@/components/governance/PanelHeader";
import { StatTile } from "@/components/governance/StatTile";
import { Pill } from "@/components/governance/Pill";
import {
  getAuthToken,
  getRecommendationQualitySummary,
  getReplacementMatrix,
  getChartTypePerformance,
  getWeightProposals,
  listRankingConfigurations,
  approveRankingConfiguration,
  type RateMetric,
  type RecommendationQualityRow,
  type ReplacementMatrixCell,
  type ChartTypePerformanceRow,
  type WeightAdjustmentProposal,
  type RankingConfiguration,
} from "@/lib/api";

function formatPercent(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}

// Sample size travels beside every percentage everywhere on this page —
// never render a rate on its own (v6 requirement: "clearly display sample
// size beside every percentage" / "mark low-sample findings as
// insufficient evidence").
function MetricCell({ metric, label }: { metric: RateMetric; label: string }) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold text-ink">{formatPercent(metric.rate)}</span>
        <span className="text-[10px] text-muted">n={metric.sample_size}</span>
      </div>
      {metric.evidence_status === "insufficient_evidence" ? (
        <Pill tone="warn">insufficient evidence</Pill>
      ) : metric.evidence_status === "directional_signal" ? (
        <Pill tone="info">directional signal</Pill>
      ) : (
        <Pill tone="ok">eligible for review</Pill>
      )}
      <span className="sr-only">{label}</span>
    </div>
  );
}

const METRIC_TILES: { key: keyof RecommendationQualityRow; label: string; icon: typeof BarChart3 }[] = [
  { key: "recommendation_retention_rate", label: "Retention rate", icon: CheckCircle2 },
  { key: "alternative_switch_rate", label: "Switch rate", icon: Repeat },
  { key: "png_export_rate", label: "PNG export rate", icon: Download },
  { key: "csv_export_rate", label: "CSV export rate", icon: FileDown },
  { key: "visualization_save_rate", label: "Save rate", icon: Save },
  { key: "render_failure_rate", label: "Render-failure rate", icon: AlertTriangle },
  { key: "fallback_rate", label: "Fallback rate", icon: ShieldAlert },
];

export default function VisualizationAnalyticsPage() {
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [analyticalIntent, setAnalyticalIntent] = useState("");
  const [chartFamily, setChartFamily] = useState("");
  const [originalChartType, setOriginalChartType] = useState("");
  const [rankingVersion, setRankingVersion] = useState("");

  const [summaryRow, setSummaryRow] = useState<RecommendationQualityRow | null>(null);
  const [matrix, setMatrix] = useState<ReplacementMatrixCell[]>([]);
  const [performance, setPerformance] = useState<ChartTypePerformanceRow[]>([]);
  const [proposals, setProposals] = useState<WeightAdjustmentProposal[]>([]);
  const [configurations, setConfigurations] = useState<RankingConfiguration[]>([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");

  const [compareBaselineId, setCompareBaselineId] = useState("");
  const [compareProposedId, setCompareProposedId] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    const token = getAuthToken();
    const filters = {
      dateFrom: dateFrom || undefined,
      dateTo: dateTo || undefined,
      analyticalIntent: analyticalIntent || undefined,
      chartFamily: chartFamily || undefined,
      originalChartType: originalChartType || undefined,
      rankingVersion: rankingVersion || undefined,
    };
    try {
      const [summary, replacementMatrix, chartPerformance, weightProposals, rankingConfigurations] = await Promise.all([
        getRecommendationQualitySummary(token, filters),
        getReplacementMatrix(token, filters),
        getChartTypePerformance(token, filters),
        getWeightProposals(token, { dateFrom: filters.dateFrom, dateTo: filters.dateTo }),
        listRankingConfigurations(token),
      ]);
      setSummaryRow(summary.rows[0] ?? null);
      setMatrix(replacementMatrix.cells);
      setPerformance(chartPerformance.rows);
      setProposals(weightProposals);
      setConfigurations(rankingConfigurations);
    } catch {
      setError("Could not load recommendation-quality data — this dashboard requires Admin access.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function onApprove(id: string) {
    setActionError("");
    try {
      await approveRankingConfiguration(getAuthToken(), id);
      await load();
    } catch {
      setActionError("Could not approve this configuration — you may lack the required permission.");
    }
  }

  const flaggedPerformance = performance.filter(
    (row) => row.unusually_high_switch_rate || row.unusually_high_fallback_rate || row.unusually_high_render_failure_rate,
  );

  const baseline = configurations.find((c) => c.id === compareBaselineId) ?? null;
  const proposed = configurations.find((c) => c.id === compareProposedId) ?? null;
  const weightDimensions = Array.from(
    new Set([...(baseline ? Object.keys(baseline.weights) : []), ...(proposed ? Object.keys(proposed.weights) : [])]),
  ).sort();

  return (
    <PageShell
      title="Visualization Recommendation Analytics"
      subtitle="Aggregate, privacy-safe reporting on Ask Kriton's chart recommendations — no user-level events, no chart data, no query text."
      showMetrics={false}
    >
      <div className={`${PANEL_CLASS} mb-6`}>
        <PanelHeader
          icon={BarChart3}
          title="Filters"
          action={
            <button onClick={load} className="flex items-center gap-1.5 rounded-lg border border-line bg-panel px-2.5 py-1.5 text-xs font-medium text-ink hover:bg-soft">
              <RefreshCw size={12} /> Apply
            </button>
          }
        />
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <label className="flex flex-col gap-1 text-[11px] text-muted">
            From
            <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="rounded-lg border border-line bg-soft px-2 py-1.5 text-sm text-ink outline-none focus:border-brand" />
          </label>
          <label className="flex flex-col gap-1 text-[11px] text-muted">
            To
            <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="rounded-lg border border-line bg-soft px-2 py-1.5 text-sm text-ink outline-none focus:border-brand" />
          </label>
          <label className="flex flex-col gap-1 text-[11px] text-muted">
            Analytical intent
            <input value={analyticalIntent} onChange={(e) => setAnalyticalIntent(e.target.value)} placeholder="e.g. comparison" className="rounded-lg border border-line bg-soft px-2 py-1.5 text-sm text-ink outline-none focus:border-brand" />
          </label>
          <label className="flex flex-col gap-1 text-[11px] text-muted">
            Chart family
            <input value={chartFamily} onChange={(e) => setChartFamily(e.target.value)} placeholder="e.g. temporal_series" className="rounded-lg border border-line bg-soft px-2 py-1.5 text-sm text-ink outline-none focus:border-brand" />
          </label>
          <label className="flex flex-col gap-1 text-[11px] text-muted">
            Original chart
            <input value={originalChartType} onChange={(e) => setOriginalChartType(e.target.value)} placeholder="e.g. donut" className="rounded-lg border border-line bg-soft px-2 py-1.5 text-sm text-ink outline-none focus:border-brand" />
          </label>
          <label className="flex flex-col gap-1 text-[11px] text-muted">
            Ranking version
            <input value={rankingVersion} onChange={(e) => setRankingVersion(e.target.value)} placeholder="e.g. 1.0.0" className="rounded-lg border border-line bg-soft px-2 py-1.5 text-sm text-ink outline-none focus:border-brand" />
          </label>
        </div>
      </div>

      {error && <p className="text-xs text-bad mb-4">{error}</p>}

      {loading ? (
        <p className="text-sm text-muted py-8 text-center">Loading recommendation-quality data…</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 mb-6 md:grid-cols-4">
            <StatTile label="Total selections" value={summaryRow?.total_selections ?? 0} tone="brand" icon={BarChart3} />
            {summaryRow &&
              METRIC_TILES.map(({ key, label, icon: Icon }) => {
                const metric = summaryRow[key] as RateMetric;
                return (
                  <div key={key} className="rounded-lg border border-line bg-panel/85 p-4 shadow-sm">
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <span className="text-[10px] text-muted font-bold uppercase tracking-wider">{label}</span>
                      <Icon size={13} />
                    </div>
                    <MetricCell metric={metric} label={label} />
                  </div>
                );
              })}
          </div>

          <div className={`${PANEL_CLASS} mb-6`}>
            <PanelHeader icon={Repeat} title="Original → active replacement matrix" subtitle="Counts only successful switches — a switch back to the original recommendation is not a replacement." />
            {matrix.length === 0 ? (
              <p className="text-sm text-muted py-6 text-center">No replacements in this range.</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-[11px] text-muted">
                    <th className="font-medium pb-2">Original</th>
                    <th className="font-medium pb-2">Replaced with</th>
                    <th className="font-medium pb-2">Count</th>
                    <th className="font-medium pb-2">Share of original&apos;s switches</th>
                  </tr>
                </thead>
                <tbody>
                  {matrix.map((cell) => (
                    <tr key={`${cell.original_chart_type}-${cell.active_chart_type}`} className="border-t border-line">
                      <td className="py-2 font-semibold text-ink">{cell.original_chart_type}</td>
                      <td className="py-2 text-ink">{cell.active_chart_type}</td>
                      <td className="py-2 text-ink">{cell.count}</td>
                      <td className="py-2"><MetricCell metric={{ rate: cell.rate, numerator: cell.count, sample_size: cell.sample_size, evidence_status: cell.evidence_status }} label="replacement rate" /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className={`${PANEL_CLASS} mb-6`}>
            <PanelHeader icon={AlertTriangle} title="Chart-type performance" subtitle="Rows with an unusually high switch, fallback, or render-failure rate are flagged (only once there is enough evidence to trust the signal)." />
            {performance.length === 0 ? (
              <p className="text-sm text-muted py-6 text-center">No chart selections in this range.</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-[11px] text-muted">
                    <th className="font-medium pb-2">Chart type</th>
                    <th className="font-medium pb-2">Selections</th>
                    <th className="font-medium pb-2">Switch rate</th>
                    <th className="font-medium pb-2">Fallback rate</th>
                    <th className="font-medium pb-2">Render-failure rate</th>
                  </tr>
                </thead>
                <tbody>
                  {performance.map((row) => {
                    const flagged = row.unusually_high_switch_rate || row.unusually_high_fallback_rate || row.unusually_high_render_failure_rate;
                    return (
                      <tr key={`${row.chart_type}-${JSON.stringify(row.group_key)}`} className={`border-t border-line ${flagged ? "bg-bad/5" : ""}`}>
                        <td className="py-2 font-semibold text-ink">
                          {row.chart_type} {flagged && <Pill tone="bad">unusually high</Pill>}
                        </td>
                        <td className="py-2 text-ink">{row.total_selections}</td>
                        <td className="py-2"><MetricCell metric={row.switch_rate} label="switch rate" /></td>
                        <td className="py-2"><MetricCell metric={row.fallback_rate} label="fallback rate" /></td>
                        <td className="py-2"><MetricCell metric={row.render_failure_rate} label="render-failure rate" /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
            {flaggedPerformance.length > 0 && (
              <p className="mt-3 text-[11px] text-bad">{flaggedPerformance.length} chart type(s) flagged for review above.</p>
            )}
          </div>

          <div className={`${PANEL_CLASS} mb-6`}>
            <PanelHeader icon={Sparkles} title="Recommendation-analysis findings" subtitle="Proposed ranking-weight nudges — evidence only, never applied automatically. Every proposal requires manual review." />
            {proposals.length === 0 ? (
              <p className="text-sm text-muted py-6 text-center">No well-evidenced findings in this range.</p>
            ) : (
              <ul className="space-y-3">
                {proposals.map((proposal, index) => (
                  <li key={index} className="rounded-lg border border-line bg-soft p-3 text-sm">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-semibold text-ink">
                        {proposal.affected_analytical_intent ?? proposal.affected_chart_family} — {proposal.current_chart_preference} → {proposal.observed_replacement}
                      </span>
                      <Pill tone="warn">review required</Pill>
                    </div>
                    <p className="mt-1 text-[11px] text-muted">
                      {formatPercent(proposal.retention_or_switch_rate)} switch rate over {proposal.sample_size} selections. Proposed adjustment:{" "}
                      {Object.entries(proposal.proposed_weight_adjustment).map(([dimension, delta]) => `${dimension} ${delta >= 0 ? "+" : ""}${delta.toFixed(3)}`).join(", ")}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className={PANEL_CLASS}>
            <PanelHeader icon={ShieldAlert} title="Ranking configurations" subtitle="Draft, approved — never active automatically. Approving requires Admin permission." />
            {actionError && <p className="text-xs text-bad mb-3">{actionError}</p>}
            {configurations.length === 0 ? (
              <p className="text-sm text-muted py-6 text-center">No ranking configurations have been drafted yet.</p>
            ) : (
              <table className="w-full text-sm mb-6">
                <thead>
                  <tr className="text-left text-[11px] text-muted">
                    <th className="font-medium pb-2">Version</th>
                    <th className="font-medium pb-2">Status</th>
                    <th className="font-medium pb-2">Created by</th>
                    <th className="font-medium pb-2">Approved by</th>
                    <th className="font-medium pb-2" />
                  </tr>
                </thead>
                <tbody>
                  {configurations.map((config) => (
                    <tr key={config.id} className="border-t border-line">
                      <td className="py-2 font-semibold text-ink">{config.ranking_version}</td>
                      <td className="py-2"><Pill tone={config.status === "approved" ? "ok" : "info"}>{config.status}</Pill></td>
                      <td className="py-2 text-xs text-muted">{config.created_by}</td>
                      <td className="py-2 text-xs text-muted">{config.approved_by ?? "—"}</td>
                      <td className="py-2 text-right">
                        {config.status === "draft" && (
                          <button
                            onClick={() => onApprove(config.id)}
                            className="rounded-lg border border-line bg-panel px-2.5 py-1 text-xs font-medium text-ink hover:bg-soft"
                          >
                            Approve
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            <div className="border-t border-line pt-4">
              <h4 className="text-xs font-bold text-ink mb-3">Compare configurations</h4>
              <div className="flex flex-wrap gap-3 mb-4">
                <select value={compareBaselineId} onChange={(e) => setCompareBaselineId(e.target.value)} className="rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand">
                  <option value="">Current version…</option>
                  {configurations.map((c) => <option key={c.id} value={c.id}>{c.ranking_version} ({c.status})</option>)}
                </select>
                <select value={compareProposedId} onChange={(e) => setCompareProposedId(e.target.value)} className="rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand">
                  <option value="">Proposed version…</option>
                  {configurations.map((c) => <option key={c.id} value={c.id}>{c.ranking_version} ({c.status})</option>)}
                </select>
              </div>
              {baseline && proposed && (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-[11px] text-muted">
                      <th className="font-medium pb-2">Weight dimension</th>
                      <th className="font-medium pb-2">{baseline.ranking_version}</th>
                      <th className="font-medium pb-2">{proposed.ranking_version}</th>
                      <th className="font-medium pb-2">Difference</th>
                    </tr>
                  </thead>
                  <tbody>
                    {weightDimensions.map((dimension) => {
                      const before = baseline.weights[dimension] ?? 0;
                      const after = proposed.weights[dimension] ?? 0;
                      const diff = after - before;
                      return (
                        <tr key={dimension} className="border-t border-line">
                          <td className="py-2 text-ink">{dimension}</td>
                          <td className="py-2 text-muted">{before.toFixed(3)}</td>
                          <td className="py-2 text-muted">{after.toFixed(3)}</td>
                          <td className={`py-2 font-semibold ${diff === 0 ? "text-muted" : diff > 0 ? "text-ok" : "text-bad"}`}>
                            {diff === 0 ? "—" : `${diff > 0 ? "+" : ""}${diff.toFixed(3)}`}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </>
      )}
    </PageShell>
  );
}
