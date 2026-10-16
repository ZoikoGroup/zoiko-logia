"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { ArrowRight, Building2, CalendarDays, Globe2, BookOpen, Sparkles } from "lucide-react";
import { BrandMark } from "@/components/layout/AppHeader";

export function OverviewFrame({ title, subtitle, children, actions }: { title: string; subtitle: string; children: ReactNode; actions?: ReactNode }) {
  return <main className="overview-page flex-1 overflow-y-auto p-4 lg:p-6"><div className="mx-auto max-w-[1600px] space-y-4">
    <div className="flex items-center gap-2 text-[11px] text-muted"><span>Workspace</span><span>/</span><span>Overview</span><span>/</span><b className="text-ink">{title}</b></div>
    <header className="flex flex-wrap items-end justify-between gap-3"><div><h1 className="text-[28px] font-bold tracking-tight text-ink">{title}</h1><p className="mt-1 text-xs leading-5 text-muted">{subtitle}</p></div>{actions}</header>
    {children}
    <footer className="py-2 text-right text-[10px] text-muted">ZoikoLogia™ with Kriton™ · Professional workspace · Figures reflect available workspace records</footer>
  </div></main>;
}

export function ContextStrip({ workspace, jurisdiction = "Workspace scope", framework = "Not selected", period = "Current records", children }: { workspace?: string; jurisdiction?: string; framework?: string; period?: string; children?: ReactNode }) {
  return <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{[
    ["Client / Entity", workspace || "Current workspace", Building2], ["Jurisdiction", jurisdiction, Globe2], ["Accounting Framework", framework, BookOpen], ["Reporting Period", period, CalendarDays],
  ].map(([label, value, Icon]) => { const Glyph = Icon as typeof Building2; return <div key={String(label)} className="flex min-w-0 items-center gap-3 rounded-xl border border-line bg-panel px-3 py-3 shadow-sm"><span className="rounded-lg bg-amber-500/10 p-2 text-amber-700"><Glyph size={17} /></span><div className="min-w-0"><p className="text-[10px] text-muted">{String(label)}</p><p className="truncate text-xs font-semibold text-ink">{String(value)}</p></div>{label === "Jurisdiction" && children}</div>; })}</div>;
}

export function OverviewPanel({ title, subtitle, href, action = "View all", children, className = "", id }: { title: string; subtitle?: string; href?: string; action?: string; children: ReactNode; className?: string; id?: string }) {
  return <section id={id} className={`min-w-0 rounded-xl border border-line bg-panel p-4 shadow-[0_2px_10px_rgba(16,24,40,.025)] ${className}`}><div className="mb-3 flex items-start justify-between gap-3"><div><h2 className="text-sm font-bold text-ink">{title}</h2>{subtitle && <p className="mt-1 text-[11px] leading-4 text-muted">{subtitle}</p>}</div>{href && <Link href={href} className="shrink-0 text-[10px] font-semibold text-amber-700 hover:underline">{action} →</Link>}</div>{children}</section>;
}

export function Metric({ label, value, detail, href, tone = "blue" }: { label: string; value: number | string; detail: string; href?: string; tone?: "blue" | "amber" | "red" | "green" }) {
  const colors = { blue: "bg-blue-500/10 text-blue-700", amber: "bg-amber-500/10 text-amber-700", red: "bg-red-500/10 text-red-700", green: "bg-emerald-500/10 text-emerald-700" };
  const content = <><div className="flex gap-3"><span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${colors[tone]}`}><BookOpen size={18} /></span><div><div className="text-[28px] font-bold leading-8 text-ink">{value}</div><h2 className="mt-1 text-xs font-bold text-ink">{label}</h2><p className="mt-1 text-[10px] leading-4 text-muted">{detail}</p></div></div>{href && <ArrowRight size={15} className="absolute bottom-4 right-4 text-muted" />}</>;
  const cls = "relative min-h-28 rounded-xl border border-line bg-panel p-4 shadow-sm";
  return href ? <Link href={href} className={`${cls} hover:border-amber-500/50`}>{content}</Link> : <div className={cls}>{content}</div>;
}

export function Status({ children }: { children: ReactNode }) {
  const label = String(children);
  const color = /blocked|critical|overdue|fail|high|restricted/i.test(label) ? "bg-red-500/10 text-red-700" : /passed|effective|eligible|complete|current|\bapproved\b|\bactive\b|\bready\b/i.test(label) ? "bg-emerald-500/10 text-emerald-700" : /pending|review|attention|exception|draft|stale/i.test(label) ? "bg-amber-500/10 text-amber-700" : "bg-blue-500/10 text-blue-700";
  return <span className={`inline-block rounded px-2 py-1 text-[10px] font-semibold ${color}`}>{children}</span>;
}

export function ActionLink({ href, children }: { href: string; children: ReactNode }) {
  return <Link href={href} className="inline-flex items-center justify-center gap-1 rounded-md border border-line bg-soft/40 px-3 py-1.5 text-[10px] font-semibold text-brand hover:border-brand/40">{children}<ArrowRight size={11} /></Link>;
}

export function NavyBanner({ eyebrow, title, children, action }: { eyebrow: string; title: string; children?: ReactNode; action?: ReactNode }) {
  return <section className="overview-navy relative overflow-hidden rounded-xl px-5 py-5 text-white"><div className="relative z-10 flex flex-wrap items-center gap-4"><BrandMark className="h-12 w-12" /><div className="min-w-0 flex-1"><p className="text-[10px] font-bold uppercase tracking-[.16em] text-blue-100/80">{eyebrow}</p><h2 className="mt-1 text-xl font-bold">{title}</h2>{children && <div className="mt-1 text-xs leading-5 text-blue-100/80">{children}</div>}</div>{action}</div></section>;
}

export function ResearchDesk({ compact = false, title = "Ask Kriton", recent }: { compact?: boolean; title?: string; recent?: { title: string; href: string } }) {
  return <section className="overview-navy relative h-full overflow-hidden rounded-xl p-5 text-white"><div className="relative z-10"><div className="flex items-center gap-3"><BrandMark className="h-12 w-12" /><div><h2 className="text-xl font-bold">{title}</h2><p className="mt-1 text-[11px] text-blue-100/80">Source-governed assistance for accounting, audit, tax, and professional workflows.</p></div></div>
    {recent && <Link href={recent.href} className="mt-4 block rounded-lg border border-white/15 bg-white/5 p-3"><p className="text-[9px] uppercase tracking-widest text-blue-100/70">Most recent saved research</p><p className="mt-2 text-sm font-semibold">{recent.title}</p><p className="mt-2 text-xs text-orange-300">Resume session →</p></Link>}
    <div className="mt-4 flex flex-wrap gap-2 text-[10px] text-blue-50"><span className="rounded border border-white/15 bg-white/10 px-2 py-1.5">● Source and licence checks</span><span className="rounded border border-white/15 bg-white/10 px-2 py-1.5">Human review when required</span></div>
    <Link href="/ask-kriton" className="mt-3 flex items-center justify-between gap-3 rounded-lg border border-white/25 bg-white/10 p-2 pl-3"><span className="text-xs text-blue-100/80">{compact ? "Ask a question or resume research…" : "Ask an accounting question, review a document, or start a workpaper…"}</span><span className="flex shrink-0 items-center gap-1 rounded-md bg-[#f28a18] px-3 py-2 text-xs font-bold text-white"><Sparkles size={13} /> Ask Kriton →</span></Link>
    {!compact && <div className="mt-3 flex flex-wrap gap-2">{["Draft a workpaper", "IFRS vs. US GAAP", "Review source guidance", "Build evidence checklist"].map(label => <Link key={label} href="/ask-kriton" className="rounded border border-white/15 bg-white/10 px-2 py-1.5 text-[10px] hover:bg-white/20">{label}</Link>)}</div>}
    <p className="mt-3 text-[10px] leading-4 text-blue-100/70">Citations · Effective-date checks · Evidence trail · Professional sign-off when required</p>
  </div></section>;
}

export function NoItems({ children = "No items to display in this workspace." }: { children?: ReactNode }) {
  return <p className="py-7 text-xs leading-5 text-muted">{children}</p>;
}
