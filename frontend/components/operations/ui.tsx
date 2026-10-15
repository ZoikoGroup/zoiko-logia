"use client";

import type { LucideIcon } from "lucide-react";
import { AlertTriangle, CheckCircle2, CircleDot, Loader2, XCircle } from "lucide-react";
import { useState, type ReactNode } from "react";
import { getAuthToken, type GateStatus } from "@/lib/api";

/** Shared pieces of the Operations console pages (Alerts Center, Provider
 * Register, Integrations, Status & Health). */

export function OpsHero({ icon: Icon, eyebrow, title, subtitle, children }: {
  icon: LucideIcon; eyebrow?: string; title: string; subtitle: string; children?: ReactNode;
}) {
  return (
    <section className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-hero to-hero-2 px-5 py-5 text-white shadow-[0_12px_32px_rgba(13,34,64,0.18)] sm:px-7">
      <div aria-hidden className="pointer-events-none absolute -right-16 -top-24 h-72 w-72 rounded-full border border-white/10" />
      <div aria-hidden className="pointer-events-none absolute -right-4 -top-10 h-44 w-44 rounded-full border border-white/10" />
      <div className="relative flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-center gap-4">
          <span className="grid h-14 w-14 shrink-0 place-items-center rounded-xl border-2 border-accent/80 bg-white/5 text-accent">
            <Icon size={26} />
          </span>
          <div className="min-w-0">
            {eyebrow && <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-accent">{eyebrow}</p>}
            <h1 className="text-2xl font-extrabold tracking-tight sm:text-3xl">{title}</h1>
            <p className="mt-1 text-sm text-white/80">{subtitle}</p>
          </div>
        </div>
        {children && <div className="border-l-2 border-accent pl-4 text-sm leading-6 text-white/90 lg:max-w-sm lg:text-right">{children}</div>}
      </div>
    </section>
  );
}

const TILE_TONE = {
  neutral: "bg-info/10 text-info",
  ok: "bg-ok/10 text-ok",
  warn: "bg-accent/10 text-accent-ink",
  bad: "bg-bad/10 text-bad",
  info: "bg-info/10 text-info",
} as const;
export type Tone = keyof typeof TILE_TONE;

export function KpiTile({ icon: Icon, value, label, hint, tone = "neutral", hintTone }: {
  icon: LucideIcon; value: ReactNode; label: string; hint?: string; tone?: Tone; hintTone?: Tone;
}) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-line bg-panel p-4 shadow-[0_4px_14px_rgba(13,34,64,0.05)]">
      <span className={`grid h-11 w-11 shrink-0 place-items-center rounded-lg ${TILE_TONE[tone]}`}><Icon size={20} /></span>
      <div className="min-w-0">
        <div className={`text-2xl font-extrabold leading-tight tracking-tight ${tone === "bad" ? "text-bad" : tone === "warn" ? "text-accent-ink" : "text-ink"}`}>{value}</div>
        <div className="text-sm font-semibold text-ink">{label}</div>
        {hint && <div className={`mt-0.5 text-xs ${hintTone === "bad" ? "font-semibold text-bad" : "text-muted"}`}>{hint}</div>}
      </div>
    </div>
  );
}

export function KpiRow({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">{children}</div>;
}

export function PillTabs<T extends string>({ tabs, active, onChange, label }: {
  tabs: { key: T; label: string; count?: number }[]; active: T; onChange: (key: T) => void; label: string;
}) {
  return (
    <div role="tablist" aria-label={label} className="flex flex-wrap gap-2">
      {tabs.map((t) => (
        <button key={t.key} role="tab" aria-selected={t.key === active} onClick={() => onChange(t.key)}
          className={`min-h-9 rounded-lg border px-3 text-sm font-semibold transition ${t.key === active
            ? "border-accent bg-accent/10 text-accent-ink" : "border-line bg-panel text-ink hover:bg-soft"}`}>
          {t.label}{t.count !== undefined && <span className="ml-1.5 text-xs text-muted">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

const BADGE = {
  ok: "bg-ok/12 text-ok", warn: "bg-accent/12 text-accent-ink", bad: "bg-bad/12 text-bad",
  info: "bg-info/12 text-info", neutral: "bg-chip text-muted",
} as const;

export function Badge({ tone, children }: { tone: keyof typeof BADGE; children: ReactNode }) {
  return <span className={`inline-flex items-center whitespace-nowrap rounded-md px-2 py-0.5 text-[11px] font-bold ${BADGE[tone]}`}>{children}</span>;
}

export function Panel({ title, meta, action, children, className = "" }: {
  title: string; meta?: ReactNode; action?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={`rounded-xl border border-line bg-panel p-4 shadow-[0_4px_14px_rgba(13,34,64,0.05)] ${className}`}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-bold text-ink">{title}</h2>
        {meta && <span className="text-xs text-muted">{meta}</span>}
        {action}
      </div>
      {children}
    </section>
  );
}

export function DetailRows({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)] gap-x-3 gap-y-2 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="min-w-0 break-words font-semibold text-ink">{v ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

export function ProgressRow({ label, value, total, tone, right }: {
  label: string; value: number; total: number; tone: "ok" | "warn" | "bad" | "info"; right?: ReactNode;
}) {
  const pct = total > 0 ? Math.min(100, (value / total) * 100) : 0;
  const bar = { ok: "bg-ok", warn: "bg-accent", bad: "bg-bad", info: "bg-info" }[tone];
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 text-sm">
      <span className="text-ink">{label}</span>
      <span className="text-right font-bold text-ink">{right ?? `${value} / ${total}`}</span>
      <div className="col-span-2 h-2 overflow-hidden rounded-full bg-soft" role="img" aria-label={`${label}: ${value} of ${total}`}>
        <div className={`h-full rounded-full ${bar}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export const GATE_STYLE: Record<GateStatus, { icon: LucideIcon; tone: string; label: string; row: string }> = {
  pass: { icon: CheckCircle2, tone: "text-ok", label: "Pass", row: "border-line" },
  open: { icon: CircleDot, tone: "text-accent-ink", label: "Open", row: "border-accent/30 bg-accent/5" },
  fail: { icon: XCircle, tone: "text-bad", label: "Fail", row: "border-bad/30 bg-bad/5" },
};

export function EmptyState({ icon: Icon = AlertTriangle, title, children }: {
  icon?: LucideIcon; title: string; children?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center">
      <Icon size={22} className="text-muted" />
      <p className="font-semibold text-ink">{title}</p>
      {children && <div className="max-w-md text-sm text-muted">{children}</div>}
    </div>
  );
}

export function Button({ children, onClick, variant = "secondary", disabled, busy, type = "button", title }: {
  children: ReactNode; onClick?: () => void; variant?: "primary" | "secondary" | "danger";
  disabled?: boolean; busy?: boolean; type?: "button" | "submit"; title?: string;
}) {
  const style = {
    primary: "border-accent bg-accent text-white hover:brightness-95",
    secondary: "border-line bg-panel text-info hover:bg-soft",
    danger: "border-bad/40 bg-panel text-bad hover:bg-bad/5",
  }[variant];
  return (
    <button type={type} onClick={onClick} disabled={disabled || busy} title={title}
      className={`inline-flex min-h-10 items-center justify-center gap-1.5 rounded-lg border px-3 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${style}`}>
      {busy && <Loader2 size={14} className="animate-spin" />}{children}
    </button>
  );
}

export const inputClass = "min-h-10 w-full rounded-lg border border-line bg-panel px-3 text-sm text-ink placeholder:text-muted focus:border-accent focus:outline-none";

/** Runs a write with the signed-in token; returns an error message or "". */
export function useMutation() {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  async function run(key: string, fn: (token: string) => Promise<unknown>): Promise<boolean> {
    setBusy(key);
    setError("");
    try {
      await fn(getAuthToken());
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "The change could not be saved.");
      return false;
    } finally {
      setBusy("");
    }
  }
  return { busy, error, setError, run };
}

export function ErrorNote({ message }: { message: string }) {
  if (!message) return null;
  return <p role="alert" className="rounded-lg border border-bad/30 bg-bad/5 px-3 py-2 text-sm text-bad">{message}</p>;
}

export function timeAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

export function utcTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return `${new Date(iso).toISOString().slice(11, 16)} UTC`;
}

export function utcDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" })} · ${utcTime(iso)}`;
}

export const humanize = (s: string) => s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

export function Breadcrumb({ section, page, detail }: { section: string; page: string; detail?: string }) {
  return (
    <nav aria-label="Breadcrumb" className="text-xs text-muted">
      {section} <span aria-hidden>›</span> <b className="text-ink">{page}</b>
      {detail && <> <span aria-hidden>›</span> {detail}</>}
    </nav>
  );
}

export function Avatar({ name }: { name: string }) {
  const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("") || "?";
  return <span aria-hidden className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-hero-2 text-[11px] font-bold text-white">{initials}</span>;
}
