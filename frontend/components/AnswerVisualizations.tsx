"use client";

import { useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ArrowDownRight, ArrowRight, ArrowUpRight, Check, Clock3, Copy, Download, GitBranch, Hash, ImageDown, ListTree, Maximize2, Sparkles } from "lucide-react";
import type { AnswerPresentation, PresentationChart } from "@/lib/api";
import { CHART_SERIES_COLORS } from "@/lib/chartColors";
import { formatPresentationValue, presentationChartToCsv, presentationChartToMarkdown, safeDownloadName, writeTextToClipboard } from "@/lib/presentation";
import { StatTile } from "@/components/governance/StatTile";


// Same validated, CVD-safe palette used by the free-text KritonChart
// component (ask-kriton/page.tsx) — one categorical palette for every
// chart surface in the app, not two that can drift apart.
const SERIES_COLORS = CHART_SERIES_COLORS;

function formatValue(value: number, unit: string): string {
  if (unit === "%") return `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}%`;
  const currency = unit === "$" || unit === "USD" ? "USD" : unit === "£" || unit === "GBP" ? "GBP" : unit === "€" || unit === "EUR" ? "EUR" : null;
  if (currency) {
    return value.toLocaleString(undefined, { style: "currency", currency, maximumFractionDigits: 2 });
  }
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function ChartActions({ chart }: { chart: PresentationChart }) {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");

  async function copyData() {
    try {
      await writeTextToClipboard(presentationChartToMarkdown(chart));
      setCopied(true);
      setError("");
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setError("Copy failed");
    }
  }

  function downloadCsv() {
    downloadBlob(
      new Blob([presentationChartToCsv(chart)], { type: "text/csv;charset=utf-8" }),
      safeDownloadName(chart.title, "csv"),
    );
  }

  function downloadSvg(event: React.MouseEvent<HTMLButtonElement>) {
    const chartRoot = event.currentTarget.closest("figure")?.querySelector("[data-chart-canvas]");
    const svg = chartRoot?.querySelector("svg");
    if (!svg) {
      setError("Image unavailable");
      return;
    }
    const clone = svg.cloneNode(true) as SVGElement;
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    const rootStyles = getComputedStyle(document.documentElement);
    const style = document.createElementNS("http://www.w3.org/2000/svg", "style");
    style.textContent = `:root{--ink:${rootStyles.getPropertyValue("--ink")};--muted:${rootStyles.getPropertyValue("--muted")};--line:${rootStyles.getPropertyValue("--line")};--panel:${rootStyles.getPropertyValue("--panel")};}`;
    clone.prepend(style);
    downloadBlob(
      new Blob([new XMLSerializer().serializeToString(clone)], { type: "image/svg+xml;charset=utf-8" }),
      safeDownloadName(chart.title, "svg"),
    );
    setError("");
  }

  async function openFullscreen(event: React.MouseEvent<HTMLButtonElement>) {
    const figure = event.currentTarget.closest("figure");
    if (!figure?.requestFullscreen) {
      setError("Fullscreen unavailable");
      return;
    }
    try {
      await figure.requestFullscreen();
      setError("");
    } catch {
      setError("Fullscreen unavailable");
    }
  }

  const actionClass = "inline-flex h-8 items-center gap-1.5 rounded-lg px-2 text-[11px] font-medium text-muted transition hover:bg-soft hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/40";
  return (
    <div className="flex flex-wrap items-center justify-end gap-1" aria-label="Chart actions">
      <button type="button" onClick={copyData} className={actionClass} aria-label="Copy chart data as a Markdown table">
        {copied ? <Check size={13} /> : <Copy size={13} />}{copied ? "Copied" : "Copy"}
      </button>
      <button type="button" onClick={downloadCsv} className={actionClass} aria-label="Download chart data as CSV">
        <Download size={13} />CSV
      </button>
      <button type="button" onClick={downloadSvg} className={actionClass} aria-label="Download chart as SVG">
        <ImageDown size={13} />SVG
      </button>
      <button type="button" onClick={openFullscreen} className={actionClass} aria-label="View chart full screen">
        <Maximize2 size={13} />Full screen
      </button>
      {error && <span className="px-2 text-[10px] font-medium text-bad">{error}</span>}
      <span className="sr-only" role="status" aria-live="polite">{copied ? "Chart data copied" : error}</span>
    </div>
  );
}

export function AnswerVisualizations({
  presentation,
  onFollowUp,
}: {
  presentation: AnswerPresentation;
  onFollowUp?: (question: string) => void;
}) {
  const charts = presentation.charts ?? [];
  const metrics = presentation.metrics ?? [];
  const guides = presentation.guides ?? [];
  const sections = presentation.sections ?? [];
  const followUps = presentation.follow_up_questions ?? [];
  if (!charts.length && !metrics.length && !guides.length && sections.length < 2 && !followUps.length) return null;

  return (
    <div className="mt-5 space-y-4" aria-label="Answer presentation">
      {guides.map((guide) => {
        const GuideIcon = guide.type === "timeline" ? Clock3
          : guide.type === "checklist" ? Check
          : guide.type === "decision_flow" ? GitBranch
          : ListTree;
        return (
          <section key={guide.guide_id} className="overflow-hidden rounded-2xl border border-line bg-[linear-gradient(145deg,var(--panel),var(--soft))] shadow-[0_8px_30px_rgba(16,24,40,.06)]">
            <div className="h-1 bg-[linear-gradient(90deg,var(--brand),var(--info),var(--ok))]" aria-hidden="true" />
            <div className="p-4 sm:p-5">
            <h3 className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.12em] text-muted">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-brand/10 text-brand"><GuideIcon size={15} aria-hidden="true" /></span>
              {guide.title}
            </h3>
            <ol className={`mt-5 ${guide.type === "timeline" ? "relative ml-3 space-y-0 border-l-2 border-brand/20" : guide.type === "process" || guide.type === "decision_flow" ? "grid gap-3 sm:grid-cols-2 lg:grid-cols-3" : "grid gap-2 sm:grid-cols-2"}`}>
              {guide.items.map((item, index) => (
                <li key={`${guide.guide_id}-${index}`} className={`relative flex gap-3 text-xs leading-5 text-ink ${guide.type === "timeline" ? "-ml-[13px] pb-5 last:pb-0" : "rounded-xl border border-line/70 bg-panel/90 p-3.5 shadow-sm transition hover:-translate-y-0.5 hover:border-brand/30 hover:shadow-md"}`}>
                  <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold ${guide.type === "checklist" ? "bg-ok/15 text-ok" : "bg-brand text-white ring-4 ring-panel"}`}>
                    {guide.type === "checklist" ? <Check size={13} aria-hidden="true" /> : index + 1}
                  </span>
                  <span className={guide.type === "timeline" ? "rounded-xl border border-line/70 bg-panel px-3.5 py-2.5 shadow-sm" : "font-medium"}>{item}</span>
                </li>
              ))}
            </ol>
            </div>
          </section>
        );
      })}

      {metrics.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-label="Key figures">
          {metrics.map((metric) => (
            <StatTile
              key={metric.metric_id}
              label={metric.label}
              value={formatValue(Number(metric.value), metric.unit)}
              tone="brand"
              icon={Hash}
            />
          ))}
        </div>
      )}

      {sections.length >= 2 && (
        <section className="rounded-2xl border border-line bg-panel p-4">
          <h3 className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.12em] text-muted">
            <Sparkles size={15} className="text-brand" aria-hidden="true" />
            Full-picture coverage
          </h3>
          <div className="mt-3 flex flex-wrap gap-2">
            {sections.map((section, index) => (
              <span key={`${section}-${index}`} className="rounded-full border border-brand/15 bg-brand/5 px-3 py-1.5 text-xs font-medium text-ink">
                {section}
              </span>
            ))}
          </div>
        </section>
      )}

      {charts.map((chart) => {
        const data = chart.categories.map((category, categoryIndex) => ({
          category,
          ...Object.fromEntries(
            chart.series.map((series) => [series.name, Number(series.values[categoryIndex])]),
          ),
        }));
        const accessibleSummary = chart.accessible_summary || chart.series
          .map((series) => `${series.name}: ${series.values.map((value, index) => `${chart.categories[index]} ${formatPresentationValue(Number(value), chart)}`).join(", ")}`)
          .join(". ");
        // A donut's slices already carry their own direct % labels and a
        // legend — a per-series metric strip on top would just repeat the
        // same numbers in a second form, so it's skipped for that type.
        const metrics = chart.type === "donut" ? [] : chart.series.map((series) => {
          const first = Number(series.values[0]);
          const latest = Number(series.values.at(-1));
          const total = series.values.reduce((sum, value) => sum + Number(value), 0);
          // Percentage change is meaningful across time, not across unrelated
          // bar categories such as departments or account balances.
          const change = (chart.type === "line" || chart.type === "area") && first !== 0
            ? ((latest - first) / Math.abs(first)) * 100
            : null;
          return { name: series.name, value: chart.type === "line" || chart.type === "area" ? total : latest, change };
        });

        return (
          <figure key={chart.chart_id} className="min-w-0 overflow-hidden rounded-2xl border border-line bg-panel shadow-[0_12px_40px_rgba(16,24,40,.08)] fullscreen:h-screen fullscreen:overflow-auto fullscreen:rounded-none fullscreen:p-6">
            <div className="border-b border-line bg-[radial-gradient(circle_at_top_right,var(--soft),transparent_60%)] p-4 sm:p-5">
              <figcaption className="flex items-center justify-between gap-3 text-xs font-bold uppercase tracking-[0.12em] text-muted">
                <span>{chart.title}</span>
                <span className="rounded-full border border-brand/15 bg-brand/5 px-2.5 py-1 text-[9px] text-brand">Validated data</span>
              </figcaption>
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                <p className="text-[11px] text-muted">
                  {chart.x_axis_label || "Category"}{chart.y_axis_label ? ` · Values in ${chart.y_axis_label}` : ""}
                </p>
                <ChartActions chart={chart} />
              </div>
              <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
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
                        <span className="text-lg font-bold tracking-tight text-ink">{formatPresentationValue(metric.value, chart)}</span>
                        {metric.change !== null && (
                          <span className={`inline-flex items-center text-[10px] font-semibold ${rising ? "text-ok" : "text-bad"}`}>
                            <TrendIcon size={12} aria-hidden="true" />{Math.abs(metric.change).toFixed(1)}%
                          </span>
                        )}
                      </div>
                      <p className="mt-0.5 text-[10px] text-muted">{chart.type === "line" || chart.type === "area" ? `Total · ${chart.categories.length} periods` : `Latest · ${chart.categories.at(-1)}`}</p>
                    </div>
                  );
                })}
              </div>
            </div>
            <div
              data-chart-canvas
              className="w-full overflow-x-auto p-3 sm:p-4"
              role="img"
              aria-label={`${chart.title}. ${accessibleSummary}`}
            >
              <div
                className="h-[300px]"
                style={{ minWidth: chart.type === "donut" ? 420 : Math.max(480, chart.categories.length * 74) }}
              >
              <ResponsiveContainer width="100%" height="100%">
                {chart.type === "line" ? (
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
                    tickFormatter={(value) => formatPresentationValue(Number(value), chart, true)}
                    width={68}
                  />
                  <Tooltip
                    contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 8, fontSize: 12 }}
                    formatter={(value, name) => [formatPresentationValue(Number(value), chart), String(name)]}
                  />
                  {chart.series.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
                  {chart.series.map((series, index) => (
                    <Line
                      key={series.name}
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
                    tickFormatter={(value) => formatPresentationValue(Number(value), chart, true)}
                    width={68}
                  />
                  <Tooltip
                    contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 8, fontSize: 12 }}
                    formatter={(value, name) => [formatPresentationValue(Number(value), chart), String(name)]}
                  />
                  {/* A single series is the only shape this branch renders
                      (area is picked only for a one-series temporal table —
                      see presentation.py) so no legend is needed. */}
                  <Area
                    dataKey={chart.series[0]?.name}
                    type="monotone"
                    stroke={SERIES_COLORS[0]}
                    fill={SERIES_COLORS[0]}
                    fillOpacity={0.18}
                    strokeWidth={2.5}
                    dot={{ r: 3, fill: SERIES_COLORS[0] }}
                    activeDot={{ r: 5 }}
                  />
                </AreaChart>
                ) : chart.type === "donut" ? (
                <PieChart>
                  <Tooltip
                    contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 8, fontSize: 12 }}
                    formatter={(value, name) => [formatPresentationValue(Number(value), chart), String(name)]}
                  />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Pie
                    data={data}
                    dataKey={chart.series[0]?.name}
                    nameKey="category"
                    innerRadius="55%"
                    outerRadius="80%"
                    paddingAngle={2}
                    // Direct % labels are legible here specifically because
                    // slice count is capped at 6 (see _cap_donut_slices) —
                    // this would be illegible clutter on an uncapped pie.
                    label={({ percent }) => `${((percent ?? 0) * 100).toFixed(0)}%`}
                    labelLine={false}
                  >
                    {chart.categories.map((category, index) => (
                      <Cell key={category} fill={SERIES_COLORS[index % SERIES_COLORS.length]} />
                    ))}
                  </Pie>
                </PieChart>
                ) : (
                <BarChart data={data} margin={{ top: 10, right: 12, left: 4, bottom: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" vertical={false} />
                  <XAxis dataKey="category" stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 11 }} interval={0} height={42} />
                  <YAxis stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={(value) => formatPresentationValue(Number(value), chart, true)} width={68} />
                  <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 12, fontSize: 12 }} formatter={(value, name) => [formatPresentationValue(Number(value), chart), String(name)]} />
                  {chart.series.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
                  {chart.series.map((series, index) => <Bar key={series.name} dataKey={series.name} fill={SERIES_COLORS[index % SERIES_COLORS.length]} radius={[7, 7, 2, 2]} maxBarSize={52} />)}
                </BarChart>
                )}
              </ResponsiveContainer>
              </div>
            </div>
            <details className="border-t border-line px-4 py-3 text-xs text-ink">
              <summary className="cursor-pointer font-medium text-muted transition hover:text-brand">View accessible data table</summary>
              <div className="mt-3 overflow-x-auto rounded-lg border border-line">
                <table className="w-full border-collapse text-xs">
                  <caption className="sr-only">{chart.title} data</caption>
                  <thead className="bg-soft">
                    <tr>
                      <th scope="col" className="px-3 py-2 text-left font-semibold">{chart.x_axis_label || "Label"}</th>
                      {chart.series.map((series) => <th key={series.name} scope="col" className="px-3 py-2 text-right font-semibold">{series.name}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {chart.categories.map((category, index) => (
                      <tr key={`${category}-${index}`} className="border-t border-line/60">
                        <th scope="row" className="whitespace-nowrap px-3 py-2 text-left font-medium">{category}</th>
                        {chart.series.map((series) => (
                          <td key={series.name} className="whitespace-nowrap px-3 py-2 text-right tabular-nums">
                            {formatPresentationValue(Number(series.values[index]), chart)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
            <p className="border-t border-line px-4 py-3 text-[11px] leading-4 text-muted">
              Visualized from the validated table in the answer above; the table remains the textual source of truth.
            </p>
          </figure>
        );
      })}

      {followUps.length > 0 && (
        <section className="border-t border-line/70 pt-4" aria-label="Suggested follow-up questions">
          <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-muted">Explore further</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {followUps.map((question) => (
              <button
                key={question}
                type="button"
                onClick={() => onFollowUp?.(question)}
                disabled={!onFollowUp}
                className="inline-flex items-center gap-1.5 rounded-full border border-line bg-panel px-3 py-2 text-left text-xs font-medium text-ink transition hover:border-brand/40 hover:bg-brand/5 disabled:cursor-default"
              >
                {question}
                <ArrowRight size={13} className="shrink-0 text-brand" aria-hidden="true" />
              </button>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
