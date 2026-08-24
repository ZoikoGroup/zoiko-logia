"use client";

import {
  ResponsiveContainer, LineChart, Line, BarChart, Bar, AreaChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, LabelList, ReferenceLine, Cell,
} from "recharts";
import { cssVar } from "@/lib/css-var";
import type { VisualizationSpec } from "@/lib/api";
import { chartPalette } from "./palette";

/**
 * Recharts composition for LINE/BAR/HISTOGRAM/GROUPED_BAR (see
 * engineRouting.ts) — a plain switch over viz.type/variant, each branch a
 * hand-tuned composition of Recharts primitives, themed via the SAME CSS
 * custom properties as the rest of the app (never hardcoded hex) so it
 * inherits light/dark automatically — Recharts renders to SVG, so `var(--x)`
 * even works directly in most props; cssVar() is only needed where Recharts
 * wants a plain string (chart fill/stroke props don't accept CSS var() in
 * every browser/SVG context reliably, so this reads the resolved value
 * instead).
 *
 * A single series never gets a legend box — the title already names it
 * (dataviz skill's own accessibility rule). GROUPED_BAR is the one type that
 * genuinely carries more than one series, and gets a legend accordingly.
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
  const isArea = viz.variant === "AREA_CHART" || viz.variant === "AREA_WITH_MARKERS";
  const isStep = viz.variant === "STEP_LINE_CHART";
  const isSpline = viz.variant === "SPLINE_LINE_CHART";
  const showMarkers = viz.variant === "LINE_WITH_MARKERS";
  const showAreaMarkers = viz.variant === "AREA_WITH_MARKERS";
  const showValueLabels = viz.variant === "VALUE_LABELED_LINE";
  const strokeDasharray = viz.variant === "DASHED_LINE"
    ? "9 6"
    : viz.variant === "DOTTED_LINE"
      ? "2 5"
      : viz.variant === "DASH_DOT_LINE" ? "10 5 2 5" : undefined;

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
  // Recharts' default numeric-axis formatter is a bare String(value) on
  // whatever tick value it internally computes (real domain bounds ± the
  // padding math above) — real computed figures (e.g. a DBnomics percentage
  // change) routinely carry 15-16 significant digits of float noise, which
  // renders as an unreadable, visually-clipped wall of digits. toLocaleString()
  // with no options matches SummaryMetricCards.tsx's own formatting exactly,
  // so the axis and the First/Latest/Total cards above it never disagree.
  const numberTick = (v: number) => v.toLocaleString();
  const tooltipStyle = {
    contentStyle: { background: panel, border: `1px solid ${line}`, color: ink, fontSize: 12, borderRadius: 8 },
    labelStyle: { color: ink, fontWeight: 600 },
    cursor: { stroke: line },
    // Same float-precision issue as the axis ticks (see numberTick above) —
    // the raw hovered value is real computed data, not a clean test number.
    formatter: (value: unknown) => typeof value === "number" ? numberTick(value) : String(value),
  };
  const rotateLabels = rows.length > 4;

  if (viz.type === "LINE" && viz.series.length > 1) {
    const categories = viz.series[0].data.map((point) => point.x);
    const lineRows = categories.map((category, index) => {
      const row: Record<string, string | number> = { category };
      for (const series of viz.series) row[series.name] = series.data[index].y;
      return row;
    });
    const values = viz.series.flatMap((series) => series.data.map((point) => point.y));
    const minimum = Math.min(...values);
    const maximum = Math.max(...values);
    const multiPad = (maximum - minimum) * 0.1 || Math.abs(maximum) * 0.1 || 1;
    const colors = chartPalette();
    return (
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={lineRows} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid stroke={line} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="category" {...axisProps} />
          <YAxis {...axisProps} tickFormatter={numberTick} domain={[minimum - multiPad, maximum + multiPad]} />
          <Tooltip {...tooltipStyle} />
          <Legend wrapperStyle={{ color: muted, fontSize: 12 }} />
          {viz.series.map((series, index) => (
            <Line
              key={series.name}
              type="linear"
              dataKey={series.name}
              name={series.name}
              stroke={colors[index % colors.length]}
              strokeWidth={2.5}
              dot={{ r: 3, strokeWidth: 0 }}
              activeDot={{ r: 5 }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    );
  }

  // GROUPED_BAR/STACKED_BAR (variant) — real, period-aligned series
  // (orchestrator.py's _build_grouped_bar_spec). Merged into one row per
  // shared category (validator.py already guarantees every series carries
  // the SAME category labels), so each <Bar> just reads its own series key.
  if (viz.type === "GROUPED_BAR") {
    const isHorizontal = viz.variant === "STACKED_HORIZONTAL_BAR" || viz.variant === "HUNDRED_PERCENT_STACKED_HORIZONTAL_BAR";
    const isPercent = viz.variant === "HUNDRED_PERCENT_STACKED_BAR" || viz.variant === "HUNDRED_PERCENT_STACKED_HORIZONTAL_BAR";
    const isStacked = viz.variant !== "GROUPED_BAR_CHART";
    const categories = viz.series[0]?.data.map((p) => p.x) ?? [];
    const barRows = categories.map((cat, i) => {
      const row: Record<string, string | number> = { category: cat };
      const total = viz.series.reduce((sum, s) => sum + Math.abs(s.data[i]?.y ?? 0), 0);
      for (const s of viz.series) {
        const value = s.data[i]?.y ?? 0;
        row[s.name] = isPercent && total ? (Math.abs(value) / total) * 100 : value;
      }
      return row;
    });
    const colors = chartPalette();
    return (
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={barRows} layout={isHorizontal ? "vertical" : "horizontal"} margin={{ top: 8, right: 16, bottom: rotateLabels ? 24 : 8, left: 0 }}>
          <CartesianGrid stroke={line} strokeDasharray="3 3" vertical={false} />
          {isHorizontal ? (
            <><XAxis type="number" {...axisProps} tickFormatter={numberTick} domain={isPercent ? [0, 100] : undefined} unit={isPercent ? "%" : undefined} /><YAxis type="category" dataKey="category" {...axisProps} width={72} /></>
          ) : (
            <><XAxis dataKey="category" {...axisProps} interval={0} angle={rotateLabels ? -35 : 0} textAnchor={rotateLabels ? "end" : "middle"} height={rotateLabels ? 56 : 30} /><YAxis {...axisProps} tickFormatter={numberTick} domain={isPercent ? [0, 100] : undefined} unit={isPercent ? "%" : undefined} /></>
          )}
          <Tooltip {...tooltipStyle} />
          <Legend wrapperStyle={{ color: muted, fontSize: 12 }} />
          {viz.series.map((s, i) => (
            <Bar
              key={s.name} dataKey={s.name} name={s.name} fill={colors[i % colors.length]}
              stackId={isStacked ? "stack" : undefined} radius={isStacked ? undefined : [4, 4, 0, 0]} maxBarSize={54}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (viz.variant === "WATERFALL_CHART") {
    const waterfallRows = rows.reduce<{ running: number; values: Array<typeof rows[number] & { range: number[]; delta: number }> }>(
      (result, row, index) => {
        const start = index === 0 ? 0 : result.running;
        const end = index === 0 ? row.value : result.running + row.value;
        return {
          running: end,
          values: [...result.values, { ...row, range: [Math.min(start, end), Math.max(start, end)], delta: row.value }],
        };
      },
      { running: 0, values: [] },
    ).values;
    return (
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={waterfallRows} margin={{ top: 8, right: 16, bottom: rotateLabels ? 24 : 8, left: 0 }}>
          <CartesianGrid stroke={line} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="category" {...axisProps} interval={0} angle={rotateLabels ? -35 : 0} textAnchor={rotateLabels ? "end" : "middle"} height={rotateLabels ? 56 : 30} />
          <YAxis {...axisProps} tickFormatter={numberTick} />
          <Tooltip {...tooltipStyle} formatter={(_value, _name, item) => [numberTick(item.payload.delta), seriesName]} />
          <Bar dataKey="range" name={seriesName}>
            {waterfallRows.map((row, index) => <Cell key={`${row.category}-${index}`} fill={row.delta >= 0 ? color : cssVar("--bad", "#b42318")} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (isBarFamily) {
    const isHorizontal = viz.variant === "HORIZONTAL_BAR" || viz.variant === "DIVERGING_BAR";
    return (
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} layout={isHorizontal ? "vertical" : "horizontal"} margin={{ top: 8, right: 16, bottom: rotateLabels ? 24 : 8, left: 0 }}>
          <CartesianGrid stroke={line} strokeDasharray="3 3" vertical={false} />
          {isHorizontal ? (
            <><XAxis type="number" {...axisProps} tickFormatter={numberTick} /><YAxis type="category" dataKey="category" {...axisProps} width={72} /><ReferenceLine x={0} stroke={muted} /></>
          ) : (
            <><XAxis dataKey="category" {...axisProps} interval={0} angle={rotateLabels ? -35 : 0} textAnchor={rotateLabels ? "end" : "middle"} height={rotateLabels ? 56 : 30} /><YAxis {...axisProps} tickFormatter={numberTick} /></>
          )}
          <Tooltip {...tooltipStyle} />
          <Bar dataKey="value" name={seriesName} fill={color} radius={isHorizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]} maxBarSize={54}>
            {viz.variant === "DIVERGING_BAR" && rows.map((row, index) => <Cell key={`${row.category}-${index}`} fill={row.value >= 0 ? color : cssVar("--bad", "#b42318")} />)}
          </Bar>
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
          <YAxis {...axisProps} tickFormatter={numberTick} domain={lineDomain} />
          <Tooltip {...tooltipStyle} />
          <Area
            type="linear" dataKey="value" name={seriesName} stroke={color}
            fill={color} fillOpacity={0.2} strokeWidth={2.5}
            dot={showAreaMarkers ? { r: 4, fill: color, strokeWidth: 0 } : false}
          />
        </AreaChart>
      </ResponsiveContainer>
    );
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
        <CartesianGrid stroke={line} strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="category" {...axisProps} />
        <YAxis {...axisProps} tickFormatter={numberTick} domain={lineDomain} />
        <Tooltip {...tooltipStyle} />
        <Line
          type={isStep ? "stepAfter" : isSpline ? "monotone" : "linear"}
          dataKey="value"
          name={seriesName}
          stroke={color}
          strokeWidth={2.5}
          strokeDasharray={strokeDasharray}
          dot={showMarkers || showValueLabels ? { r: 4, fill: color, strokeWidth: 0 } : false}
          activeDot={{ r: 5 }}
        >
          {showValueLabels && (
            <LabelList dataKey="value" position="top" fill={ink} fontSize={10} formatter={(value: unknown) => numberTick(Number(value))} />
          )}
        </Line>
      </LineChart>
    </ResponsiveContainer>
  );
}
