"use client";

import { useEffect, useRef, useState } from "react";
import ReactECharts from "echarts-for-react";
import { BarChart, Bar, Cell, LineChart, Line, PieChart, Pie, RadialBarChart, RadialBar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { recomputeCalculation, getAuthToken, ApiError, type CalculationWidget as CalculationWidgetData } from "@/lib/api";
import { VisualizationActions } from "@/components/VisualizationActions";
import { exportEChartPng } from "@/lib/export/exportEChartPng";
import { exportSvgElementPng } from "@/lib/export/exportSvgElementPng";
import { exportChartCsv } from "@/lib/export/exportChartCsv";
import { saveVisualization } from "@/lib/export/saveVisualization";

// Only these chart_types actually render through ReactECharts (see
// renderChart() below — "bar" uses Recharts), so PNG export (which reads the
// live ECharts instance) is only offered for these. CSV/save don't depend
// on the renderer and stay available for all.
const ECHARTS_CHART_TYPES = ["gauge", "donut", "stacked_bar", "line", "bullet", "treemap", "sankey", "kpi", "waterfall"];

// Governed calculation architecture — interactive rendering (2026-07-23,
// backend/docs/calculation_architecture.md). Every recompute on a slider
// change calls the backend's /calculations/recompute endpoint rather than
// reimplementing the formula's math here — one verified source of truth
// for the number, the same principle the whole calculation domain is built
// around. Debounced so a fast drag doesn't fire a request per pixel.
const RECOMPUTE_DEBOUNCE_MS = 300;

/** ECharts has no built-in waterfall type — the standard trick is a stacked
 * bar chart with an invisible "base" series absorbing the running total, so
 * each visible segment floats at the right height. Formerly rendered via
 * Plotly (1.36MB gzip) for this one chart_type; every input point except the
 * first (absolute start) and last (total, whose y is the real computed
 * output — see widget.py's _comparison_widget) is a relative delta already
 * negated by the backend to represent a subtraction.
 */
export function buildWaterfallOption(chartData: { x: string; y: number }[]) {
  const base: number[] = [];
  const rise: number[] = [];
  const fall: number[] = [];
  const startOrTotal: number[] = [];
  let running = 0;
  chartData.forEach((point, index) => {
    base.push(0); rise.push(0); fall.push(0); startOrTotal.push(0);
    if (index === 0 || index === chartData.length - 1) {
      running = point.y;
      startOrTotal[index] = point.y;
      return;
    }
    const delta = -point.y;
    if (delta >= 0) {
      base[index] = running;
      rise[index] = delta;
    } else {
      base[index] = running + delta;
      fall[index] = -delta;
    }
    running += delta;
  });
  return {
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    xAxis: { type: "category", data: chartData.map((point) => point.x), axisLabel: { fontSize: 11 } },
    yAxis: { type: "value" },
    series: [
      { name: "Base", type: "bar", stack: "waterfall", itemStyle: { color: "transparent" }, emphasis: { disabled: true }, silent: true, data: base },
      { name: "Start / total", type: "bar", stack: "waterfall", itemStyle: { color: "#65d6cf" }, data: startOrTotal },
      { name: "Increase", type: "bar", stack: "waterfall", itemStyle: { color: "#7c8cff" }, data: rise },
      { name: "Decrease", type: "bar", stack: "waterfall", itemStyle: { color: "#ef7f8d" }, data: fall },
    ],
  };
}

function formatNumber(raw: string, unit: string): string {
  const value = Number(raw);
  if (Number.isNaN(value)) return raw;
  if (unit === "USD" || unit === "annual_amount" || unit === "monthly_amount") {
    return value.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 2 });
  }
  if (unit === "percent") return `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}%`;
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export function CalculationWidget({
  data, queryId, sourceReferences = [],
}: {
  data: CalculationWidgetData;
  queryId?: string;
  sourceReferences?: string[];
}) {
  const [widget, setWidget] = useState<CalculationWidgetData>(data);
  const [sliderValues, setSliderValues] = useState<Record<string, string>>(
    () => Object.fromEntries(data.inputs.map((input) => [input.name, input.value])),
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const echartsRef = useRef<ReactECharts | null>(null);
  const svgChartContainerRef = useRef<HTMLDivElement | null>(null);
  // Rotated after each successful save so a later, deliberate re-save (e.g.
  // after a slider recompute) isn't silently deduped against the old one —
  // reused as-is across retries of the same failed/in-flight attempt.
  const idempotencyKeyRef = useRef(crypto.randomUUID());

  useEffect(() => {
    setWidget(data);
    setSliderValues(Object.fromEntries(data.inputs.map((input) => [input.name, input.value])));
  }, [data]);

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  function scheduleRecompute(nextValues: Record<string, string>) {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      setError("");
      try {
        const inputs = Object.fromEntries(
          widget.inputs.map((input) => [input.name, { value: nextValues[input.name], unit: input.unit }]),
        );
        const recomputed = await recomputeCalculation(getAuthToken(), widget.formula_id, inputs);
        setWidget(recomputed);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Could not recompute — showing the last verified result.");
      } finally {
        setLoading(false);
      }
    }, RECOMPUTE_DEBOUNCE_MS);
  }

  function handleSliderChange(name: string, value: string) {
    const next = { ...sliderValues, [name]: value };
    setSliderValues(next);
    scheduleRecompute(next);
  }

  const chartData = widget.chart_points.map((point) => ({ x: point.x, y: Number(point.y) }));
  const palette = ["var(--brand)", "#67c7c2", "#f4b860", "#8a7cf0"];

  function renderChart() {
    if (ECHARTS_CHART_TYPES.includes(widget.chart_type)) {
      const gaugeValue = Number(widget.output_value);
      const gaugeMax = widget.output_unit === "percent" ? 100 : widget.formula_id.includes("receivables_days") ? Math.max(120, gaugeValue * 1.25) : widget.formula_id.includes("inventory_turnover") ? Math.max(12, gaugeValue * 1.5) : 3;
      const option = widget.chart_type === "gauge" ? {
        series: [{ type: "gauge", startAngle: 205, endAngle: -25, min: 0, max: gaugeMax, progress: { show: true, width: 18 }, axisLine: { lineStyle: { width: 18 } }, axisTick: { show: false }, splitLine: { length: 10 }, pointer: { show: false }, detail: { formatter: widget.output_unit === "percent" ? "{value}%" : "{value}", fontSize: 28, offsetCenter: [0, "20%"] }, data: [{ value: gaugeValue, name: widget.output_label }], title: { offsetCenter: [0, "55%"] } }],
      } : widget.chart_type === "donut" ? {
        tooltip: { trigger: "item" }, legend: { bottom: 0 }, series: [{ type: "pie", radius: ["48%", "72%"], data: chartData.map((point) => ({ name: point.x, value: point.y })), label: { formatter: "{b}\n{d}%" } }],
      } : widget.chart_type === "stacked_bar" ? {
        tooltip: { trigger: "axis" }, legend: { bottom: 0 }, xAxis: { type: "value" }, yAxis: { type: "category", data: ["Current assets", "Liabilities"] }, series: chartData.map((point) => ({ name: point.x, type: "bar", stack: "total", data: point.x === "Current liabilities" ? [0, point.y] : [point.y, 0] })),
      } : widget.chart_type === "bullet" ? {
        tooltip: { trigger: "axis" }, grid: { left: 100, right: 20, top: 25, bottom: 35 }, xAxis: { type: "value" }, yAxis: { type: "category", data: chartData.map((point) => point.x) }, series: [{ type: "bar", data: chartData.map((point) => point.y), itemStyle: { color: "#67c7c2", borderRadius: [0, 6, 6, 0] }, label: { show: true, position: "right" } }],
      } : widget.chart_type === "treemap" ? {
        tooltip: { formatter: "{b}: {c}" }, series: [{ type: "treemap", roam: false, breadcrumb: { show: false }, label: { show: true, formatter: "{b}\n{c}" }, data: chartData.map((point) => ({ name: point.x, value: point.y })) }],
      } : widget.chart_type === "sankey" ? {
        tooltip: { trigger: "item" }, series: [{ type: "sankey", emphasis: { focus: "adjacency" }, lineStyle: { color: "gradient", curveness: 0.5 }, data: chartData.map((point) => ({ name: point.x })), links: chartData.length >= 3 ? [{ source: chartData[0].x, target: chartData[1].x, value: chartData[1].y }, { source: chartData[0].x, target: chartData[2].x, value: chartData[2].y }] : [] }],
      } : widget.chart_type === "kpi" ? {
        graphic: [{ type: "text", left: "center", top: "middle", style: { text: formatNumber(widget.output_value, widget.output_unit), fontSize: 38, fontWeight: 700, fill: "#65d6cf" } }],
      } : widget.chart_type === "waterfall" ? buildWaterfallOption(chartData) : {
        tooltip: { trigger: "axis" }, xAxis: { type: "category", data: chartData.map((point) => point.x) }, yAxis: { type: "value" }, series: [{ type: "line", smooth: true, data: chartData.map((point) => point.y), areaStyle: {} }],
      };
      return <ReactECharts
        ref={echartsRef}
        option={{
          color: ["#65d6cf", "#7c8cff", "#f4b860", "#ef7f8d"],
          backgroundColor: "transparent",
          textStyle: { color: "#94a3b8", fontFamily: "inherit" },
          animationDuration: 450,
          ...option,
        }}
        style={{ height: "340px", width: "100%" }}
        notMerge
        opts={{ renderer: "canvas" }}
      />;
    }
    if (widget.chart_type === "donut") {
      return <PieChart>
        <Pie data={chartData} dataKey="y" nameKey="x" innerRadius={48} outerRadius={82} paddingAngle={2}>
          {chartData.map((entry, index) => <Cell key={entry.x} fill={palette[index % palette.length]} />)}
        </Pie>
        <Tooltip formatter={(value) => Number(value).toLocaleString(undefined, { style: "currency", currency: "USD" })} />
      </PieChart>;
    }
    if (widget.chart_type === "gauge") {
      const ratio = Number(widget.output_value);
      const gaugeData = [{ name: "Current ratio", value: Math.min(Math.max(ratio / 3 * 100, 0), 100), actual: ratio }];
      return <RadialBarChart innerRadius="62%" outerRadius="100%" data={gaugeData} startAngle={180} endAngle={0} barSize={24}>
        <RadialBar dataKey="value" fill="var(--brand)" cornerRadius={12} background />
        <Tooltip formatter={(_, __, item) => [`${item.payload.actual.toFixed(2)}:1`, "Current ratio"]} />
        <text x="50%" y="62%" textAnchor="middle" fill="var(--ink)" fontSize="24" fontWeight="700">{ratio.toFixed(2)}:1</text>
      </RadialBarChart>;
    }
    if (widget.chart_type === "stacked_bar") {
      const quick = chartData.find((point) => point.x === "Quick assets")?.y ?? 0;
      const inventory = chartData.find((point) => point.x === "Inventory")?.y ?? 0;
      const liabilities = chartData.find((point) => point.x === "Current liabilities")?.y ?? 0;
      const stacked = [
        { x: "Current assets", quick, inventory, liabilities: 0 },
        { x: "Liabilities", quick: 0, inventory: 0, liabilities },
      ];
      return <BarChart data={stacked} layout="vertical">
        <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
        <XAxis type="number" tick={{ fill: "var(--muted)", fontSize: 11 }} />
        <YAxis type="category" dataKey="x" width={90} tick={{ fill: "var(--muted)", fontSize: 11 }} />
        <Tooltip formatter={(value) => Number(value).toLocaleString(undefined, { style: "currency", currency: "USD" })} />
        <Bar dataKey="quick" name="Quick assets" stackId="a" fill="var(--brand)" isAnimationActive={false} />
        <Bar dataKey="inventory" name="Inventory" stackId="a" fill="#f4b860" isAnimationActive={false} />
        <Bar dataKey="liabilities" name="Current liabilities" stackId="a" fill="#67c7c2" isAnimationActive={false} />
      </BarChart>;
    }
    if (widget.chart_type === "bar") {
      return <BarChart data={chartData}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
        <XAxis dataKey="x" stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 10 }} interval={0} />
        <YAxis stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 11 }} width={70} />
        <Tooltip formatter={(value) => [Number(value).toLocaleString(undefined, { style: "currency", currency: "USD" }), "Amount"]} />
        <Bar dataKey="y" radius={[5, 5, 0, 0]} isAnimationActive={false}>
          {chartData.map((entry, index) => <Cell key={entry.x} fill={palette[index % palette.length]} />)}
        </Bar>
      </BarChart>;
    }
    return <LineChart data={chartData}>
      <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
      <XAxis dataKey="x" stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 11 }} />
      <YAxis stroke="var(--muted)" tick={{ fill: "var(--muted)", fontSize: 11 }} width={70} />
      <Tooltip formatter={(value) => [Number(value).toLocaleString(undefined, { style: "currency", currency: "USD" }), widget.chart_y_label]} />
      <Line type="monotone" dataKey="y" stroke="var(--brand)" strokeWidth={2} dot={false} />
    </LineChart>;
  }

  return (
    <section className="mt-5 min-w-0 overflow-hidden rounded-3xl border border-line bg-panel shadow-[0_18px_55px_rgba(16,24,40,.12)]">
      <div className="flex items-center justify-between bg-[linear-gradient(120deg,var(--soft),var(--panel))] px-5 py-4">
        <div>
          <span className="text-[10px] font-bold uppercase tracking-[0.18em] text-brand">Governed calculation</span>
          <h3 className="mt-1 text-base font-bold text-ink">{widget.formula_name}</h3>
        </div>
        {loading && <span className="text-[11px] text-muted">Recomputing…</span>}
      </div>

      <div className="border-y border-line px-5 py-4">
        <div className="grid items-center gap-4 md:grid-cols-[1fr_auto]">
          <div className="rounded-xl bg-soft px-4 py-3 text-center font-mono text-sm text-ink">
            {widget.formula_display}
          </div>
          <div className="min-w-48 rounded-xl border border-brand/20 bg-brand/5 px-5 py-3 text-center md:text-left">
            <span className="text-[9px] font-bold uppercase tracking-[0.16em] text-muted">{widget.output_label}</span>
            <p className="mt-1 text-2xl font-extrabold tracking-tight text-ink">{formatNumber(widget.output_value, widget.output_unit)}</p>
          </div>
        </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {widget.inputs.map((input) => (
              <div key={input.name} className="rounded-xl border border-line/70 bg-soft/40 p-3">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-medium text-ink">{input.label}</span>
                  <span className="font-mono font-semibold text-brand">{formatNumber(sliderValues[input.name], input.unit)}</span>
                </div>
                <input
                  type="range"
                  min={input.min}
                  max={input.max}
                  step={input.step}
                  value={sliderValues[input.name]}
                  onChange={(e) => handleSliderChange(input.name, e.target.value)}
                  className="mt-1.5 w-full accent-brand"
                  aria-label={input.label}
                />
              </div>
            ))}
          </div>

          {error && <p className="mt-2 text-xs text-warn">{error}</p>}
      </div>

      <div className="min-w-0 bg-[radial-gradient(circle_at_top,var(--soft),transparent_70%)] px-4 py-5 sm:px-6">
          <div className="mb-3 flex items-center justify-between gap-3">
            <p className="text-xs font-bold uppercase tracking-[0.12em] text-muted">{widget.chart_label}</p>
            <span className="rounded-full border border-line bg-panel px-2.5 py-1 text-[9px] font-bold uppercase tracking-wider text-muted">{widget.chart_type.replace("_", " ")}</span>
          </div>
          <div ref={svgChartContainerRef} className="h-[340px] w-full rounded-2xl border border-line/70 bg-panel/70 p-2 sm:p-4">
            {widget.chart_type === "bar" ? <ResponsiveContainer width="100%" height="100%">{renderChart()}</ResponsiveContainer> : renderChart()}
          </div>
          <div className="mt-3">
            <VisualizationActions
              onDownloadPng={
                ECHARTS_CHART_TYPES.includes(widget.chart_type)
                  ? () => exportEChartPng(echartsRef, widget.chart_label || widget.formula_name)
                  : () => exportSvgElementPng(svgChartContainerRef.current, widget.chart_label || widget.formula_name)
              }
              onExportCsv={() => exportChartCsv(widget)}
              onSave={
                queryId
                  ? async () => {
                      const ok = await saveVisualization(
                        {
                          query_id: queryId,
                          visualization_type: "chart",
                          title: widget.formula_name,
                          summary: widget.formula_display,
                          payload: widget,
                          source_references: sourceReferences,
                        },
                        idempotencyKeyRef.current,
                      );
                      if (ok) idempotencyKeyRef.current = crypto.randomUUID();
                      return ok;
                    }
                  : undefined
              }
            />
          </div>
        </div>

      <div className="border-t border-line px-5 py-3 text-[11px] leading-4 text-muted">
        {widget.methodology_reference}
      </div>
    </section>
  );
}
