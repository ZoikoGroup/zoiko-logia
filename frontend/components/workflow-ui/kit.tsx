"use client";

import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import { AlertTriangle, ArrowUpRight, CheckCircle2, ChevronDown, Circle, Info, Loader2, Search, XCircle } from "lucide-react";
import type { ReactNode } from "react";

/** Building blocks of the Kriton Workspace and Accounting Workflows pages
 * (Saved Answers, Drafts & Reports, Workpapers, Review Tasks, Evidence Packs,
 * Reports & Insights, Compliance Calendar). Every figure a page passes in is
 * read from its records; the kit only lays them out. Colours come from the
 * theme tokens, so light and dark mode both work. */

export type Tone = "ok" | "warn" | "bad" | "info" | "neutral" | "brand";

const TILE: Record<Tone, string> = {
  ok: "bg-ok/10 text-ok", warn: "bg-accent/12 text-accent-ink", bad: "bg-bad/10 text-bad",
  info: "bg-info/10 text-info", neutral: "bg-chip text-muted", brand: "bg-accent/12 text-accent-ink",
};
const BADGE: Record<Tone, string> = {
  ok: "bg-ok/12 text-ok", warn: "bg-accent/14 text-accent-ink", bad: "bg-bad/12 text-bad",
  info: "bg-info/12 text-info", neutral: "bg-chip text-muted", brand: "bg-accent/14 text-accent-ink",
};

// ── Page frame ───────────────────────────────────────────────────────────────

export function WorkflowPage({ section, title, subtitle, note, children }: {
  section: "Kriton Workspace" | "Accounting Workflows"; title: string; subtitle: string; note?: string; children: ReactNode;
}) {
  const today = new Date().toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" });
  return (
    <main className="flex-1 overflow-y-auto p-4 lg:p-6">
      <div className="mx-auto max-w-[1600px] space-y-4">
        <nav aria-label="Breadcrumb" className="text-xs text-muted">
          Workspace <span aria-hidden className="mx-1">/</span> {section} <span aria-hidden className="mx-1">/</span> <b className="text-ink">{title}</b>
        </nav>
        <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-accent-ink">{section}</p>
            <h1 className="mt-1 text-[28px] font-bold leading-tight tracking-tight text-ink sm:text-[32px]">{title}</h1>
            <p className="mt-1 text-sm text-muted">{subtitle}</p>
          </div>
          <div className="shrink-0 sm:text-right">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-accent/40 bg-accent/10 px-3 py-1 text-[10px] font-bold uppercase tracking-wider text-accent-ink">
              <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-ok" /> Live records
            </span>
            <p className="mt-1 text-[11px] text-muted">{today}{note ? ` · ${note}` : ""}</p>
          </div>
        </header>
        {children}
      </div>
    </main>
  );
}

// ── Scope bar ────────────────────────────────────────────────────────────────

export type ScopeItem = {
  icon: LucideIcon; label: string; value: string; onChange: (value: string) => void;
  options: { value: string; label: string }[]; tone?: Tone;
};

/** The row of scope selectors under the title. Each one filters real records. */
export function ScopeBar({ items }: { items: ScopeItem[] }) {
  return (
    <div className={`grid gap-3 sm:grid-cols-2 ${items.length >= 4 ? "xl:grid-cols-4" : items.length === 3 ? "xl:grid-cols-3" : ""}`}>
      {items.map(({ icon: Icon, label, value, onChange, options, tone = "brand" }) => (
        <label key={label} className="relative flex min-w-0 items-center gap-3 rounded-xl border border-line bg-panel px-3 py-2.5 shadow-[0_4px_14px_rgba(13,34,64,0.04)]">
          <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg ${TILE[tone]}`}><Icon size={17} /></span>
          <span className="min-w-0 flex-1">
            <span className="block text-[10px] text-muted">{label}</span>
            <select value={value} onChange={(e) => onChange(e.target.value)} aria-label={label}
              className="w-full cursor-pointer appearance-none truncate bg-transparent pr-6 text-sm font-semibold text-ink outline-none">
              {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </span>
          <ChevronDown aria-hidden size={16} className="pointer-events-none absolute right-3 text-ink" />
        </label>
      ))}
    </div>
  );
}

// ── Hero banner ──────────────────────────────────────────────────────────────

export function Hero({ icon: Icon, eyebrow, title, subtitle, actions, aside }: {
  icon: LucideIcon; eyebrow: string; title: string; subtitle: string; actions?: ReactNode; aside?: ReactNode;
}) {
  return (
    <section className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-hero to-hero-2 px-5 py-5 text-white shadow-[0_12px_32px_rgba(13,34,64,0.18)] sm:px-6">
      <div aria-hidden className="pointer-events-none absolute -right-10 -top-24 h-72 w-72 rotate-45 border border-white/5" />
      <div aria-hidden className="pointer-events-none absolute right-40 -bottom-28 h-64 w-64 rotate-45 border border-white/5" />
      <div className="relative flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 items-center gap-4">
          <span className="grid h-14 w-14 shrink-0 place-items-center rounded-xl border-2 border-white/80 bg-hero-2 text-gold shadow-inner"><Icon size={26} /></span>
          <div className="min-w-0">
            <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-white/80">{eyebrow}</p>
            <h2 className="mt-0.5 text-xl font-extrabold tracking-tight sm:text-2xl">{title}</h2>
            <p className="mt-1 text-xs text-white/75 sm:text-sm">{subtitle}</p>
          </div>
        </div>
        {actions && <div className="flex flex-wrap gap-2 lg:justify-end">{actions}</div>}
        {aside && <div className="lg:text-right">{aside}</div>}
      </div>
    </section>
  );
}

export function HeroButton({ children, onClick, href, primary, disabled, title }: {
  children: ReactNode; onClick?: () => void; href?: string; primary?: boolean; disabled?: boolean; title?: string;
}) {
  const style = `inline-flex min-h-9 items-center gap-1.5 rounded-lg border px-3.5 text-xs font-bold transition disabled:cursor-not-allowed disabled:opacity-50 ${
    primary ? "border-accent bg-accent text-white hover:brightness-95" : "border-white/30 bg-white/5 text-white hover:bg-white/10"}`;
  if (href) return <Link href={href} className={style} title={title}>{children}</Link>;
  return <button type="button" onClick={onClick} disabled={disabled} title={title} className={style}>{children}</button>;
}

/** "1 Assemble → 2 Validate → 3 Review → 4 Seal" on the right of the hero. */
export function LifecycleSteps({ title, steps, link }: { title: string; steps: string[]; link?: { label: string; href: string } }) {
  return (
    <div>
      <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-accent">{title}</p>
      <ol className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-white/85 lg:justify-end">
        {steps.map((step, i) => (
          <li key={step} className="flex items-center gap-1.5">
            <span className={`grid h-4 w-4 place-items-center rounded-full text-[9px] font-bold ${i === steps.length - 1 ? "bg-accent text-white" : "bg-white/15"}`}>{i + 1}</span>
            {step}{i < steps.length - 1 && <span aria-hidden className="text-accent">→</span>}
          </li>
        ))}
      </ol>
      {link && <Link href={link.href} className="mt-2 inline-flex items-center gap-1 text-xs font-bold text-accent hover:underline">{link.label} <ArrowUpRight size={12} /></Link>}
    </div>
  );
}

// ── Figures ──────────────────────────────────────────────────────────────────

export function StatGrid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">{children}</div>;
}

export function StatCard({ icon: Icon, tone = "info", value, label, hint }: {
  icon: LucideIcon; tone?: Tone; value: ReactNode; label: string; hint?: string;
}) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-line bg-panel p-4 shadow-[0_4px_14px_rgba(13,34,64,0.05)]">
      <span className={`grid h-11 w-11 shrink-0 place-items-center rounded-lg ${TILE[tone]}`}><Icon size={20} /></span>
      <div className="min-w-0">
        <div className="text-2xl font-extrabold leading-tight tracking-tight text-ink">{value}</div>
        <div className="text-sm font-semibold text-ink">{label}</div>
        {hint && <div className="mt-0.5 text-[11px] text-muted">{hint}</div>}
      </div>
    </div>
  );
}

// ── Panels, tabs and controls ────────────────────────────────────────────────

export function Panel({ title, subtitle, actions, children, footer, className = "" }: {
  title: string; subtitle?: string; actions?: ReactNode; children: ReactNode; footer?: ReactNode; className?: string;
}) {
  return (
    <section className={`min-w-0 rounded-xl border border-line bg-panel shadow-[0_4px_14px_rgba(13,34,64,0.05)] ${className}`} aria-label={title}>
      <div className="flex flex-wrap items-start justify-between gap-2 px-4 pt-4">
        <div className="min-w-0">
          <h2 className="text-base font-bold text-ink">{title}</h2>
          {subtitle && <p className="mt-0.5 text-[11px] text-muted">{subtitle}</p>}
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>
      <div className="px-4 pb-4 pt-3">{children}</div>
      {footer && <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-4 py-2.5 text-[11px] text-muted">{footer}</div>}
    </section>
  );
}

/** Register filter tabs: buttons in a labelled group, the active one
 * underlined. The count is decoration (aria-hidden), so a tab is named by its
 * label alone. */
export function FilterTabs<T extends string>({ tabs, active, onChange, label }: {
  tabs: { key: T; label: string; count?: number }[]; active: T; onChange: (key: T) => void; label: string;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-x-5 gap-y-1 border-b border-line">
      {tabs.map((t) => (
        <button key={t.key} type="button" onClick={() => onChange(t.key)} aria-pressed={t.key === active}
          className={`-mb-px flex items-center gap-1.5 border-b-2 pb-2 pt-1 text-xs font-semibold transition ${t.key === active
            ? "border-accent text-accent-ink" : "border-transparent text-muted hover:text-ink"}`}>
          {t.label}
          {t.count !== undefined && <span aria-hidden className="rounded-full bg-chip px-1.5 text-[10px] font-bold text-muted">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

/** Tabs inside an inspector panel (role=tab). */
export function SubTabs<T extends string>({ tabs, active, onChange, label }: {
  tabs: { key: T; label: string }[]; active: T; onChange: (key: T) => void; label: string;
}) {
  return (
    <div role="tablist" aria-label={label} className="flex flex-wrap gap-x-5 border-b border-line">
      {tabs.map((t) => (
        <button key={t.key} type="button" role="tab" aria-selected={t.key === active} onClick={() => onChange(t.key)}
          className={`-mb-px border-b-2 pb-2 text-xs font-semibold transition ${t.key === active ? "border-accent text-accent-ink" : "border-transparent text-muted hover:text-ink"}`}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function SearchField({ value, onChange, placeholder, label }: { value: string; onChange: (v: string) => void; placeholder: string; label: string }) {
  return (
    <label className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-line bg-panel px-3 py-2">
      <Search size={14} className="shrink-0 text-muted" />
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} aria-label={label}
        className="w-full min-w-0 bg-transparent text-sm text-ink outline-none placeholder:text-muted" />
    </label>
  );
}

export function FilterSelect({ value, onChange, options, label }: {
  value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; label: string;
}) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} aria-label={label}
      className="min-h-9 rounded-lg border border-line bg-panel px-2.5 text-xs text-ink outline-none focus:border-accent">
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}

export const inputClass = "w-full rounded-lg border border-line bg-panel px-3 py-2 text-sm text-ink outline-none placeholder:text-muted focus:border-accent";

export function Btn({ children, onClick, variant = "secondary", disabled, busy, type = "button", title, className = "", label }: {
  children: ReactNode; onClick?: () => void; variant?: "primary" | "secondary" | "danger" | "success" | "quiet";
  disabled?: boolean; busy?: boolean; type?: "button" | "submit"; title?: string; className?: string; label?: string;
}) {
  const style = {
    primary: "border-accent bg-accent text-white hover:brightness-95",
    secondary: "border-line bg-panel text-ink hover:bg-soft",
    danger: "border-bad/40 bg-panel text-bad hover:bg-bad/5",
    success: "border-ok bg-ok text-white hover:brightness-95",
    quiet: "border-transparent bg-transparent text-muted hover:bg-soft hover:text-ink",
  }[variant];
  return (
    <button type={type} onClick={onClick} disabled={disabled || busy} title={title} aria-label={label}
      className={`inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg border px-3 text-xs font-bold transition disabled:cursor-not-allowed disabled:opacity-50 ${style} ${className}`}>
      {busy && <Loader2 size={13} className="animate-spin" />}{children}
    </button>
  );
}

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`inline-flex items-center whitespace-nowrap rounded-md px-2 py-0.5 text-[11px] font-bold ${BADGE[tone]}`}>{children}</span>;
}

// ── Register table ───────────────────────────────────────────────────────────

/** Column headings over a register. `template` is the grid-cols class shared
 * with RegisterRow, written out in full by the page. */
export function RegisterHead({ columns, template }: { columns: string[]; template: string }) {
  return (
    <div aria-hidden className={`hidden gap-3 rounded-t-lg bg-soft px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-muted md:grid ${template}`}>
      {columns.map((c) => <span key={c}>{c}</span>)}
    </div>
  );
}

export function RegisterRow({ selected, onClick, icon: Icon, tone = "info", title, subtitle, cells, template }: {
  selected?: boolean; onClick: () => void; icon: LucideIcon; tone?: Tone; title: ReactNode; subtitle?: ReactNode; cells: ReactNode[]; template: string;
}) {
  return (
    <button type="button" onClick={onClick} aria-current={selected || undefined}
      className={`grid w-full gap-x-3 gap-y-1.5 border-b border-line px-3 py-3 text-left transition last:border-b-0 hover:bg-soft md:items-center ${template} ${selected ? "bg-accent/5 shadow-[inset_3px_0_0_var(--accent)]" : ""}`}>
      <span className="flex min-w-0 items-start gap-3">
        <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg ${TILE[tone]}`}><Icon size={15} /></span>
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold text-ink">{title}</span>
          {subtitle && <span className="mt-0.5 block truncate text-[11px] text-muted">{subtitle}</span>}
        </span>
      </span>
      {cells.map((cell, i) => <span key={i} className="min-w-0 text-xs text-ink md:pl-0 pl-11">{cell}</span>)}
    </button>
  );
}

export function Stack({ main, sub, subTone }: { main: ReactNode; sub?: ReactNode; subTone?: "muted" | "warn" | "bad" | "ok" }) {
  const tone = { muted: "text-muted", warn: "text-accent-ink", bad: "text-bad", ok: "text-ok" }[subTone ?? "muted"];
  return (
    <span className="block min-w-0">
      <span className="block truncate font-semibold text-ink">{main}</span>
      {sub && <span className={`mt-0.5 block truncate text-[11px] ${tone}`}>{sub}</span>}
    </span>
  );
}

// ── Inspector ────────────────────────────────────────────────────────────────

export function Inspector({ eyebrow, badges, title, description, children }: {
  eyebrow: string; badges?: ReactNode; title: string; description?: string; children: ReactNode;
}) {
  return (
    <section aria-label={`${eyebrow}: ${title}`} className="min-w-0 rounded-xl border border-line bg-panel p-4 shadow-[0_4px_14px_rgba(13,34,64,0.05)] lg:sticky lg:top-4">
      <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-muted">{eyebrow}</p>
      {badges && <div className="mt-2 flex flex-wrap gap-1.5">{badges}</div>}
      <h2 className="mt-2 text-xl font-bold leading-snug tracking-tight text-ink">{title}</h2>
      {description && <p className="mt-1 text-xs leading-5 text-muted">{description}</p>}
      <div className="mt-4 space-y-4">{children}</div>
    </section>
  );
}

export function KeyGrid({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-lg border border-line bg-soft/60 p-3">
      {items.map(([k, v]) => (
        <div key={k} className="min-w-0">
          <dt className="text-[9px] font-bold uppercase tracking-wider text-muted">{k}</dt>
          <dd className="mt-0.5 break-words text-xs font-semibold text-ink">{v ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

/** A completion bar. `passed` of `total` checks, read from the record. */
export function Readiness({ label, passed, total, hint, tone }: { label: string; passed: number; total: number; hint?: string; tone?: "ok" | "warn" }) {
  const pct = total ? Math.round((passed / total) * 100) : 0;
  const done = total > 0 && passed === total;
  const bar = (tone ?? (done ? "ok" : "warn")) === "ok" ? "bg-ok" : "bg-accent";
  return (
    <div className="rounded-lg border border-line bg-soft/60 p-3">
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="font-semibold text-ink">{label}</span>
        <span className={`font-bold ${done ? "text-ok" : "text-accent-ink"}`}>{passed} of {total} passed</span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-line" role="img" aria-label={`${label}: ${passed} of ${total} passed`}>
        <div className={`h-full rounded-full ${bar}`} style={{ width: `${pct}%` }} />
      </div>
      {hint && <p className="mt-2 text-[11px] text-muted">{hint}</p>}
    </div>
  );
}

export function Callout({ tone = "warn", title, children }: { tone?: "warn" | "bad" | "ok" | "info"; title: string; children?: ReactNode }) {
  const style = {
    warn: "border-accent/40 bg-accent/8 text-accent-ink", bad: "border-bad/30 bg-bad/5 text-bad",
    ok: "border-ok/30 bg-ok/5 text-ok", info: "border-info/30 bg-info/5 text-info",
  }[tone];
  const Icon = tone === "ok" ? CheckCircle2 : tone === "info" ? Info : AlertTriangle;
  return (
    <div className={`rounded-lg border px-3 py-2.5 ${style}`}>
      <p className="flex items-center gap-1.5 text-xs font-bold"><Icon size={14} /> {title}</p>
      {children && <div className="mt-1 text-[11px] leading-5 text-ink/80">{children}</div>}
    </div>
  );
}

export type CheckState = "pass" | "warn" | "fail" | "todo";
const CHECK: Record<CheckState, { icon: LucideIcon; style: string; text: string }> = {
  pass: { icon: CheckCircle2, style: "bg-ok/12 text-ok", text: "text-muted" },
  warn: { icon: AlertTriangle, style: "bg-accent/14 text-accent-ink", text: "text-accent-ink" },
  fail: { icon: XCircle, style: "bg-bad/12 text-bad", text: "text-bad" },
  todo: { icon: Circle, style: "bg-chip text-muted", text: "text-muted" },
};

export function CheckRow({ state, title, detail, right }: { state: CheckState; title: string; detail?: ReactNode; right?: ReactNode }) {
  const { icon: Icon, style, text } = CHECK[state];
  return (
    <li className="flex items-start gap-3 border-b border-line py-2.5 last:border-b-0">
      <span className={`grid h-6 w-6 shrink-0 place-items-center rounded-md ${style}`}><Icon size={13} /></span>
      <span className="min-w-0 flex-1">
        <span className="block text-xs font-semibold text-ink">{title}</span>
        {detail && <span className="mt-0.5 block text-[11px] text-muted">{detail}</span>}
      </span>
      {right && <span className={`shrink-0 text-[11px] ${text}`}>{right}</span>}
    </li>
  );
}

export function Checklist({ children }: { children: ReactNode }) {
  return <ul className="rounded-lg">{children}</ul>;
}

/** The footnote box at the bottom of an inspector. */
export function ControlNote({ children }: { children: ReactNode }) {
  return <p className="rounded-lg border border-line bg-soft/70 px-3 py-2 text-[11px] leading-5 text-muted">{children}</p>;
}

// ── Lists and footers ────────────────────────────────────────────────────────

export function ListItem({ icon: Icon, tone = "info", title, detail, badge, onClick }: {
  icon: LucideIcon; tone?: Tone; title: ReactNode; detail?: ReactNode; badge?: ReactNode; onClick?: () => void;
}) {
  const body = (
    <>
      <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg ${TILE[tone]}`}><Icon size={15} /></span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-xs font-semibold text-ink">{title}</span>
        {detail && <span className="mt-0.5 block truncate text-[11px] text-muted">{detail}</span>}
      </span>
      {badge}
    </>
  );
  return (
    <li className="border-b border-line last:border-b-0">
      {onClick
        ? <button type="button" onClick={onClick} className="flex w-full items-center gap-3 py-2.5 text-left hover:bg-soft">{body}</button>
        : <div className="flex items-center gap-3 py-2.5">{body}</div>}
    </li>
  );
}

export function PanelLink({ href, onClick, children }: { href?: string; onClick?: () => void; children: ReactNode }) {
  const style = "inline-flex items-center gap-1 text-[11px] font-bold text-info hover:underline";
  if (href) return <Link href={href} className={style}>{children} <ArrowUpRight size={11} /></Link>;
  return <button type="button" onClick={onClick} className={style}>{children} <ArrowUpRight size={11} /></button>;
}

export function InfoCards({ items }: { items: { icon: LucideIcon; title: string; text: string }[] }) {
  return (
    <div className="grid gap-3 md:grid-cols-3">
      {items.map(({ icon: Icon, title, text }) => (
        <div key={title} className="rounded-xl border border-line bg-panel p-4 shadow-[0_4px_14px_rgba(13,34,64,0.04)]">
          <p className="flex items-center gap-1.5 text-xs font-bold text-ink"><Icon size={13} className="text-accent-ink" /> {title}</p>
          <p className="mt-1.5 text-[11px] leading-5 text-muted">{text}</p>
        </div>
      ))}
    </div>
  );
}

export function Empty({ icon: Icon = Info, title, children }: { icon?: LucideIcon; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center">
      <Icon size={22} className="text-muted" />
      <p className="text-sm font-semibold text-ink">{title}</p>
      {children && <div className="max-w-md text-xs text-muted">{children}</div>}
    </div>
  );
}

export function Loading({ children }: { children: ReactNode }) {
  return <div className="flex items-center justify-center py-12 text-sm text-muted"><Loader2 className="mr-2 animate-spin" size={16} /> {children}</div>;
}

export function ErrorNote({ message }: { message: string }) {
  if (!message) return null;
  return <p role="alert" className="rounded-lg border border-bad/30 bg-bad/5 px-3 py-2 text-xs text-bad">{message}</p>;
}

/** "Oct 16" over "2026". */
export function DateCell({ iso }: { iso: string | null | undefined }) {
  if (!iso) return <span className="text-muted">—</span>;
  const d = new Date(iso);
  return (
    <span className="block">
      <span className="block font-semibold text-ink">{d.toLocaleDateString(undefined, { month: "short", day: "numeric" })}</span>
      <span className="block text-[11px] text-muted">{d.getFullYear()}</span>
    </span>
  );
}

export function shortId(prefix: string, id: string) {
  return `${prefix}-${id.replace(/[^a-zA-Z0-9]/g, "").slice(-6).toUpperCase()}`;
}
