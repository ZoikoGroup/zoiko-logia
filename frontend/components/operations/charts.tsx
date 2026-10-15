"use client";

import {
  CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { cssVar } from "@/lib/css-var";
import { chartPalette } from "@/components/visualization/charts/palette";
import type { AlertSeverity, StatusOverview } from "@/lib/api";

type Hour = StatusOverview["hourly"][number];

function useTheme() {
  return {
    ink: cssVar("--ink", "#151922"), muted: cssVar("--muted", "#637083"),
    line: cssVar("--line", "#d8dde5"), panel: cssVar("--panel", "#ffffff"),
    bad: cssVar("--bad", "#b42318"), palette: chartPalette(),
  };
}

const hourLabel = (iso: string) => `${new Date(iso).toISOString().slice(11, 13)}:00`;

function tooltip(t: ReturnType<typeof useTheme>, unit: string) {
  return {
    contentStyle: { background: t.panel, border: `1px solid ${t.line}`, color: t.ink, fontSize: 12, borderRadius: 8 },
    labelStyle: { color: t.ink, fontWeight: 600 },
    labelFormatter: (label: unknown) => `${hourLabel(String(label))} UTC`,
    formatter: (value: unknown) => (typeof value === "number" ? `${value.toLocaleString()}${unit}` : "No samples"),
  };
}

/** Hourly share of health checks that passed, against the objective. */
export function AvailabilityChart({ hours, objective }: { hours: Hour[]; objective: number }) {
  const t = useTheme();
  const values = hours.map((h) => h.availability).filter((v): v is number => v !== null);
  const min = values.length ? Math.min(objective, ...values) : objective;
  const lower = Math.max(0, Math.floor((min - 0.5) * 10) / 10);
  return (
    <ResponsiveContainer width="100%" height={180}>
      <LineChart data={hours} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
        <CartesianGrid stroke={t.line} strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="hour" tickFormatter={hourLabel} interval={5} tick={{ fill: t.muted, fontSize: 11 }} stroke={t.line} />
        <YAxis domain={[lower, 100]} tickFormatter={(v) => `${v}%`} tick={{ fill: t.muted, fontSize: 11 }} stroke={t.line} width={52} />
        <ReferenceLine y={objective} stroke={t.muted} strokeDasharray="4 4"
          label={{ value: `Objective ${objective}%`, fill: t.muted, fontSize: 10, position: "insideBottomRight" }} />
        <Tooltip {...tooltip(t, "%")} />
        <Line type="monotone" dataKey="availability" name="Availability" stroke={t.palette[0]} strokeWidth={2}
          dot={{ r: 3, fill: t.palette[0], strokeWidth: 0 }} activeDot={{ r: 5 }} connectNulls={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

/** Hourly API latency from real request timings: typical (p50) and slow (p95). */
export function LatencyChart({ hours }: { hours: Hour[] }) {
  const t = useTheme();
  return (
    <ResponsiveContainer width="100%" height={180}>
      <LineChart data={hours} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
        <CartesianGrid stroke={t.line} strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="hour" tickFormatter={hourLabel} interval={5} tick={{ fill: t.muted, fontSize: 11 }} stroke={t.line} />
        <YAxis tickFormatter={(v) => `${v}`} tick={{ fill: t.muted, fontSize: 11 }} stroke={t.line} width={44} />
        <Tooltip {...tooltip(t, " ms")} />
        <Legend verticalAlign="top" align="right" height={22} iconType="plainline" wrapperStyle={{ fontSize: 11, color: t.muted }} />
        <Line type="monotone" dataKey="p50" name="p50" stroke={t.palette[0]} strokeWidth={2} dot={false} activeDot={{ r: 5 }}
          connectNulls={false} isAnimationActive={false} />
        <Line type="monotone" dataKey="p95" name="p95" stroke={t.palette[1]} strokeWidth={2} dot={false} activeDot={{ r: 5 }}
          connectNulls={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export const SEVERITY_COLOR: Record<AlertSeverity, string> = {
  Critical: "var(--bad)", High: "var(--accent)", Medium: "var(--info)", Low: "var(--ok)",
};

/** Active alerts by severity; status colours always paired with a label. */
export function SeverityDonut({ counts }: { counts: Record<AlertSeverity, number> }) {
  const t = useTheme();
  const rows = (Object.keys(SEVERITY_COLOR) as AlertSeverity[]).map((s) => ({ name: s, value: counts[s] ?? 0 }));
  const total = rows.reduce((n, r) => n + r.value, 0);
  const resolved: Record<AlertSeverity, string> = {
    Critical: cssVar("--bad", "#b42318"), High: cssVar("--accent", "#e8771e"),
    Medium: cssVar("--info", "#295ea7"), Low: cssVar("--ok", "#1f7a4d"),
  };
  return (
    <div className="flex flex-wrap items-center gap-6">
      <div className="relative h-40 w-40" role="img" aria-label={`${total} active alerts by severity`}>
        {total > 0 ? (
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={rows.filter((r) => r.value > 0)} dataKey="value" nameKey="name" innerRadius={48} outerRadius={70}
                paddingAngle={2} stroke={t.panel} strokeWidth={2} isAnimationActive={false}>
                {rows.filter((r) => r.value > 0).map((r) => <Cell key={r.name} fill={resolved[r.name]} />)}
              </Pie>
              <Tooltip contentStyle={{ background: t.panel, border: `1px solid ${t.line}`, color: t.ink, fontSize: 12, borderRadius: 8 }} />
            </PieChart>
          </ResponsiveContainer>
        ) : <div className="h-full w-full rounded-full border-[14px] border-soft" />}
        <span className="absolute inset-0 grid place-items-center text-3xl font-extrabold text-ink">{total}</span>
      </div>
      <ul className="min-w-40 flex-1 space-y-2 text-sm">
        {rows.map((r) => (
          <li key={r.name} className="flex items-center justify-between gap-3">
            <span className="flex items-center gap-2 text-ink">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: SEVERITY_COLOR[r.name] }} />{r.name}
            </span>
            <span className="font-bold text-ink">{r.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
