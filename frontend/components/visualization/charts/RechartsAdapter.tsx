"use client";

import {
  ResponsiveContainer, LineChart, Line, BarChart, Bar, AreaChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip,
} from "recharts";
import { cssVar } from "@/lib/css-var";
import type { VisualizationSpec } from "@/lib/api";
import { chartPalette } from "./palette";

/**
 * Recharts composition for LINE/BAR/HISTOGRAM (see engineRouting.ts) — a
 * plain switch over viz.type/variant, each branch a hand-tuned composition
 * of Recharts primitives, themed via the SAME CSS custom properties as the
 * rest of the app (never hardcoded hex) so it inherits light/dark
 * automatically — Recharts renders to SVG, so `var(--x)` even works
 * directly in most props; cssVar() is only needed where Recharts wants a
 * plain string (chart fill/stroke props don't accept CSS var() in every
 * browser/SVG context reliably, so this reads the resolved value instead).
 *
 * A single series never gets a legend box — the title already names it
 * (dataviz skill's own accessibility rule); this pipeline never sends more
 * than one series per spec today.
 */
export function RechartsChart({ viz }: { viz: VisualizationSpec }) {
  const ink = cssVar("--ink", "#17211f");
  const muted = cssVar("--muted", "#667673");
  const line = cssVar("--line", "#eef3f2");
  const panel = cssVar("--panel", "#ffffff");
  const [color] = chartPalette();

  const rows = viz.data.map((p) => ({ category: p.x, value: p.y }));
  const seriesName = viz.title ?? "value";
  const isBarFamily = viz.type === "BAR" || viz.type === "HISTOGRAM";
  const isArea = viz.variant === "AREA_CHART";
  const isStep = viz.variant === "STEP_LINE_CHART";
  const showMarkers = viz.variant === "LINE_WITH_MARKERS";

  // BAR keeps a zero baseline — bar LENGTH is the visual comparison, so
  // forcing zero is the honest convention there. A LINE's slope is what's
  // being read, not its distance from zero, so a real series that never
  // goes near zero (e.g. India CPI ~192-197) would otherwise render as a
  // near-flat sliver pinned to the top of a 0-scaled axis — technically
  // correct but functionally unreadable. Pad 10% beyond the real min/max
  // instead of fabricating a value: still exactly the real range, just not
  // artificially anchored to zero.
  const values = rows.map((r) => r.value);
  const dataMin = values.length ? Math.min(...values) : 0;
  const dataMax = values.length ? Math.max(...values) : 0;
  const pad = (dataMax - dataMin) * 0.1 || Math.abs(dataMax) * 0.1 || 1;
  const lineDomain: [number, number] = [dataMin - pad, dataMax + pad];

  const axisProps = { tick: { fill: muted, fontSize: 11 }, stroke: line };
  const tooltipStyle = {
    contentStyle: { background: panel, border: `1px solid ${line}`, color: ink, fontSize: 12, borderRadius: 8 },
    labelStyle: { color: ink, fontWeight: 600 },
    cursor: { stroke: line },
  };
  const rotateLabels = rows.length > 4;

  if (isBarFamily) {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 8, right: 16, bottom: rotateLabels ? 24 : 8, left: 0 }}>
          <CartesianGrid stroke={line} strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="category" {...axisProps} interval={0}
            angle={rotateLabels ? -35 : 0} textAnchor={rotateLabels ? "end" : "middle"}
            height={rotateLabels ? 56 : 30}
          />
          <YAxis {...axisProps} />
          <Tooltip {...tooltipStyle} />
          <Bar dataKey="value" name={seriesName} fill={color} radius={[4, 4, 0, 0]} maxBarSize={54} />
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (isArea) {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={rows} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid stroke={line} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="category" {...axisProps} />
          <YAxis {...axisProps} domain={lineDomain} />
          <Tooltip {...tooltipStyle} />
          <Area type="monotone" dataKey="value" name={seriesName} stroke={color} fill={color} fillOpacity={0.2} strokeWidth={2.5} />
        </AreaChart>
      </ResponsiveContainer>
    );
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
        <CartesianGrid stroke={line} strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="category" {...axisProps} />
        <YAxis {...axisProps} domain={lineDomain} />
        <Tooltip {...tooltipStyle} />
        <Line
          type={isStep ? "stepAfter" : "monotone"}
          dataKey="value"
          name={seriesName}
          stroke={color}
          strokeWidth={2.5}
          dot={showMarkers || rows.length <= 16 ? { r: 4, fill: color, strokeWidth: 0 } : false}
          activeDot={{ r: 5 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
