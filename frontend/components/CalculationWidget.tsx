"use client";

import { useEffect, useRef, useState } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { recomputeCalculation, getAuthToken, ApiError, type CalculationWidget as CalculationWidgetData } from "@/lib/api";

// Governed calculation architecture — interactive rendering (2026-07-23,
// backend/docs/calculation_architecture.md). Every recompute on a slider
// change calls the backend's /calculations/recompute endpoint rather than
// reimplementing the formula's math here — one verified source of truth
// for the number, the same principle the whole calculation domain is built
// around. Debounced so a fast drag doesn't fire a request per pixel.
const RECOMPUTE_DEBOUNCE_MS = 300;

function formatNumber(raw: string, unit: string): string {
  const value = Number(raw);
  if (Number.isNaN(value)) return raw;
  if (unit === "USD" || unit === "annual_amount" || unit === "monthly_amount") {
    return value.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 2 });
  }
  if (unit === "percent") return `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}%`;
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export function CalculationWidget({ data }: { data: CalculationWidgetData }) {
  const [widget, setWidget] = useState<CalculationWidgetData>(data);
  const [sliderValues, setSliderValues] = useState<Record<string, string>>(
    () => Object.fromEntries(data.inputs.map((input) => [input.name, input.value])),
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  return (
    <div className="mt-4 min-w-0 rounded-2xl border border-line bg-panel shadow-[0_1px_2px_rgba(16,24,40,.04)]">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <span className="text-xs font-bold uppercase tracking-[0.12em] text-muted">{widget.formula_name}</span>
        {loading && <span className="text-[11px] text-muted">Recomputing…</span>}
      </div>

      <div className="grid gap-5 p-4 sm:grid-cols-2">
        <div className="min-w-0">
          <div className="rounded-lg bg-soft px-3 py-2 text-center font-mono text-sm text-ink">
            {widget.formula_display}
          </div>

          <div className="mt-4 space-y-4">
            {widget.inputs.map((input) => (
              <div key={input.name}>
                <div className="flex items-center justify-between text-xs">
                  <span className="font-medium text-ink">{input.label}</span>
                  <span className="font-mono text-muted">{formatNumber(sliderValues[input.name], input.unit)}</span>
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

          <div className="mt-4 rounded-lg border border-line/70 p-3">
            <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-muted">{widget.output_label}</span>
            <p className="mt-0.5 text-lg font-bold text-ink">{formatNumber(widget.output_value, widget.output_unit)}</p>
          </div>

          {error && <p className="mt-2 text-xs text-warn">{error}</p>}
        </div>

        <div className="min-w-0">
          <p className="mb-1.5 text-xs font-semibold text-ink">{widget.chart_label}</p>
          <div className="h-[220px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={widget.chart_points.map((p) => ({ x: Number(p.x), y: Number(p.y) }))}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
                <XAxis
                  dataKey="x"
                  stroke="var(--muted)"
                  tick={{ fill: "var(--muted)", fontSize: 11 }}
                  label={{ value: widget.chart_x_label, position: "insideBottom", offset: -5, fill: "var(--muted)", fontSize: 11 }}
                />
                <YAxis
                  stroke="var(--muted)"
                  tick={{ fill: "var(--muted)", fontSize: 11 }}
                  width={70}
                  label={{ value: widget.chart_y_label, angle: -90, position: "insideLeft", fill: "var(--muted)", fontSize: 11 }}
                />
                <Tooltip
                  contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 8, fontSize: 12 }}
                  labelStyle={{ color: "var(--muted)" }}
                  formatter={(value) => [
                    Number(value).toLocaleString(undefined, { style: "currency", currency: "USD" }),
                    widget.chart_y_label,
                  ]}
                />
                <Line type="monotone" dataKey="y" stroke="var(--brand)" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="border-t border-line px-4 py-2.5 text-[11px] leading-4 text-muted">
        {widget.methodology_reference}
      </div>
    </div>
  );
}
