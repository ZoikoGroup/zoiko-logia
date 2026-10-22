"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft, ArrowRight, Award, BarChart3, BookMarked, BookOpen, ChartColumn, ChevronRight, Clock, Compass, Download,
  ExternalLink, FileText, Flame, Globe2, GraduationCap, ListChecks, Loader2, MessageSquare, Network, PlayCircle, Scale,
  Search, SearchCheck, SpellCheck, Trash2, UserRound, Calculator, FileSpreadsheet, ClipboardList,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { AnswerRenderer } from "@/components/AnswerRenderer";
import { uniqueCitations } from "@/lib/unique-citations";
import { deleteCPDEntry } from "@/lib/learning-practice-api";
import { ADVISOR } from "@/lib/advisor";
import { PracticeQuiz } from "@/components/learning/PracticeQuiz";
import { Badge, Panel } from "@/components/workflow-ui/kit";
import {
  askKriton,
  createCPDEntry,
  getAuthToken,
  getCPDSummary,
  listCPDEntries,
  listSyllabusPathways,
  listTopicMapNodes,
  ApiError,
  type AskKritonResponse,
  type CPDEntry,
  type CPDSummary,
  type SyllabusPathway,
  type TopicMapNode,
} from "@/lib/api";

type View = "overview" | "learning" | "practice" | "progress";

const RISK_TONE: Record<string, "ok" | "info" | "warn" | "bad"> = {
  LOW: "ok",
  MEDIUM: "info",
  HIGH: "warn",
  RESTRICTED: "bad",
};

// The jurisdictions Ask Kriton accepts (as on the main Ask Kriton composer).
const LEARNING_JURISDICTIONS: [string, string][] = [
  ["", "Any jurisdiction"], ["UK", "UK"], ["US", "US"], ["IFRS", "IFRS"], ["UAE", "UAE"], ["India", "India"], ["EU", "EU"],
];

const SUBJECTS = ["IFRS", "US GAAP", "Tax", "Audit", "Regulations", "Global Perspectives"];

const PATHS: { title: string; detail: string; modules: number; hours: number; icon: LucideIcon; art: LucideIcon; tile: string; badge: string }[] = [
  { title: "Financial Reporting Mastery", detail: "From fundamentals to advanced reporting under IFRS and US GAAP.", modules: 12, hours: 6,
    icon: ChartColumn, art: BarChart3, tile: "from-hero via-hero-2 to-info", badge: "bg-hero" },
  { title: "International Tax Essentials", detail: "Key principles, compliance and practice across major jurisdictions.", modules: 10, hours: 5,
    icon: Scale, art: Scale, tile: "from-hero-2 via-accent-ink to-gold", badge: "bg-accent-ink" },
  { title: "Audit & Assurance Foundations", detail: "Risk, procedures, documentation and reporting.", modules: 8, hours: 4,
    icon: FileText, art: SearchCheck, tile: "from-soft via-line to-hero-2", badge: "bg-hero" },
  { title: "Financial Analysis & Valuation", detail: "Analyse performance, model scenarios and create value.", modules: 10, hours: 5,
    icon: ChartColumn, art: Calculator, tile: "from-line via-soft to-hero-2", badge: "bg-accent-ink" },
];

const SCENARIOS: { title: string; level: "Intermediate" | "Advanced"; detail: string; minutes: number }[] = [
  { title: "Prepare a Balance Sheet", level: "Intermediate", detail: "Prepare a complete balance sheet under IFRS with adjustments.", minutes: 30 },
  { title: "Corporate Tax Calculation", level: "Advanced", detail: "Calculate tax for a multinational group across multiple jurisdictions.", minutes: 45 },
  { title: "Audit Risk Assessment", level: "Intermediate", detail: "Identify and assess key audit risks for a listed company.", minutes: 40 },
  { title: "Cash Flow Forecasting", level: "Intermediate", detail: "Build a 12-month cash flow forecast with scenarios.", minutes: 35 },
];

const ROLES: { icon: LucideIcon; title: string; detail: string; tone: string }[] = [
  { icon: UserRound, title: "Accountants & Bookkeepers", detail: "Core accounting and compliance", tone: "bg-info" },
  { icon: BarChart3, title: "Finance Professionals", detail: "Analysis, planning and reporting", tone: "bg-accent" },
  { icon: FileSpreadsheet, title: "Tax Specialists", detail: "International and local tax", tone: "bg-ok" },
  { icon: SearchCheck, title: "Auditors & Assurance", detail: "Audit methodology and practice", tone: "bg-info" },
  { icon: GraduationCap, title: "Students & Educators", detail: "Foundations and exam preparation", tone: "bg-accent" },
];

const TRENDING = [
  "IFRS 18 Presentation and Disclosure",
  "AI in Auditing and Finance",
  "Global Tax Reform 2026",
  "Sustainability Reporting (ESRS)",
  "Financial Modelling Techniques",
];
const TRENDING_TONE = ["bg-accent", "bg-info", "bg-bad", "bg-muted", "bg-hero-2"];

const CARD = "rounded-xl border border-line bg-panel shadow-[0_4px_14px_rgba(13,34,64,0.05)]";

function prerequisiteList(text: string): string[] {
  return (text || "").split(/[,;]/).map((s) => s.trim()).filter(Boolean);
}

function downloadCpdCsv(entries: CPDEntry[]) {
  const cell = (value: string) => `"${value.replace(/"/g, '""')}"`;
  const rows = entries.map((e) => [new Date(e.logged_at).toISOString().slice(0, 10), cell(e.topic), String(e.minutes)].join(","));
  const blob = new Blob([["Date,Topic,Minutes", ...rows].join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `cpd-log-${new Date().toISOString().slice(0, 10)}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

/** Days in a row, ending today or yesterday, with CPD time logged. */
function learningStreak(entries: CPDEntry[], now = new Date()): number {
  const days = new Set(entries.map((e) => new Date(e.logged_at).toISOString().slice(0, 10)));
  const day = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  if (!days.has(day.toISOString().slice(0, 10))) day.setUTCDate(day.getUTCDate() - 1);
  let streak = 0;
  while (days.has(day.toISOString().slice(0, 10))) {
    streak += 1;
    day.setUTCDate(day.getUTCDate() - 1);
  }
  return streak;
}

function ProgressRing({ value }: { value: number }) {
  const radius = 50;
  const circumference = 2 * Math.PI * radius;
  return (
    <svg viewBox="0 0 124 124" className="h-32 w-32 shrink-0" aria-hidden>
      <circle cx="62" cy="62" r={radius} fill="none" strokeWidth="9" className="stroke-soft" />
      <circle cx="62" cy="62" r={radius} fill="none" strokeWidth="9" strokeLinecap="round" className="stroke-accent"
        strokeDasharray={`${(value / 100) * circumference} ${circumference}`} transform="rotate(-90 62 62)" />
      <text x="62" y="62" textAnchor="middle" className="fill-ink text-[22px] font-extrabold">{value}%</text>
      <text x="62" y="80" textAnchor="middle" className="fill-muted text-[9px]">Overall Progress</text>
    </svg>
  );
}

function SectionHead({ title, link, onClick }: { title: string; link?: string; onClick?: () => void }) {
  return (
    <div className="mb-3 flex items-center justify-between">
      <h2 className="text-lg font-bold text-ink">{title}</h2>
      {link && (
        <button type="button" onClick={onClick} className="inline-flex items-center gap-1 text-xs font-semibold text-info hover:underline">
          {link} <ArrowRight size={13} />
        </button>
      )}
    </div>
  );
}

export default function LearningPracticePage() {
  const [view, setView] = useState<View>("overview");
  const [pathways, setPathways] = useState<SyllabusPathway[]>([]);
  const [topics, setTopics] = useState<TopicMapNode[]>([]);
  const [error, setError] = useState("");

  // Ask Kriton (Learning mode)
  const [query, setQuery] = useState("");
  const [asking, setAsking] = useState(false);
  const [askResult, setAskResult] = useState<AskKritonResponse | null>(null);
  const [askError, setAskError] = useState("");
  const [jurisdiction, setJurisdiction] = useState("");
  const [highlightTopic, setHighlightTopic] = useState("");
  const [deletingId, setDeletingId] = useState<string | null>(null);

  // CPD log
  const [cpdEntries, setCpdEntries] = useState<CPDEntry[]>([]);
  const [cpdSummary, setCpdSummary] = useState<CPDSummary | null>(null);
  const [cpdTopic, setCpdTopic] = useState("");
  const [cpdMinutes, setCpdMinutes] = useState("30");
  const [loggingCpd, setLoggingCpd] = useState(false);

  function loadCPD() {
    const token = getAuthToken();
    Promise.all([listCPDEntries(token), getCPDSummary(token)]).then(([entries, summary]) => {
      setCpdEntries(entries);
      setCpdSummary(summary);
    });
  }

  useEffect(() => {
    const token = getAuthToken();
    Promise.all([listSyllabusPathways(token), listTopicMapNodes(token)])
      .then(([p, t]) => {
        setPathways(p);
        setTopics(t);
      })
      .catch(() => setError("Could not load learning content from the server."));
    loadCPD();
  }, []);

  function open(next: View) {
    setView(next);
    window.scrollTo?.({ top: 0, behavior: "smooth" });
  }

  async function handleAsk(e: FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setAsking(true);
    setAskResult(null);
    setAskError("");
    try {
      const response = await askKriton(getAuthToken(), { query, mode: "Learning", ...(jurisdiction ? { jurisdiction } : {}) });
      setAskResult(response);
    } catch (err) {
      setAskError(err instanceof ApiError ? err.message : "Could not reach the orchestration service.");
    } finally {
      setAsking(false);
    }
  }

  // Puts a study question in the Ask box; the learner reviews it and presses Ask.
  function askAbout(text: string) {
    setView("learning");
    setQuery(text);
    requestAnimationFrame(() => {
      const input = document.getElementById("learning-ask-input");
      input?.scrollIntoView?.({ behavior: "smooth", block: "center" });
      input?.focus();
    });
  }

  function showTopic(name: string) {
    const node = topics.find((t) => t.topic.toLowerCase() === name.toLowerCase());
    if (!node) {
      askAbout(`Explain ${name}.`);
      return;
    }
    setHighlightTopic(node.id);
    document.getElementById(`topic-${node.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  async function handleDeleteCPD(entry: CPDEntry) {
    if (!window.confirm(`Delete the CPD entry "${entry.topic}" (${entry.minutes} min)?`)) return;
    setDeletingId(entry.id);
    try {
      await deleteCPDEntry(entry.id);
      loadCPD();
    } catch {
      setError("Could not delete this CPD entry.");
    } finally {
      setDeletingId(null);
    }
  }

  async function handleLogCPD(e: FormEvent) {
    e.preventDefault();
    const minutes = parseInt(cpdMinutes, 10);
    if (!cpdTopic.trim() || !minutes || minutes <= 0) return;
    setLoggingCpd(true);
    try {
      await createCPDEntry(getAuthToken(), { topic: cpdTopic, minutes });
      setCpdTopic("");
      setCpdMinutes("30");
      loadCPD();
    } catch {
      setError("Could not log this CPD entry.");
    } finally {
      setLoggingCpd(false);
    }
  }

  const studied = pathways.filter((p) => cpdEntries.some((e) => e.topic === p.topic)).length;
  const minutesBy = (key: (e: CPDEntry) => string) =>
    [...cpdEntries.reduce((m, e) => m.set(key(e), (m.get(key(e)) ?? 0) + e.minutes), new Map<string, number>())]
      .sort((a, b) => b[1] - a[1]);
  const byTopic = minutesBy((e) => e.topic);
  const byMonth = minutesBy((e) => new Date(e.logged_at).toLocaleDateString(undefined, { year: "numeric", month: "short" }));
  const sources = askResult?.answer ? uniqueCitations(askResult.answer.citations ?? []) : [];

  // Learning progress, from the user's own records.
  const progressPct = pathways.length ? Math.round((studied / pathways.length) * 100) : 0;
  const practiceDone = cpdEntries.filter((e) => /^practice quiz/i.test(e.topic)).length;
  const streak = learningStreak(cpdEntries);

  const headerButtons: [string, LucideIcon, () => void, boolean][] = [
    ["My Learning", UserRound, () => open("learning"), view === "learning"],
    ["Certificates", Award, () => open("progress"), false],
    ["Bookmarks", BookMarked, () => {}, false],
    ["Progress", BarChart3, () => open("progress"), view === "progress"],
  ];

  const resources: { icon: LucideIcon; title: string; detail: string; tone: string; go: () => void }[] = [
    { icon: PlayCircle, title: "Video Courses", detail: "Expert-led lessons", tone: "bg-info/12 text-info", go: () => open("learning") },
    { icon: ListChecks, title: "Practice Questions", detail: "Test your knowledge", tone: "bg-info/12 text-info", go: () => open("practice") },
    { icon: FileText, title: "Case Studies", detail: "Real-world examples", tone: "bg-ok/12 text-ok", go: () => open("practice") },
    { icon: BookOpen, title: "Study Notes", detail: "Summaries and guides", tone: "bg-accent/14 text-accent", go: () => open("learning") },
    { icon: ClipboardList, title: "Templates", detail: "Download and use", tone: "bg-ok/12 text-ok", go: () => {} },
    { icon: SpellCheck, title: "Glossary", detail: "Key terms explained", tone: "bg-bad/10 text-bad",
      go: () => askAbout("Explain the key accounting terms a learner should know, with a one-line definition each.") },
  ];

  return (
    <main className="flex-1 overflow-y-auto p-4 lg:p-6">
      <div className="mx-auto max-w-[1600px] space-y-5">
        {/* Header */}
        <header className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex items-center gap-4">
            <GraduationCap size={52} className="shrink-0 text-ink" />
            <div>
              <h1 className="text-[28px] font-bold leading-tight tracking-tight text-ink sm:text-[32px]">Learning &amp; Practice</h1>
              <p className="mt-1 text-sm text-muted">Build your accounting and finance knowledge. Practice real-world scenarios. Grow with Kriton.</p>
            </div>
          </div>
          <nav aria-label="Learning sections" className="flex flex-wrap gap-3">
            {headerButtons.map(([label, Icon, go, active]) => {
              const style = `inline-flex min-h-12 items-center gap-2.5 rounded-lg border px-4 text-sm font-semibold text-ink shadow-[0_4px_14px_rgba(13,34,64,0.04)] hover:bg-soft ${active ? "border-accent bg-accent/5" : "border-line bg-panel"}`;
              return label === "Bookmarks" ? (
                <Link key={label} href="/saved-answers" className={style}><Icon size={18} /> {label}</Link>
              ) : (
                <button key={label} type="button" onClick={go} aria-pressed={active} className={style}><Icon size={18} /> {label}</button>
              );
            })}
          </nav>
        </header>

        {error && <p role="alert" className="text-xs text-bad">{error}</p>}

        {view !== "overview" && (
          <button type="button" onClick={() => open("overview")} className="inline-flex items-center gap-1.5 text-xs font-semibold text-info hover:underline">
            <ArrowLeft size={13} /> Back to Learning &amp; Practice
          </button>
        )}

        {view === "overview" && (
          <>
            <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
              <div className="min-w-0 space-y-6">
                {/* Hero */}
                <section className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-hero via-hero to-hero-2 px-7 py-7 text-white shadow-[0_12px_32px_rgba(13,34,64,0.18)]">
                  <div aria-hidden className="pointer-events-none absolute -right-16 -top-20 h-80 w-80 rounded-full bg-info/25 blur-3xl" />
                  <div aria-hidden className="pointer-events-none absolute right-16 top-1/2 hidden -translate-y-1/2 md:block">
                    <span className="grid h-44 w-60 place-items-center rounded-xl border-4 border-white/20 bg-hero/60 text-info shadow-[0_0_60px_rgba(80,160,255,0.35)]">
                      <Globe2 size={96} strokeWidth={1.2} />
                    </span>
                  </div>
                  <div className="relative max-w-2xl">
                    <p className="text-xs font-semibold uppercase tracking-[0.18em] text-white/85">Learn. Practice. Apply.</p>
                    <h2 className="mt-3 text-[30px] font-bold leading-tight tracking-tight">
                      Master accounting and finance<br />with <span className="text-accent">Kriton</span>
                    </h2>
                    <p className="mt-3 max-w-lg text-[15px] leading-6 text-white/85">Structured learning, real-world practice and expert guidance across global standards, tax, audit and finance.</p>
                    <div className="mt-5 flex flex-wrap gap-2">
                      {SUBJECTS.map((label) => (
                        <button key={label} type="button" onClick={() => askAbout(`Explain the key concepts of ${label} for an accounting learner.`)}
                          className="rounded-full border border-white/50 px-4 py-1.5 text-xs font-semibold text-white hover:bg-white/10">
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>
                </section>

                {/* Featured learning paths */}
                <section aria-label="Featured learning paths">
                  <SectionHead title="Featured Learning Paths" link="View all learning paths" onClick={() => open("learning")} />
                  <div className="grid gap-4 sm:grid-cols-2 2xl:grid-cols-4">
                    {PATHS.map((path) => (
                      <button key={path.title} type="button" onClick={() => askAbout(`Guide me through the ${path.title} learning path: ${path.detail}`)}
                        className={`${CARD} overflow-hidden text-left transition hover:-translate-y-0.5`}>
                        <span className={`relative block h-[76px] bg-gradient-to-br ${path.tile}`}>
                          <path.art aria-hidden size={64} strokeWidth={1.3} className="absolute right-5 top-1.5 text-white/55" />
                          <span className={`absolute -bottom-5 left-4 grid h-11 w-11 place-items-center rounded-lg text-white shadow ${path.badge}`}>
                            <path.icon size={20} />
                          </span>
                        </span>
                        <span className="block px-4 pb-3 pt-8">
                          <span className="block text-base font-bold leading-snug text-ink">{path.title}</span>
                          <span className="mt-1 block min-h-[34px] text-xs leading-[17px] text-muted">{path.detail}</span>
                          <span className="mt-4 flex items-center gap-4 text-[11px] text-muted">
                            <span className="inline-flex items-center gap-1"><FileText size={12} /> {path.modules} modules</span>
                            <span className="inline-flex items-center gap-1"><Clock size={12} /> {path.hours} hours</span>
                            <ArrowRight size={14} className="ml-auto text-accent" />
                          </span>
                        </span>
                      </button>
                    ))}
                  </div>
                </section>

                {/* Practice scenarios */}
                <section aria-label="Practice scenarios">
                  <SectionHead title="Practice Scenarios" link="View all practice scenarios" onClick={() => open("practice")} />
                  <div className="grid gap-4 sm:grid-cols-2 2xl:grid-cols-4">
                    {SCENARIOS.map((s) => (
                      <button key={s.title} type="button" onClick={() => askAbout(`Guide me step by step through this practice scenario: ${s.title}. ${s.detail}`)}
                        className={`${CARD} p-4 text-left transition hover:-translate-y-0.5`}>
                        <span className="block text-sm font-bold text-ink">{s.title}</span>
                        <span className={`mt-2 inline-block rounded px-2 py-0.5 text-[11px] font-medium ${s.level === "Advanced" ? "bg-bad/10 text-bad" : "bg-accent/12 text-accent-ink"}`}>{s.level}</span>
                        <span className="mt-2 block min-h-[34px] text-xs leading-[17px] text-muted">{s.detail}</span>
                        <span className="mt-4 flex items-center gap-5 text-[11px] text-muted">
                          <span className="inline-flex items-center gap-1"><Clock size={12} /> {s.minutes} mins</span>
                          <span className="inline-flex items-center gap-1"><Compass size={12} /> Guided</span>
                          <ArrowRight size={14} className="ml-auto text-accent" />
                        </span>
                      </button>
                    ))}
                  </div>
                </section>
              </div>

              {/* Right column */}
              <aside className="min-w-0 space-y-4">
                <section aria-label="Your learning progress" className={`${CARD} p-4`}>
                  <SectionHead title="Your Learning Progress" link="View all" onClick={() => open("progress")} />
                  <div className="flex items-center gap-3">
                    <ProgressRing value={progressPct} />
                    <dl className="flex-1 divide-y divide-line text-[11px]">
                      {([
                        [studied, "Courses completed"],
                        [Math.max(0, pathways.length - studied), "In progress"],
                        [0, "Certificates earned"],
                        [practiceDone, "Practice scenarios completed"],
                      ] as const).map(([value, label]) => (
                        <div key={label} className="flex items-center gap-3 py-1.5">
                          <dt className="w-7 text-right text-sm font-bold text-ink">{value}</dt>
                          <dd className="text-muted">{label}</dd>
                        </div>
                      ))}
                    </dl>
                  </div>
                  <button type="button" onClick={() => open("progress")} className={`${CARD} mt-3 flex w-full items-center gap-3 px-3 py-2.5 text-left`}>
                    <Flame size={26} className="shrink-0 text-accent" />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[11px] font-semibold text-ink">Learning Streak</span>
                      <span className="block text-sm font-bold text-ink">{streak} day{streak === 1 ? "" : "s"}</span>
                      <span className="block text-[11px] text-muted">Keep going! You&apos;re building expertise.</span>
                    </span>
                    <ArrowRight size={14} className="text-accent" />
                  </button>
                </section>

                <section aria-label="Role-based learning" className={`${CARD} p-4`}>
                  <SectionHead title="Role-Based Learning" link="View all" onClick={() => open("learning")} />
                  <ul>
                    {ROLES.map(({ icon: Icon, title, detail, tone }) => (
                      <li key={title}>
                        <button type="button" onClick={() => askAbout(`Suggest a learning plan for ${title.toLowerCase()}: ${detail.toLowerCase()}.`)}
                          className="flex w-full items-center gap-3 py-2 text-left hover:bg-soft">
                          <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg text-white ${tone}`}><Icon size={17} /></span>
                          <span className="min-w-0 flex-1">
                            <span className="block text-sm font-semibold text-ink">{title}</span>
                            <span className="block text-[11px] text-muted">{detail}</span>
                          </span>
                          <ChevronRight size={15} className="text-accent" />
                        </button>
                      </li>
                    ))}
                  </ul>
                </section>

                <section aria-label="Trending topics" className={`${CARD} p-4`}>
                  <h2 className="mb-2 text-lg font-bold text-ink">Trending Topics</h2>
                  <ol className="divide-y divide-line">
                    {TRENDING.map((topic, index) => (
                      <li key={topic}>
                        <button type="button" onClick={() => askAbout(`Explain ${topic}.`)} className="flex w-full items-center gap-3 py-2 text-left hover:bg-soft">
                          <span className={`grid h-6 w-6 shrink-0 place-items-center rounded-full text-[11px] font-bold text-white ${TRENDING_TONE[index]}`}>{index + 1}</span>
                          <span className="min-w-0 flex-1 truncate text-xs text-ink">{topic}</span>
                          <ChevronRight size={15} className="text-accent" />
                        </button>
                      </li>
                    ))}
                  </ol>
                </section>
              </aside>
            </div>

            {/* Learning resources */}
            <section aria-label="Learning resources">
              <SectionHead title="Learning Resources" link="View all resources" onClick={() => open("learning")} />
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6">
                {resources.map(({ icon: Icon, title, detail, tone, go }) => {
                  const body = (
                    <>
                      <span className={`grid h-11 w-11 shrink-0 place-items-center rounded-lg ${tone}`}><Icon size={22} /></span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-sm font-semibold text-ink">{title}</span>
                        <span className="block text-[11px] text-muted">{detail}</span>
                      </span>
                      <ChevronRight size={15} className="text-muted" />
                    </>
                  );
                  const style = `${CARD} flex items-center gap-3 p-3 text-left hover:bg-soft`;
                  return title === "Templates"
                    ? <Link key={title} href="/drafts-reports" className={style}>{body}</Link>
                    : <button key={title} type="button" onClick={go} className={style}>{body}</button>;
                })}
              </div>
            </section>
          </>
        )}

        {view === "learning" && (
          <>
            {/* Ask Kriton, Learning mode */}
            <Panel title="Study with Kriton" subtitle="Learning mode · answers are checked against sources">
              <div className="mb-3 flex items-center gap-2 text-xs text-muted">
                <Badge tone="info">Context: Learning</Badge>
                <label className="flex items-center gap-1.5">
                  Jurisdiction:
                  <select value={jurisdiction} onChange={(e) => setJurisdiction(e.target.value)} aria-label="Jurisdiction"
                    className="rounded-lg border border-line bg-soft px-2 py-1 text-xs text-ink outline-none">
                    {LEARNING_JURISDICTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </label>
              </div>
              <form onSubmit={handleAsk} className="zl-search-surface flex items-center gap-2 rounded-xl border px-4 py-3 transition-shadow">
                <Search size={16} className="shrink-0 text-accent-ink" />
                <input id="learning-ask-input" type="text" value={query} onChange={(e) => setQuery(e.target.value)}
                  placeholder={ADVISOR.chatPlaceholder} className="w-full bg-transparent text-sm text-ink outline-none placeholder:text-muted" />
                <button type="submit" disabled={asking || !query.trim()}
                  className="flex shrink-0 items-center gap-1.5 rounded-lg bg-accent px-3.5 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60">
                  {asking && <Loader2 size={12} className="animate-spin" />}
                  Ask
                </button>
              </form>
              {askError && <p className="mt-2 text-xs text-bad">{askError}</p>}
              {askResult && (
                <div className="mt-3 rounded-xl border border-line bg-panel p-3">
                  <div className="mb-1.5 flex items-center gap-2">
                    <Badge tone={RISK_TONE[askResult.safety.risk_level] ?? "neutral"}>{askResult.safety.risk_level}</Badge>
                    <span className="text-[11px] text-muted">Outcome: {askResult.outcome}</span>
                  </div>
                  {askResult.answer?.text ? (
                    <AnswerRenderer
                      text={askResult.answer.text}
                      visualization={askResult.visualization}
                      secondaryVisualizations={askResult.secondary_visualizations}
                      calculationResult={askResult.answer.calculation_result}
                      verifiedCharts={askResult.answer.verified_charts}
                      className="text-sm"
                    />
                  ) : (
                    <p className="text-sm leading-relaxed text-ink">{askResult.safety.refusal_text ?? "No response composed."}</p>
                  )}
                  {sources.length > 0 && (
                    <div className="mt-3 border-t border-line pt-2">
                      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">Sources</p>
                      <ul className="space-y-0.5">
                        {sources.map((s) => (
                          <li key={s.ref_id} className="text-xs">
                            {s.url ? (
                              <a href={s.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-info hover:underline">
                                <ExternalLink size={11} /> {s.title}
                              </a>
                            ) : (
                              <span className="text-ink">{s.title}</span>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </Panel>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <Panel title="Continue Pathway" subtitle={pathways.length ? `${studied} of ${pathways.length} studied` : undefined}>
                {pathways.length > 0 && (
                  <div className="mb-3 h-1.5 overflow-hidden rounded-full bg-soft" role="progressbar" aria-label="Pathway progress"
                    aria-valuemin={0} aria-valuemax={pathways.length} aria-valuenow={studied}>
                    <div className="h-full rounded-full bg-ok" style={{ width: `${(studied / pathways.length) * 100}%` }} />
                  </div>
                )}
                <ul className="space-y-3">
                  {pathways.map((p) => (
                    <li key={p.id} className="border-t border-line pt-3 first:border-t-0 first:pt-0">
                      <div className="text-sm font-semibold text-ink">{p.topic}</div>
                      <div className="mt-0.5 text-xs text-muted">{p.body} — {p.qualification} — {p.module}</div>
                      <div className="mt-1 text-xs text-ink">{p.learning_outcome}</div>
                      {/* A topic counts as studied once CPD time is logged against it. */}
                      <div className="mt-1.5 flex flex-wrap items-center gap-3">
                        <button onClick={() => askAbout(`Explain ${p.topic} for ${p.body} ${p.qualification}: ${p.learning_outcome}`)}
                          className="inline-flex items-center gap-1 text-xs font-semibold text-info hover:underline">
                          <MessageSquare size={11} /> Ask Kriton
                        </button>
                        {cpdEntries.some((e) => e.topic === p.topic) ? (
                          <Badge tone="ok">Studied ✓</Badge>
                        ) : (
                          <button onClick={() => { setCpdTopic(p.topic); open("progress"); }}
                            className="text-xs font-semibold text-info hover:underline">
                            Log study time
                          </button>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              </Panel>

              <Panel title="Topic Map" subtitle="What to learn first, and the standards behind each topic">
                <ul className="space-y-3">
                  {topics.map((t) => (
                    <li key={t.id} id={`topic-${t.id}`}
                      className={`rounded-lg border-t border-line pt-3 first:border-t-0 first:pt-0 ${highlightTopic === t.id ? "bg-accent/5 ring-1 ring-accent/30" : ""}`}>
                      <div className="flex items-center gap-1.5 text-sm font-semibold text-ink"><Network size={13} className="text-muted" /> {t.topic}</div>
                      <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted">
                        Learn first:
                        {prerequisiteList(t.prerequisites).length ? (
                          prerequisiteList(t.prerequisites).map((name) => (
                            <button key={name} onClick={() => showTopic(name)}
                              title={topics.some((x) => x.topic.toLowerCase() === name.toLowerCase()) ? "Show this topic" : "Ask Kriton about this"}
                              className="rounded-full border border-line px-2 py-0.5 text-[11px] text-ink hover:border-accent hover:text-accent-ink">
                              {name}
                            </button>
                          ))
                        ) : (
                          <span>nothing</span>
                        )}
                      </div>
                      <div className="text-xs text-muted">Standards: {t.standards_summary}</div>
                      <button onClick={() => askAbout(`Explain ${t.topic} under ${t.standards_summary || "the relevant standards"}.`)}
                        className="mt-1 inline-flex items-center gap-1 text-xs font-semibold text-info hover:underline">
                        <MessageSquare size={11} /> Ask Kriton
                      </button>
                    </li>
                  ))}
                </ul>
              </Panel>
            </div>
          </>
        )}

        {view === "practice" && <PracticeQuiz onLogged={loadCPD} />}

        {view === "progress" && (
          <Panel title="CPD / Progress" subtitle="Your recorded study time"
            actions={cpdSummary ? <Badge tone="ok"><Clock size={11} className="mr-1 inline" />{cpdSummary.total_hours}h logged</Badge> : undefined}>
            <form onSubmit={handleLogCPD} className="mb-4 flex flex-wrap items-end gap-3">
              <div>
                <label className="mb-1 block text-[11px] font-medium text-muted">Topic</label>
                <input value={cpdTopic} onChange={(e) => setCpdTopic(e.target.value)} placeholder="e.g. Revenue Recognition"
                  className="min-w-[200px] rounded-lg border border-line bg-soft px-2.5 py-1.5 text-xs text-ink outline-none focus:border-accent" />
              </div>
              <div>
                <label className="mb-1 block text-[11px] font-medium text-muted">Minutes</label>
                <input id="cpd-minutes" type="number" min={1} max={600} value={cpdMinutes} onChange={(e) => setCpdMinutes(e.target.value)}
                  className="w-24 rounded-lg border border-line bg-soft px-2.5 py-1.5 text-xs text-ink outline-none focus:border-accent" />
              </div>
              <button type="submit" disabled={loggingCpd || !cpdTopic.trim()}
                className="rounded-lg bg-accent px-4 py-2 text-xs font-semibold text-white hover:brightness-95 disabled:opacity-60">
                {loggingCpd ? "Logging…" : "Log CPD time"}
              </button>
            </form>

            {cpdEntries.length === 0 ? (
              <p className="text-sm text-muted">No CPD time logged yet.</p>
            ) : (
              <>
                <ul className="space-y-1.5">
                  {cpdEntries.map((entry) => (
                    <li key={entry.id} className="flex items-center justify-between gap-2 border-t border-line pt-1.5 text-sm first:border-t-0 first:pt-0">
                      <span className="font-medium text-ink">{entry.topic}</span>
                      <span className="flex items-center gap-2 text-xs text-muted">
                        {entry.minutes} min · {new Date(entry.logged_at).toLocaleDateString()}
                        <button onClick={() => void handleDeleteCPD(entry)} disabled={deletingId === entry.id}
                          aria-label={`Delete CPD entry ${entry.topic}`} className="rounded p-0.5 text-muted hover:text-bad disabled:opacity-50">
                          <Trash2 size={12} />
                        </button>
                      </span>
                    </li>
                  ))}
                </ul>

                <div className="mt-4 grid grid-cols-1 gap-3 border-t border-line pt-3 sm:grid-cols-2">
                  {([["By topic", byTopic], ["By month", byMonth]] as const).map(([heading, rows]) => (
                    <div key={heading}>
                      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">{heading}</p>
                      <ul className="space-y-0.5 text-xs">
                        {rows.map(([label, minutes]) => (
                          <li key={label} className="flex justify-between gap-2">
                            <span className="truncate text-ink">{label}</span>
                            <span className="shrink-0 text-muted">{(minutes / 60).toFixed(1)}h</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
                <button onClick={() => downloadCpdCsv(cpdEntries)}
                  className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-xs font-semibold text-ink hover:bg-soft">
                  <Download size={12} /> Download CPD log (CSV)
                </button>
              </>
            )}
            <p className="mt-3 border-t border-line pt-2 text-[11px] text-muted">
              CPD claims are ZoikoLogia-recorded evidence, not a professional-body-issued certificate.
            </p>
          </Panel>
        )}
      </div>
    </main>
  );
}
