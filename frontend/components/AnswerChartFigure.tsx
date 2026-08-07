"use client";

import { useEffect, useRef, useState } from "react";
import {
  Area,
  AreaChart,
  ComposedChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Funnel,
  FunnelChart,
  Legend,
  Line,
  LineChart,
  LabelList,
  Pie,
  PieChart,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import type ReactECharts from "echarts-for-react";
import { ArrowDownRight, ArrowUpRight, Check, Copy } from "lucide-react";
import { getAuthToken, getVisualizationPreferences, putVisualizationPreferences, type PresentationChart, type VisualizationPreferences } from "@/lib/api";
import { DOMAIN_LABELS, chartFamily } from "@/lib/presentationLabels";
import { formatPresentationValue, tableRowsToTsv, writeImageToClipboard, writeTextToClipboard } from "@/lib/presentation";
import { serializeContainerSvg, svgToPngBlob } from "@/lib/export/svgToPngBlob";
import { BoxPlotChart } from "@/components/BoxPlotChart";
import { EChartsPresentationChart } from "@/components/EChartsPresentationChart";
import { ChartErrorBoundary } from "@/components/ChartErrorBoundary";
import { emitVisualizationEvent } from "@/lib/telemetry";
import { VisualizationActions } from "@/components/VisualizationActions";
import { exportSvgElementPng } from "@/lib/export/exportSvgElementPng";
import { echartToPngBlob, exportEChartPng } from "@/lib/export/exportEChartPng";
import { exportPresentationChartCsv } from "@/lib/export/exportPresentationChartCsv";
import { exportPresentationWaterfallCsv } from "@/lib/export/exportPresentationWaterfallCsv";
import { saveVisualization } from "@/lib/export/saveVisualization";

const SERIES_COLORS = ["var(--brand)", "var(--info)", "var(--warn)", "var(--ok)"];
// Dynamic Visualization Selection v1/v2 — these chart types aren't category-
// vs-series comparisons the way bar/line/area/donut are, so the "latest/
// average/total per series" metric cards above the chart wouldn't mean
// anything for them; they render just the chart + accessible summary/table.
const NO_METRIC_CARDS_TYPES = new Set([
  "radar", "histogram", "box_plot", "scatter", "bubble", "heatmap", "correlation_matrix", "waterfall",
]);
// Rendered through EChartsPresentationChart rather than Recharts — see that
// file for why (no native heatmap/bullet primitive in Recharts).
const ECHARTS_PRESENTATION_TYPES = new Set(["heatmap", "correlation_matrix", "bullet", "waterfall"]);
// Chart types whose data is structurally invalid outside an exact series
// count — the backend registry already enforces these before selecting the
// type, but a chart re-rendered from a stale saved payload could still
// arrive here malformed.
const REQUIRED_SERIES_COUNT: Record<string, number> = { slope: 2, dumbbell: 2, bullet: 2, bubble: 3 };

function formatChartTypeLabel(type: string): string {
  return type.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatRecommendedView(chart: PresentationChart): string {
  if (chart.grammar?.composition === "facet") return "Small Multiples";
  if (chart.grammar?.composition === "layer") return "Layered Chart";
  return formatChartTypeLabel(chart.type);
}

// Pinned to en-US rather than the workstation locale, matching
// lib/presentation.ts's formatPresentationValue — a governed financial report
// must read identically for every reviewer, and an undefined locale silently
// regroups 120,000 as 1,20,000 on an en-IN machine. That mismatch also made
// the chart disagree with its own "Copy table" output, which has always gone
// through the pinned formatter.
const VALUE_LOCALE = "en-US";

function formatValue(value: number, unit: string): string {
  if (unit === "%") return `${value.toLocaleString(VALUE_LOCALE, { maximumFractionDigits: 2 })}%`;
  const currency = unit === "$" || unit === "USD" ? "USD" : unit === "£" || unit === "GBP" ? "GBP" : unit === "€" || unit === "EUR" ? "EUR" : null;
  if (currency) {
    return value.toLocaleString(VALUE_LOCALE, { style: "currency", currency, maximumFractionDigits: 2 });
  }
  return value.toLocaleString(VALUE_LOCALE, { maximumFractionDigits: 2 });
}

/** series[1] minus series[0] per category — e.g. Actual minus Budget — so a
 * diverging bar chart can show the gap itself (extending above/below zero)
 * instead of two side-by-side bars. */
function buildDivergingData(chart: PresentationChart): { category: string; variance: number }[] {
  return chart.categories.map((category, index) => ({
    category,
    variance: Number(chart.series[1]?.values[index] ?? 0) - Number(chart.series[0]?.values[index] ?? 0),
  }));
}

/** Each category's series values rescaled to sum to 100 — a 100%-stacked
 * bar shows composition (share of the whole), not absolute amounts. */
function buildPercentageStackedData(chart: PresentationChart): Record<string, string | number>[] {
  return chart.categories.map((category, categoryIndex) => {
    const raw = chart.series.map((series) => Number(series.values[categoryIndex]));
    const total = raw.reduce((sum, value) => sum + value, 0);
    return {
      category,
      ...Object.fromEntries(chart.series.map((series, index) => [series.name, total !== 0 ? (raw[index] / total) * 100 : 0])),
    };
  });
}

/** Buckets the single distribution series into ~8 equal-width ranges and
 * counts how many values fall in each — deterministic binning, no
 * statistical library, computed only from the validated values already in
 * the accessible table. */
function buildHistogramBuckets(chart: PresentationChart): { range: string; count: number }[] {
  const values = chart.series[0]?.values.map(Number) ?? [];
  if (values.length === 0) return [];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const bucketCount = Math.min(8, Math.max(1, Math.ceil(Math.sqrt(values.length))));
  const width = (max - min) / bucketCount || 1;
  const buckets = Array.from({ length: bucketCount }, (_, index) => {
    const start = min + index * width;
    const end = index === bucketCount - 1 ? max : start + width;
    return { range: `${formatValue(start, chart.unit)}–${formatValue(end, chart.unit)}`, start, end, count: 0 };
  });
  values.forEach((value) => {
    const bucket = buckets.find((b, index) => value < b.end || index === buckets.length - 1) ?? buckets[buckets.length - 1];
    bucket.count += 1;
  });
  return buckets.map(({ range, count }) => ({ range, count }));
}

/** The single measure across ordered categories (stages) — backend's
 * contains_flow already verified this is monotonically non-increasing
 * before selecting "funnel" at all, so this is a direct pass-through. */
function buildFunnelData(chart: PresentationChart): { name: string; value: number }[] {
  return chart.categories.map((category, index) => ({
    name: category,
    value: Number(chart.series[0]?.values[index] ?? 0),
  }));
}

/** Transposes category-major data into period-major rows — a slope chart
 * needs one Line per entity connecting its two period values, so each row
 * here is one period (x-axis point) with one key per entity. */
function buildSlopeData(chart: PresentationChart): Record<string, string | number>[] {
  return chart.series.map((series) => ({
    period: series.name,
    ...Object.fromEntries(chart.categories.map((category, index) => [category, Number(series.values[index])])),
  }));
}

/** series[0]/series[1] as x/y — backend's contains_paired_measures already
 * rejected constant or identical columns before "scatter" was ever
 * selected, so no further guarding needed here. */
function buildScatterPoints(chart: PresentationChart): { x: number; y: number; label: string }[] {
  return chart.categories.map((category, index) => ({
    x: Number(chart.series[0]?.values[index] ?? 0),
    y: Number(chart.series[1]?.values[index] ?? 0),
    label: category,
  }));
}

/** Same x/y as scatter, plus series[2] as the bubble's size (z) — backend's
 * size_values_non_negative already verified this before "bubble" was ever
 * selected. */
function buildBubblePoints(chart: PresentationChart): { x: number; y: number; z: number; label: string }[] {
  return chart.categories.map((category, index) => ({
    x: Number(chart.series[0]?.values[index] ?? 0),
    y: Number(chart.series[1]?.values[index] ?? 0),
    z: Number(chart.series[2]?.values[index] ?? 0),
    label: category,
  }));
}

/** An invisible "base" (the lower of the two values) plus a thin visible
 * "range" bar between them — the same invisible-base stacking trick as the
 * waterfall charts, here drawing the dumbbell's connecting segment; the two
 * endpoint values are then plotted as Scatter dots on top of it. */
function buildDumbbellData(chart: PresentationChart) {
  return chart.categories.map((category, index) => {
    const baselineValue = Number(chart.series[0]?.values[index] ?? 0);
    const currentValue = Number(chart.series[1]?.values[index] ?? 0);
    return {
      category,
      base: Math.min(baselineValue, currentValue),
      range: Math.abs(currentValue - baselineValue),
      baselineValue,
      currentValue,
    };
  });
}

/** Sorted descending by value — a lollipop is inherently a ranked view (see
 * the "rank"/"highest"/"lowest" query language that selects it over a plain
 * bar in the first place), so the sort is deterministic and always applied,
 * never left to the source table's original row order. */
function buildLollipopData(chart: PresentationChart): { category: string; value: number }[] {
  const rows = chart.categories.map((category, index) => ({
    category, value: Number(chart.series[0]?.values[index] ?? 0),
  }));
  return [...rows].sort((a, b) => b.value - a.value);
}

/** Copies the "View as table" data as TSV rather than CSV: TSV is what
 * Excel and Google Sheets paste straight into columns, which is the whole
 * point of copying a governed figure table. CSV stays available as a file
 * download via VisualizationActions. Values are formatted with the chart's
 * own currency/percent settings so a pasted cell reads the same as the one
 * on screen. */
function CopyTableButton({ chart }: { chart: PresentationChart }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    const header = [chart.x_axis_label || "Label", ...chart.series.map((s) => s.name)];
    const rows = chart.categories.map((category, index) => [
      category,
      ...chart.series.map((series) => {
        const raw = Number(series.values[index]);
        return Number.isFinite(raw) ? formatPresentationValue(raw, chart) : "";
      }),
    ]);
    try {
      await writeTextToClipboard(tableRowsToTsv([header, ...rows]));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      // Clipboard denial is the browser's call, not an app error — the
      // table is still on screen and still exportable as CSV.
    }
  }

  return (
    <button
      type="button"
      onClick={copy}
      className="inline-flex items-center gap-1.5 rounded-lg border border-line px-2 py-1 text-[11px] font-semibold text-muted transition hover:border-brand/40 hover:text-brand"
    >
      {copied ? <Check size={11} /> : <Copy size={11} />}
      {copied ? "Copied" : "Copy table"}
    </button>
  );
}

function buildTableAlternative(chart: PresentationChart) {
  return (
    <table className="w-full border-collapse text-left text-[11px]">
      <thead>
        <tr className="border-b border-line/70 text-muted">
          <th scope="col" className="py-1.5 pr-3 font-semibold">{chart.title}</th>
          {/* Series/category labels are display text, not guaranteed-unique
              IDs — the LLM-composed table behind a chart can legitimately
              repeat a label (e.g. "Headcount" appearing in more than one
              row). Index-qualifying every key avoids React's duplicate-key
              warning and the resulting dropped/duplicated rows, without
              changing what's rendered. */}
          {chart.series.map((series, seriesIndex) => <th key={`${series.name}-${seriesIndex}`} scope="col" className="py-1.5 pr-3 font-semibold">{series.name}</th>)}
        </tr>
      </thead>
      <tbody>
        {chart.categories.map((category, index) => (
          <tr key={`${category}-${index}`} className="border-b border-line/40 last:border-0">
            <th scope="row" className="py-1 pr-3 font-medium text-ink">{category}</th>
            {chart.series.map((series, seriesIndex) => (
              <td key={`${series.name}-${seriesIndex}`} className="py-1 pr-3 text-ink">{formatValue(Number(series.values[index]), series.unit || chart.unit)}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function AnswerChartFigure({
  chart: chartProp, queryId, sourceReferences, conversationId,
}: {
  chart: PresentationChart;
  queryId?: string;
  sourceReferences?: string[];
  conversationId?: string;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const echartsRef = useRef<ReactECharts | null>(null);
  const idempotencyKeyRef = useRef(crypto.randomUUID());
  const [chartRevealed, setChartRevealed] = useState(chartProp.preferred_output !== "table");
  const [defaultStatus, setDefaultStatus] = useState("");
  // Dynamic Visualization Selection v3 — "Try another view". activeType is
  // local, client-only state: switching views never refetches anything,
  // never touches the backend, and never mutates chartProp (the validated
  // payload the backend sent) — it only changes which of that same
  // payload's already-known-compatible interpretations gets rendered.
  const [activeType, setActiveType] = useState<PresentationChart["type"]>(chartProp.type);
  useEffect(() => {
    setActiveType(chartProp.type);
    setChartRevealed(chartProp.preferred_output !== "table");
  }, [chartProp.chart_id, chartProp.type, chartProp.preferred_output]);
  // Shadows the prop for the rest of this component: every existing
  // chart.* reference below (data builders, the render ternary, table
  // alternative, PNG/CSV export, metric cards) transparently follows
  // whichever view is active, with no other code needing to change.
  const chart: PresentationChart = activeType === chartProp.type ? chartProp : { ...chartProp, type: activeType, grammar: null };
  const usesGrammarRenderer = Boolean(chart.grammar);
  const isSwitchedView = activeType !== chartProp.type;
  // A v1/v2 saved payload never populated original_chart_type/schema_version
  // at all — that absence, not any single field, is what "legacy" means here.
  const isLegacyPayload = !chartProp.original_chart_type && !chartProp.schema_version;
  const currentSelectionSource = isSwitchedView
    ? "alternative_switch"
    : isLegacyPayload ? "legacy_payload" : (chartProp.selection_source ?? null);
  const telemetryBase = {
    conversation_id: conversationId,
    query_id: queryId,
    analytical_intent: chartProp.analytical_intent,
    original_chart_type: chartProp.original_chart_type ?? chartProp.type,
    active_chart_type: activeType,
    selection_source: currentSelectionSource,
    renderer: usesGrammarRenderer || ECHARTS_PRESENTATION_TYPES.has(activeType) || activeType === "box_plot" ? "echarts" : "recharts",
    schema_version: chartProp.schema_version,
    chart_family: chartFamily(activeType),
  } as const;

  // Empty state — nothing to chart. Distinct from "invalid data" below:
  // this is a well-formed chart with zero rows/series, not a malformed one.
  if (chart.categories.length === 0 || chart.series.length === 0) {
    return (
      <figure className="min-w-0 overflow-hidden rounded-2xl border border-line bg-panel shadow-[0_12px_40px_rgba(16,24,40,.08)]">
        <div className="p-5 text-center text-xs text-muted">
          <span className="font-semibold text-ink">{chart.title}</span>: no data available to visualize.
        </div>
      </figure>
    );
  }

  // Invalid-data state — several chart types structurally require an exact
  // series count (slope/dumbbell/bullet: two comparable points per entity;
  // bubble: two position measures plus one size measure). The backend
  // registry already enforces this before selecting any of these types, but
  // a chart re-rendered from a stale saved payload could still arrive here
  // malformed.
  const requiredSeriesCount = REQUIRED_SERIES_COUNT[chart.type];
  if (requiredSeriesCount !== undefined && chart.series.length !== requiredSeriesCount) {
    return (
      <figure className="min-w-0 overflow-hidden rounded-2xl border border-line bg-panel shadow-[0_12px_40px_rgba(16,24,40,.08)]">
        <div className="p-5 text-center text-xs text-muted">
          <span className="font-semibold text-ink">{chart.title}</span>: this view needs exactly {requiredSeriesCount} data series to render as a {chart.type.replace("_", " ")} chart.
        </div>
        <div className="border-t border-line px-4 py-3">{buildTableAlternative(chart)}</div>
      </figure>
    );
  }

  const data = chart.categories.map((category, categoryIndex) => ({
    category,
    ...Object.fromEntries(
      chart.series.map((series) => [series.name, Number(series.values[categoryIndex])]),
    ),
  }));
  const showMetricCards = !NO_METRIC_CARDS_TYPES.has(chart.type);
  const accessibleSummary = chart.series
    .map((series) => `${series.name}: ${series.values.map((value, index) => `${chart.categories[index]} ${formatValue(Number(value), chart.unit)}`).join(", ")}`)
    .join(". ");
  const metrics = chart.series.map((series) => {
    const first = Number(series.values[0]);
    const latest = Number(series.values.at(-1));
    const total = series.values.reduce((sum, value) => sum + Number(value), 0);
    const temporal = chart.type === "line" || chart.type === "area";
    const change = temporal && first !== 0 ? ((latest - first) / Math.abs(first)) * 100 : null;
    const value = chart.summary_mode === "latest" ? latest : chart.summary_mode === "average" ? total / series.values.length : total;
    return { name: series.name, value, change };
  });

  if (!chartRevealed) {
    return <figure className="min-w-0 overflow-hidden rounded-2xl border border-line bg-panel">
      <figcaption className="border-b border-line p-4 text-xs font-bold uppercase tracking-wider text-muted">{chart.title}</figcaption>
      <div className="overflow-x-auto p-4">{buildTableAlternative(chart)}</div>
      <div className="border-t border-line p-4"><button type="button" className="rounded-lg border border-line px-3 py-2 text-xs font-bold" onClick={() => setChartRevealed(true)}>Reveal chart</button></div>
    </figure>;
  }

  const preferenceUpdateForActiveView = (current: VisualizationPreferences): VisualizationPreferences | null => {
    if (["grouped_bar", "dumbbell", "lollipop", "diverging_bar"].includes(activeType)) return { ...current, comparison_preference: activeType as VisualizationPreferences["comparison_preference"] };
    if (["line", "area"].includes(activeType)) return { ...current, trend_preference: activeType as VisualizationPreferences["trend_preference"] };
    if (["donut", "composition_bar", "stacked_bar", "percentage_stacked_bar"].includes(activeType)) return { ...current, composition_preference: activeType as VisualizationPreferences["composition_preference"] };
    return null;
  };
  const canSaveActiveAsDefault = ["grouped_bar", "dumbbell", "lollipop", "diverging_bar", "line", "area", "donut", "composition_bar", "stacked_bar", "percentage_stacked_bar"].includes(activeType);

  return (
    <figure data-density={chart.visual_density} data-contrast={chart.contrast_preference} data-reduced-motion={chart.reduced_motion || undefined} className={`min-w-0 overflow-hidden rounded-2xl border bg-panel shadow-[0_12px_40px_rgba(16,24,40,.08)] ${chart.contrast_preference === "high" ? "border-ink" : "border-line"}`}>
      <div className="border-b border-line bg-[radial-gradient(circle_at_top_right,var(--soft),transparent_60%)] p-4 sm:p-5">
        <figcaption className="flex items-center justify-between gap-3 text-xs font-bold uppercase tracking-[0.12em] text-muted">
          <span>{chart.title}</span>
          <span className="rounded-full border border-brand/15 bg-brand/5 px-2.5 py-1 text-[9px] text-brand">{DOMAIN_LABELS[chart.domain ?? "general"]}</span>
        </figcaption>
        {
          // v10 — only ever shown when personalization ACTUALLY won the
          // near-tie break for this chart (never merely because it's
          // enabled), and only for the original recommendation — a manual
          // local switch away from it clears the claim immediately, since
          // that view was the user's own explicit choice, not a
          // personalized recommendation.
          chartProp.personalization_affected_selection && !isSwitchedView && (
            <p className="mt-1.5 text-[10px] font-semibold normal-case text-muted">Recommended based on your visualization preferences</p>
          )
        }
        {chartProp.fallback_note && (
          <p className="mt-2 text-[11px] text-warn">{chartProp.fallback_note}</p>
        )}
        {chartProp.alternatives && chartProp.alternatives.length > 0 && (
          <div className="mt-3 flex items-center gap-2">
            <label htmlFor={`${chartProp.chart_id}-view-select`} className="text-[10px] font-bold uppercase tracking-[0.1em] text-muted">
              View
            </label>
            <select
              id={`${chartProp.chart_id}-view-select`}
              value={activeType}
              onChange={(event) => {
                const nextType = event.target.value as PresentationChart["type"];
                const isKnownTarget = nextType === chartProp.type || (chartProp.alternatives ?? []).includes(nextType);
                if (!isKnownTarget || nextType === activeType) return;
                setActiveType(nextType);
                // Only after the switch itself is applied — a no-op change
                // (same value re-selected) or an out-of-range value never
                // reaches here at all.
                emitVisualizationEvent({
                  ...telemetryBase, event_name: "alternative_view_selected",
                  active_chart_type: nextType, selection_source: "alternative_switch",
                });
              }}
              className="rounded-lg border border-line bg-panel px-2 py-1 text-xs text-ink normal-case"
            >
              <option value={chartProp.type}>{formatRecommendedView(chartProp)} (recommended)</option>
              {chartProp.alternatives.map((alternative) => (
                <option key={alternative} value={alternative}>{formatChartTypeLabel(alternative)}</option>
              ))}
            </select>
          </div>
        )}
        {canSaveActiveAsDefault && <div className="mt-2">
          <button type="button" className="rounded-lg border border-line px-2.5 py-1 text-xs font-semibold" onClick={async () => {
            const token = getAuthToken();
            if (!token) return;
            const current = await getVisualizationPreferences(token);
            const next = preferenceUpdateForActiveView(current);
            if (next) { await putVisualizationPreferences(token, next); setDefaultStatus("Default saved."); }
          }}>Use this view as my default</button>
          <span aria-live="polite" className="ml-2 text-xs text-muted">{defaultStatus}</span>
        </div>}
        <div aria-live="polite" className="sr-only">
          {activeType !== chartProp.type ? `Now showing as ${formatChartTypeLabel(activeType)}.` : ""}
        </div>
        {showMetricCards && (
        <div aria-label="Chart summary metrics" className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {metrics.slice(0, 3).map((metric, index) => {
            const rising = metric.change !== null && metric.change >= 0;
            const TrendIcon = rising ? ArrowUpRight : ArrowDownRight;
            return (
              <div key={metric.name} className="rounded-xl border border-line/70 bg-panel/90 px-3.5 py-3 shadow-sm">
                <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.1em] text-muted">
                  <span className="h-2 w-2 rounded-full" style={{ background: SERIES_COLORS[index % SERIES_COLORS.length] }} />
                  {metric.name}
                </div>
                <div className="mt-1 flex items-end justify-between gap-2">
                  <span className="text-lg font-bold tracking-tight text-ink">{formatValue(metric.value, chart.unit)}</span>
                  {metric.change !== null && (
                    <span className={`inline-flex items-center text-[10px] font-semibold ${rising ? "text-ok" : "text-bad"}`}>
                      <TrendIcon size={12} aria-hidden="true" />{Math.abs(metric.change).toFixed(1)}%
                    </span>
                  )}
                </div>
                <p className="mt-0.5 text-[10px] text-muted">{chart.summary_mode === "latest" ? `Latest · ${chart.categories.at(-1)}` : chart.summary_mode === "average" ? `Average · ${chart.categories.length} values` : `Total · ${chart.categories.length} values`}</p>
              </div>
            );
          })}
        </div>
        )}
      </div>
      <ChartErrorBoundary
        title={chart.title}
        telemetry={{
          conversationId: telemetryBase.conversation_id, queryId: telemetryBase.query_id,
          analyticalIntent: telemetryBase.analytical_intent, originalChartType: telemetryBase.original_chart_type,
          activeChartType: telemetryBase.active_chart_type, selectionSource: telemetryBase.selection_source,
          renderer: telemetryBase.renderer, schemaVersion: telemetryBase.schema_version,
        }}
      >
        <div
          ref={containerRef}
          className="h-[300px] w-full p-3 sm:p-4"
          role="img"
          aria-label={`${chart.title}. ${accessibleSummary}`}
        >
          {usesGrammarRenderer ? (
            <EChartsPresentationChart chart={chart} chartRef={echartsRef} />
          ) : chart.type === "box_plot" ? (
            <BoxPlotChart chart={chart} chartRef={echartsRef} />
          ) : ECHARTS_PRESENTATION_TYPES.has(chart.type) ? (
            <EChartsPresentationChart chart={chart} chartRef={echartsRef} />
          ) : (
          <ResponsiveContainer width="100%" height="100%">
            {chart.type === "dual_axis" ? (
            <ComposedChart data={data} margin={{ top: 10, right: 18, left: 8, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
              <XAxis dataKey="category" stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 11 }} />
              <YAxis yAxisId="left" stroke="var(--brand)" tickFormatter={(value) => formatValue(Number(value), chart.series[0]?.unit || chart.unit)} width={82} />
              <YAxis yAxisId="right" orientation="right" stroke="var(--info)" tickFormatter={(value) => formatValue(Number(value), chart.series[1]?.unit || "%")} width={58} />
              <Tooltip formatter={(value, name) => { const series = chart.series.find((item) => item.name === String(name)); return [formatValue(Number(value), series?.unit || chart.unit), String(name)]; }} />
              <Legend />
              <Bar yAxisId="left" dataKey={chart.series[0].name} fill="var(--brand)" radius={[7, 7, 2, 2]} maxBarSize={48} />
              <Line yAxisId="right" dataKey={chart.series[1].name} stroke="var(--info)" strokeWidth={3} dot={{ r: 4 }} />
            </ComposedChart>
            ) : chart.type === "line" ? (
            <LineChart data={data} margin={{ top: 10, right: 12, left: 4, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
              <XAxis
                dataKey="category"
                stroke="var(--muted)"
                tick={{ fill: "var(--muted)", fontSize: 11 }}
                angle={chart.categories.some((category) => category.length > 12) ? -20 : 0}
                textAnchor={chart.categories.some((category) => category.length > 12) ? "end" : "middle"}
                interval={0}
                height={52}
              />
              <YAxis
                stroke="var(--muted)"
                tick={{ fill: "var(--muted)", fontSize: 11 }}
                tickFormatter={(value) => formatValue(Number(value), chart.unit)}
                width={78}
              />
              <Tooltip
                contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 8, fontSize: 12 }}
                formatter={(value, name) => [formatValue(Number(value), chart.unit), String(name)]}
              />
              {chart.series.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
              {chart.series.map((series, index) => (
                <Line
                  key={`${series.name}-${index}`}
                  dataKey={series.name}
                  type="monotone"
                  stroke={SERIES_COLORS[index % SERIES_COLORS.length]}
                  strokeWidth={2.5}
                  dot={{ r: 3, fill: SERIES_COLORS[index % SERIES_COLORS.length] }}
                  activeDot={{ r: 5 }}
                />
              ))}
            </LineChart>
            ) : chart.type === "area" ? (
            <AreaChart data={data} margin={{ top: 10, right: 12, left: 4, bottom: 20 }}>
              <defs>{chart.series.map((series, index) => <linearGradient key={`${series.name}-${index}`} id={`${chart.chart_id}-fill-${index}`} x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor={SERIES_COLORS[index % SERIES_COLORS.length]} stopOpacity={0.34}/><stop offset="95%" stopColor={SERIES_COLORS[index % SERIES_COLORS.length]} stopOpacity={0.03}/></linearGradient>)}</defs>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
              <XAxis dataKey="category" stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 11 }} interval={0} height={42} />
              <YAxis stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={(value) => formatValue(Number(value), chart.unit)} width={78} />
              <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 12, fontSize: 12 }} formatter={(value, name) => [formatValue(Number(value), chart.unit), String(name)]} />
              {chart.series.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
              {chart.series.map((series, index) => <Area key={`${series.name}-${index}`} dataKey={series.name} type="monotone" stroke={SERIES_COLORS[index % SERIES_COLORS.length]} strokeWidth={2.5} fill={`url(#${chart.chart_id}-fill-${index})`} />)}
            </AreaChart>
            ) : chart.type === "donut" ? (
            <PieChart>
              <Pie data={data} dataKey={chart.series[0].name} nameKey="category" innerRadius="48%" outerRadius="78%" paddingAngle={2} label={({ name, percent }) => `${name} ${((percent ?? 0) * 100).toFixed(0)}%`}>
                {data.map((entry, index) => <Cell key={`${entry.category}-${index}`} fill={SERIES_COLORS[index % SERIES_COLORS.length]} />)}
              </Pie>
              <Tooltip formatter={(value) => formatValue(Number(value), chart.unit)} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
            </PieChart>
            ) : chart.type === "stacked_bar" ? (
            <BarChart data={data} margin={{ top: 10, right: 12, left: 4, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" vertical={false} />
              <XAxis dataKey="category" stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 11 }} interval={0} height={42} />
              <YAxis stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={(value) => formatValue(Number(value), chart.unit)} width={78} />
              <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 12, fontSize: 12 }} formatter={(value, name) => [formatValue(Number(value), chart.unit), String(name)]} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {chart.series.map((series, index) => <Bar key={`${series.name}-${index}`} dataKey={series.name} stackId="a" fill={SERIES_COLORS[index % SERIES_COLORS.length]} maxBarSize={52} />)}
            </BarChart>
            ) : chart.type === "percentage_stacked_bar" ? (
            <BarChart data={buildPercentageStackedData(chart)} margin={{ top: 10, right: 12, left: 4, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" vertical={false} />
              <XAxis dataKey="category" stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 11 }} interval={0} height={42} />
              <YAxis stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={(value) => `${Number(value).toFixed(0)}%`} width={50} domain={[0, 100]} />
              <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 12, fontSize: 12 }} formatter={(value, name) => [`${Number(value).toFixed(1)}%`, String(name)]} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {chart.series.map((series, index) => <Bar key={`${series.name}-${index}`} dataKey={series.name} stackId="a" fill={SERIES_COLORS[index % SERIES_COLORS.length]} maxBarSize={52} />)}
            </BarChart>
            ) : chart.type === "diverging_bar" ? (
            <BarChart data={buildDivergingData(chart)} margin={{ top: 10, right: 12, left: 4, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" vertical={false} />
              <XAxis dataKey="category" stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 11 }} interval={0} height={42} />
              <YAxis stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={(value) => formatValue(Number(value), chart.unit)} width={78} />
              <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 12, fontSize: 12 }} formatter={(value) => [formatValue(Number(value), chart.unit), `${chart.series[1]?.name ?? ""} vs ${chart.series[0]?.name ?? ""}`]} />
              <ReferenceLine y={0} stroke="var(--muted)" />
              <Bar dataKey="variance" radius={[7, 7, 2, 2]} maxBarSize={52}>
                {buildDivergingData(chart).map((entry, index) => <Cell key={`${entry.category}-${index}`} fill={entry.variance >= 0 ? "var(--ok)" : "var(--bad)"} />)}
              </Bar>
            </BarChart>
            ) : chart.type === "radar" ? (
            <RadarChart data={data} margin={{ top: 10, right: 20, left: 20, bottom: 10 }}>
              <PolarGrid stroke="var(--line)" />
              <PolarAngleAxis dataKey="category" tick={{ fill: "var(--muted)", fontSize: 11 }} />
              <PolarRadiusAxis tick={{ fill: "var(--muted)", fontSize: 10 }} tickFormatter={(value) => formatValue(Number(value), chart.unit)} />
              <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 12, fontSize: 12 }} formatter={(value, name) => [formatValue(Number(value), chart.unit), String(name)]} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {chart.series.map((series, index) => <Radar key={`${series.name}-${index}`} dataKey={series.name} stroke={SERIES_COLORS[index % SERIES_COLORS.length]} fill={SERIES_COLORS[index % SERIES_COLORS.length]} fillOpacity={0.25} />)}
            </RadarChart>
            ) : chart.type === "histogram" ? (
            <BarChart data={buildHistogramBuckets(chart)} margin={{ top: 10, right: 12, left: 4, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" vertical={false} />
              <XAxis dataKey="range" stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 10 }} interval={0} angle={-20} textAnchor="end" height={52} />
              <YAxis stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 11 }} allowDecimals={false} width={40} />
              <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 12, fontSize: 12 }} formatter={(value) => [value, "Count"]} />
              <Bar dataKey="count" fill="var(--brand)" radius={[7, 7, 2, 2]} maxBarSize={52} />
            </BarChart>
            ) : chart.type === "funnel" ? (
            <FunnelChart>
              <Tooltip formatter={(value) => formatValue(Number(value), chart.unit)} />
              <Funnel dataKey="value" data={buildFunnelData(chart)} isAnimationActive={false}>
                <LabelList position="right" dataKey="name" fill="var(--ink)" stroke="none" fontSize={11} />
                {buildFunnelData(chart).map((entry, index) => <Cell key={`${entry.name}-${index}`} fill={SERIES_COLORS[index % SERIES_COLORS.length]} />)}
              </Funnel>
            </FunnelChart>
            ) : chart.type === "slope" ? (
            <LineChart data={buildSlopeData(chart)} margin={{ top: 10, right: 60, left: 4, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
              <XAxis dataKey="period" type="category" stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 11 }} />
              <YAxis stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={(value) => formatValue(Number(value), chart.unit)} width={78} />
              <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 12, fontSize: 12 }} formatter={(value, name) => [formatValue(Number(value), chart.unit), String(name)]} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {chart.categories.map((category, index) => (
                <Line key={`${category}-${index}`} dataKey={category} type="linear" stroke={SERIES_COLORS[index % SERIES_COLORS.length]} strokeWidth={2.5} dot={{ r: 4 }} />
              ))}
            </LineChart>
            ) : chart.type === "scatter" ? (
            <ScatterChart margin={{ top: 10, right: 20, left: 4, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
              <XAxis type="number" dataKey="x" name={chart.series[0]?.name} stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={(value) => formatValue(Number(value), chart.series[0]?.unit || chart.unit)} />
              <YAxis type="number" dataKey="y" name={chart.series[1]?.name} stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={(value) => formatValue(Number(value), chart.series[1]?.unit || chart.unit)} width={78} />
              <Tooltip cursor={{ strokeDasharray: "3 3" }} contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 12, fontSize: 12 }} formatter={(value, name) => [formatValue(Number(value), chart.unit), String(name)]} />
              <Scatter data={buildScatterPoints(chart)} fill="var(--brand)" />
            </ScatterChart>
            ) : chart.type === "bubble" ? (
            <ScatterChart margin={{ top: 10, right: 20, left: 4, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
              <XAxis type="number" dataKey="x" name={chart.series[0]?.name} stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={(value) => formatValue(Number(value), chart.series[0]?.unit || chart.unit)} />
              <YAxis type="number" dataKey="y" name={chart.series[1]?.name} stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={(value) => formatValue(Number(value), chart.series[1]?.unit || chart.unit)} width={78} />
              <ZAxis type="number" dataKey="z" range={[60, 600]} name={chart.series[2]?.name} />
              <Tooltip cursor={{ strokeDasharray: "3 3" }} contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 12, fontSize: 12 }} formatter={(value, name) => [formatValue(Number(value), chart.unit), String(name)]} />
              <Scatter data={buildBubblePoints(chart)} fill="var(--brand)" fillOpacity={0.55} />
            </ScatterChart>
            ) : chart.type === "dumbbell" ? (
            <ComposedChart data={buildDumbbellData(chart)} layout="vertical" margin={{ top: 10, right: 30, left: 4, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
              <XAxis type="number" stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={(value) => formatValue(Number(value), chart.unit)} />
              <YAxis type="category" dataKey="category" stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 11 }} width={90} />
              <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 12, fontSize: 12 }} formatter={(value, name) => [formatValue(Number(value), chart.unit), String(name)]} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey="base" stackId="a" fill="transparent" isAnimationActive={false} legendType="none" />
              <Bar dataKey="range" stackId="a" fill="var(--line)" barSize={4} isAnimationActive={false} legendType="none" />
              <Scatter dataKey="baselineValue" name={chart.series[0]?.name} fill={SERIES_COLORS[0]} legendType="circle" />
              <Scatter dataKey="currentValue" name={chart.series[1]?.name} fill={SERIES_COLORS[1]} legendType="circle" />
            </ComposedChart>
            ) : chart.type === "lollipop" ? (
            <ComposedChart data={buildLollipopData(chart)} margin={{ top: 10, right: 12, left: 4, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" vertical={false} />
              <XAxis dataKey="category" stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 11 }} interval={0} height={42} />
              <YAxis stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={(value) => formatValue(Number(value), chart.unit)} width={78} />
              <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 12, fontSize: 12 }} formatter={(value) => [formatValue(Number(value), chart.unit), chart.series[0]?.name ?? ""]} />
              <Bar dataKey="value" barSize={2} fill="var(--line)" isAnimationActive={false} />
              <Scatter dataKey="value" fill="var(--brand)" legendType="none" />
            </ComposedChart>
            ) : chart.type === "composition_bar" ? (
            // The single-total-composition alternative to donut — bars
            // instead of arc/angle, so it tolerates the longer labels and
            // higher category counts donut's own cardinality cap rejects
            // (see presentation_dataprofile.py's composition_bar spec).
            <BarChart data={data} margin={{ top: 10, right: 12, left: 4, bottom: chart.categories.some((category) => category.length > 10) ? 56 : 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" vertical={false} />
              <XAxis
                dataKey="category"
                stroke="var(--muted)"
                tick={{ fill: "var(--muted)", fontSize: 11 }}
                angle={chart.categories.some((category) => category.length > 10) ? -30 : 0}
                textAnchor={chart.categories.some((category) => category.length > 10) ? "end" : "middle"}
                interval={0}
                height={chart.categories.some((category) => category.length > 10) ? 66 : 42}
              />
              <YAxis stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={(value) => formatValue(Number(value), chart.unit)} width={78} />
              <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 12, fontSize: 12 }} formatter={(value) => [formatValue(Number(value), chart.unit), chart.series[0]?.name ?? ""]} />
              <Bar dataKey={chart.series[0]?.name} radius={[7, 7, 2, 2]} maxBarSize={52}>
                {data.map((entry, index) => <Cell key={`${entry.category}-${index}`} fill={SERIES_COLORS[index % SERIES_COLORS.length]} />)}
              </Bar>
            </BarChart>
            ) : (
            <BarChart data={data} margin={{ top: 10, right: 12, left: 4, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" vertical={false} />
              <XAxis dataKey="category" stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 11 }} interval={0} height={42} />
              <YAxis stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={(value) => formatValue(Number(value), chart.unit)} width={78} />
              <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 12, fontSize: 12 }} formatter={(value, name) => [formatValue(Number(value), chart.unit), String(name)]} />
              {chart.series.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
              {chart.series.map((series, index) => <Bar key={`${series.name}-${index}`} dataKey={series.name} fill={SERIES_COLORS[index % SERIES_COLORS.length]} radius={[7, 7, 2, 2]} maxBarSize={52} />)}
            </BarChart>
            )}
          </ResponsiveContainer>
          )}
        </div>
      </ChartErrorBoundary>
      <p className="border-t border-line px-4 py-3 text-[11px] leading-4 text-muted">
        Visualized from the validated table in the answer above; the table remains the textual source of truth.
        {chart.type === "bubble" && chart.series[2] && (
          <> Bubble size represents <span className="font-semibold text-ink">{chart.series[2].name}</span>.</>
        )}
      </p>
      <details
        open={chart.table_alternative_default_open || undefined}
        className="border-t border-line px-4 py-3"
        onToggle={(event) => {
          // A permitted personalization signal (requirement: "table
          // opened") — only fired when opening, not closing, and the
          // shared dedup window already absorbs a rapid open/close/open.
          if (event.currentTarget.open) emitVisualizationEvent({ ...telemetryBase, event_name: "table_view_opened" });
        }}
      >
        <summary className="cursor-pointer text-xs font-semibold text-muted">View as table</summary>
        <div className="mt-2 flex justify-end">
          <CopyTableButton chart={chart} />
        </div>
        <div className="mt-2 overflow-x-auto">{buildTableAlternative(chart)}</div>
      </details>
      <div className="border-t border-line px-4 py-3">
        <VisualizationActions
          onDownloadPng={async () => {
            const ok =
              usesGrammarRenderer || chart.type === "box_plot" || ECHARTS_PRESENTATION_TYPES.has(chart.type)
                ? exportEChartPng(echartsRef, chart.title)
                : await exportSvgElementPng(containerRef.current, chart.title);
            // Only after the PNG actually generated — a failed export
            // (returns/resolves false) never reports success.
            if (ok) emitVisualizationEvent({ ...telemetryBase, event_name: "visualization_exported_png" });
            return ok;
          }}
          onCopyImage={async () => {
            // Same rasterization as the download above, so the pasted figure
            // and the saved file are the same image.
            const blob =
              usesGrammarRenderer || chart.type === "box_plot" || ECHARTS_PRESENTATION_TYPES.has(chart.type)
                ? echartToPngBlob(echartsRef)
                : await svgToPngBlob(serializeContainerSvg(containerRef.current) ?? "");
            if (!blob) return false;
            await writeImageToClipboard(blob);
            // Counted as a PNG export: it is the same artefact leaving the
            // app, just via the clipboard instead of the filesystem.
            emitVisualizationEvent({ ...telemetryBase, event_name: "visualization_exported_png" });
            return true;
          }}
          onExportCsv={async () => {
            if (chart.type === "waterfall") exportPresentationWaterfallCsv(chart);
            else exportPresentationChartCsv(chart);
            // Both exporters build and download the CSV synchronously and
            // throw on failure (caught by VisualizationActions' own action
            // wrapper) rather than returning a status — reaching this line
            // means it succeeded.
            emitVisualizationEvent({ ...telemetryBase, event_name: "visualization_exported_csv" });
          }}
          onSave={
            queryId
              ? async () => {
                  const ok = await saveVisualization(
                    {
                      query_id: queryId,
                      visualization_type: "presentation_chart",
                      title: chart.title,
                      summary: `${chart.series.length} series across ${chart.categories.length} categories.`,
                      // Records the currently active view as the payload's
                      // own type (so it renders as-shown on reload), while
                      // preserving whichever type the ranking algorithm
                      // originally picked — even if the user switched away
                      // from it before saving.
                      payload: { ...chartProp, type: activeType, original_chart_type: chartProp.original_chart_type ?? chartProp.type },
                      source_references: sourceReferences,
                    },
                    idempotencyKeyRef.current,
                  );
                  if (ok) {
                    idempotencyKeyRef.current = crypto.randomUUID();
                    emitVisualizationEvent({ ...telemetryBase, event_name: "visualization_saved" });
                  }
                  return ok;
                }
              : undefined
          }
        />
      </div>
    </figure>
  );
}
