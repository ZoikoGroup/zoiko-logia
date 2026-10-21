"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight, BarChart3, BookMarked, BookOpen, Briefcase, Calculator, ClipboardList, Clock, Compass, Download,
  ExternalLink, FileText, Flame, GraduationCap, Landmark, LayoutTemplate, ListChecks, Loader2, MessageSquare, Network,
  PlayCircle, Scale, Search, ShieldCheck, SpellCheck, Trash2, TrendingUp, UserRound, Users, Award,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { AnswerRenderer } from "@/components/AnswerRenderer";
import { uniqueCitations } from "@/lib/unique-citations";
import { deleteCPDEntry, listPracticeBanks, type PracticeBank } from "@/lib/learning-practice-api";
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

const RISK_TONE: Record<string, "ok" | "info" | "warn" | "bad"> = {
  LOW: "ok",
  MEDIUM: "info",
  HIGH: "warn",
  RESTRICTED: "bad",
};

// The jurisdictions Ask Kriton accepts (as on the main Ask Kriton composer).
// The request has no framework field, so none is offered.
const LEARNING_JURISDICTIONS: [string, string][] = [
  ["", "Any jurisdiction"], ["UK", "UK"], ["US", "US"], ["IFRS", "IFRS"], ["UAE", "UAE"], ["India", "India"], ["EU", "EU"],
];

// Study prompts behind the hero chips and the role list. They only fill the
// Ask box; the learner reviews the question and presses Ask.
const SUBJECTS: [string, string][] = [
  ["IFRS", "Explain the core principles of IFRS and the main standards a learner should start with."],
  ["US GAAP", "Explain the structure of US GAAP and how the FASB Codification is organised."],
  ["Tax", "Explain the basic concepts of corporate tax and indirect tax for an accounting learner."],
  ["Audit", "Explain the main stages of a financial statement audit."],
  ["Regulations", "Explain how accounting and tax regulations are set and who the main regulators are."],
  ["Global Perspectives", "Compare the main differences between IFRS and US GAAP."],
];
const ROLES: { icon: LucideIcon; title: string; detail: string; tone: string; prompt: string }[] = [
  { icon: UserRound, title: "Accountants & Bookkeepers", detail: "Core accounting and compliance", tone: "bg-info/12 text-info",
    prompt: "Suggest a learning plan for an accountant or bookkeeper: core accounting and compliance topics in order." },
  { icon: BarChart3, title: "Finance Professionals", detail: "Analysis, planning and reporting", tone: "bg-accent/14 text-accent-ink",
    prompt: "Suggest a learning plan for a finance professional: analysis, planning and reporting topics in order." },
  { icon: FileText, title: "Tax Specialists", detail: "International and local tax", tone: "bg-ok/12 text-ok",
    prompt: "Suggest a learning plan for a tax specialist covering international and local tax topics in order." },
  { icon: ShieldCheck, title: "Auditors & Assurance", detail: "Audit methodology and practice", tone: "bg-info/12 text-info",
    prompt: "Suggest a learning plan for an auditor: audit methodology and practice topics in order." },
  { icon: GraduationCap, title: "Students & Educators", detail: "Foundations and exam preparation", tone: "bg-accent/14 text-accent-ink",
    prompt: "Suggest a learning plan for an accounting student preparing for professional exams." },
];
const PATH_STYLES: { icon: LucideIcon; tile: string }[] = [
  { icon: BarChart3, tile: "from-hero to-info" },
  { icon: Scale, tile: "from-accent-ink to-accent" },
  { icon: FileText, tile: "from-hero-2 to-brand" },
  { icon: Calculator, tile: "from-accent to-gold" },
];

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

function scrollTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function ProgressRing({ value }: { value: number }) {
  const radius = 44;
  const circumference = 2 * Math.PI * radius;
  return (
    <svg viewBox="0 0 110 110" className="h-28 w-28 shrink-0" aria-hidden>
      <circle cx="55" cy="55" r={radius} fill="none" strokeWidth="10" className="stroke-soft" />
      <circle cx="55" cy="55" r={radius} fill="none" strokeWidth="10" strokeLinecap="round"
        className="stroke-accent" strokeDasharray={`${(value / 100) * circumference} ${circumference}`}
        transform="rotate(-90 55 55)" />
      <text x="55" y="55" textAnchor="middle" className="fill-ink text-[20px] font-extrabold">{value}%</text>
      <text x="55" y="72" textAnchor="middle" className="fill-muted text-[9px]">pathway progress</text>
    </svg>
  );
}

export default function LearningPracticePage() {
  const [pathways, setPathways] = useState<SyllabusPathway[]>([]);
  const [topics, setTopics] = useState<TopicMapNode[]>([]);
  const [banks, setBanks] = useState<PracticeBank[]>([]);
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
    // The practice scenarios are the quiz banks; the quiz itself still loads them.
    Promise.resolve().then(() => listPracticeBanks()).then((b) => setBanks(b ?? [])).catch(() => setBanks([]));
    loadCPD();
  }, []);

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
    setQuery(text);
    const input = document.getElementById("learning-ask-input");
    input?.scrollIntoView({ behavior: "smooth", block: "center" });
    input?.focus();
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

  // Learning progress, all from the user's own records.
  const progressPct = pathways.length ? Math.round((studied / pathways.length) * 100) : 0;
  const quizzesDone = cpdEntries.filter((e) => /^practice quiz/i.test(e.topic)).length;
  const streak = learningStreak(cpdEntries);
  const cpdHours = cpdSummary ? cpdSummary.total_hours : 0;
  // Featured learning paths: the syllabus pathways grouped by qualification.
  const paths = [...pathways.reduce((groups, p) => {
    const key = `${p.body} · ${p.qualification}`;
    return groups.set(key, [...(groups.get(key) ?? []), p]);
  }, new Map<string, SyllabusPathway[]>())].slice(0, 4);

  const resources: { icon: LucideIcon; title: string; detail: string; tone: string; action?: () => void; href?: string }[] = [
    { icon: PlayCircle, title: "Video Courses", detail: "Coming soon", tone: "bg-info/12 text-info" },
    { icon: ListChecks, title: "Practice Questions", detail: "Test your knowledge", tone: "bg-info/12 text-info", action: () => scrollTo("practice-quiz") },
    { icon: FileText, title: "Case Studies", detail: "Coming soon", tone: "bg-ok/12 text-ok" },
    { icon: BookOpen, title: "Study Notes", detail: "Topic map and standards", tone: "bg-accent/14 text-accent-ink", action: () => scrollTo("topic-map") },
    { icon: LayoutTemplate, title: "Templates", detail: "Drafts and reports", tone: "bg-ok/12 text-ok", href: "/drafts-reports" },
    { icon: SpellCheck, title: "Glossary", detail: "Key terms explained", tone: "bg-bad/10 text-bad",
      action: () => askAbout("Explain the key accounting terms a learner should know, with a one-line definition each.") },
  ];

  return (
    <main className="flex-1 overflow-y-auto p-4 lg:p-6">
      <div className="mx-auto max-w-[1600px] space-y-5">
        {/* Header */}
        <header className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex items-center gap-4">
            <span className="grid h-14 w-14 shrink-0 place-items-center rounded-xl text-ink"><GraduationCap size={40} /></span>
            <div>
              <h1 className="text-[28px] font-bold leading-tight tracking-tight text-ink sm:text-[32px]">Learning &amp; Practice</h1>
              <p className="mt-1 text-sm text-muted">Build your accounting and finance knowledge. Practice real-world scenarios. Grow with Kriton.</p>
            </div>
          </div>
          <nav aria-label="Learning sections" className="flex flex-wrap gap-2">
            {([
              ["My Learning", UserRound, () => scrollTo("my-learning")],
              ["Certificates", Award, () => scrollTo("cpd-progress")],
              ["Progress", BarChart3, () => scrollTo("learning-progress")],
            ] as const).map(([label, Icon, go]) => (
              <button key={label} type="button" onClick={go}
                className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-line bg-panel px-4 text-sm font-semibold text-ink shadow-[0_4px_14px_rgba(13,34,64,0.04)] hover:bg-soft">
                <Icon size={17} /> {label}
              </button>
            ))}
            <Link href="/saved-answers"
              className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-line bg-panel px-4 text-sm font-semibold text-ink shadow-[0_4px_14px_rgba(13,34,64,0.04)] hover:bg-soft">
              <BookMarked size={17} /> Bookmarks
            </Link>
          </nav>
        </header>

        {error && <p role="alert" className="text-xs text-bad">{error}</p>}

        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="min-w-0 space-y-5">
            {/* Hero */}
            <section className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-hero to-hero-2 px-6 py-7 text-white shadow-[0_12px_32px_rgba(13,34,64,0.18)]">
              <div aria-hidden className="pointer-events-none absolute -right-10 -top-16 h-72 w-72 rounded-full bg-info/20 blur-3xl" />
              <div aria-hidden className="pointer-events-none absolute right-10 top-1/2 hidden -translate-y-1/2 opacity-90 md:block">
                <span className="grid h-40 w-40 place-items-center rounded-3xl border border-white/15 bg-white/5 text-gold"><GraduationCap size={88} /></span>
              </div>
              <div className="relative max-w-2xl">
                <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-white/80">Learn. Practice. Apply.</p>
                <h2 className="mt-2 text-3xl font-extrabold leading-tight tracking-tight">
                  Master accounting and finance<br />with <span className="text-accent">Kriton</span>
                </h2>
                <p className="mt-3 text-sm text-white/80">Structured learning, real-world practice and expert guidance across global standards, tax, audit and finance.</p>
                <div className="mt-5 flex flex-wrap gap-2" role="group" aria-label="Study a subject">
                  {SUBJECTS.map(([label, prompt]) => (
                    <button key={label} type="button" onClick={() => askAbout(prompt)}
                      className="rounded-full border border-white/40 bg-white/5 px-4 py-1.5 text-xs font-semibold text-white hover:bg-white/15">
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            </section>

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

            {/* Featured learning paths */}
            <section aria-label="Featured learning paths">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-lg font-bold text-ink">Featured Learning Paths</h2>
                <button type="button" onClick={() => scrollTo("my-learning")} className="inline-flex items-center gap-1 text-xs font-bold text-info hover:underline">
                  View all learning paths <ArrowRight size={13} />
                </button>
              </div>
              {paths.length === 0 ? (
                <p className="rounded-xl border border-line bg-panel p-4 text-sm text-muted">No learning paths are set up yet.</p>
              ) : (
                <div className="grid gap-4 sm:grid-cols-2 2xl:grid-cols-4">
                  {paths.map(([name, items], index) => {
                    const style = PATH_STYLES[index % PATH_STYLES.length];
                    const minutes = cpdEntries.filter((e) => items.some((p) => p.topic === e.topic)).reduce((s, e) => s + e.minutes, 0);
                    const done = items.filter((p) => cpdEntries.some((e) => e.topic === p.topic)).length;
                    return (
                      <button key={name} type="button" onClick={() => scrollTo("my-learning")}
                        className="group overflow-hidden rounded-xl border border-line bg-panel text-left shadow-[0_4px_14px_rgba(13,34,64,0.05)] transition hover:-translate-y-0.5">
                        <span className={`relative block h-28 bg-gradient-to-br ${style.tile}`}>
                          <span aria-hidden className="absolute -right-6 -top-6 h-24 w-24 rounded-full bg-white/10" />
                          <span className="absolute bottom-0 left-4 grid h-12 w-12 translate-y-1/2 place-items-center rounded-xl border-2 border-panel bg-hero text-white shadow">
                            <style.icon size={22} />
                          </span>
                        </span>
                        <span className="block px-4 pb-4 pt-8">
                          <span className="block text-base font-bold leading-snug text-ink">{items[0].qualification}</span>
                          <span className="mt-1 block text-xs text-muted">{items[0].body} · {[...new Set(items.map((p) => p.module))].slice(0, 2).join(", ")}</span>
                          <span className="mt-3 flex items-center justify-between border-t border-line pt-2 text-[11px] text-muted">
                            <span className="inline-flex items-center gap-1"><ClipboardList size={12} /> {items.length} topic{items.length === 1 ? "" : "s"} · {done} done</span>
                            <span className="inline-flex items-center gap-1"><Clock size={12} /> {(minutes / 60).toFixed(1)} h logged</span>
                            <ArrowRight size={14} className="text-accent-ink" />
                          </span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </section>

            {/* Practice scenarios: the quiz banks */}
            <section aria-label="Practice scenarios">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-lg font-bold text-ink">Practice Scenarios</h2>
                <button type="button" onClick={() => scrollTo("practice-quiz")} className="inline-flex items-center gap-1 text-xs font-bold text-info hover:underline">
                  Start practising <ArrowRight size={13} />
                </button>
              </div>
              {banks.length === 0 ? (
                <p className="rounded-xl border border-line bg-panel p-4 text-sm text-muted">Practice quizzes appear here once their question banks are available.</p>
              ) : (
                <div className="grid gap-4 sm:grid-cols-2 2xl:grid-cols-4">
                  {banks.map((bank) => (
                    <button key={bank.id} type="button" onClick={() => scrollTo("practice-quiz")}
                      className="rounded-xl border border-line bg-panel p-4 text-left shadow-[0_4px_14px_rgba(13,34,64,0.05)] transition hover:-translate-y-0.5">
                      <span className="block text-sm font-bold text-ink">{bank.title}</span>
                      <span className="mt-2 inline-block"><Badge tone="warn">{bank.questionCount} questions</Badge></span>
                      <span className="mt-2 block text-xs text-muted">Answers checked against: {bank.source}</span>
                      <span className="mt-3 flex items-center justify-between border-t border-line pt-2 text-[11px] text-muted">
                        <span className="inline-flex items-center gap-1"><Clock size={12} /> 5 questions a round</span>
                        <span className="inline-flex items-center gap-1"><Compass size={12} /> Guided</span>
                        <ArrowRight size={14} className="text-accent-ink" />
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </section>
          </div>

          {/* Right column */}
          <aside className="min-w-0 space-y-5">
            <section id="learning-progress" aria-label="Your learning progress"
              className="rounded-xl border border-line bg-panel p-4 shadow-[0_4px_14px_rgba(13,34,64,0.05)]">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-base font-bold text-ink">Your Learning Progress</h2>
                <button type="button" onClick={() => scrollTo("cpd-progress")} className="inline-flex items-center gap-1 text-xs font-bold text-info hover:underline">
                  View all <ArrowRight size={13} />
                </button>
              </div>
              <div className="flex items-center gap-4">
                <ProgressRing value={progressPct} />
                <dl className="flex-1 divide-y divide-line text-xs">
                  {([
                    [studied, "Pathway topics studied"],
                    [Math.max(0, pathways.length - studied), "Topics still to study"],
                    [`${cpdHours}h`, "CPD time logged"],
                    [quizzesDone, "Practice quizzes completed"],
                  ] as const).map(([value, label]) => (
                    <div key={label} className="flex items-center gap-3 py-1.5">
                      <dt className="w-10 text-right text-base font-extrabold text-ink">{value}</dt>
                      <dd className="text-muted">{label}</dd>
                    </div>
                  ))}
                </dl>
              </div>
              <div className="mt-4 flex items-center gap-3 rounded-lg border border-line bg-soft/60 px-3 py-2.5">
                <Flame size={26} className="shrink-0 text-accent" />
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-semibold text-ink">Learning Streak</p>
                  <p className="text-sm font-bold text-ink">{streak} day{streak === 1 ? "" : "s"}</p>
                  <p className="text-[11px] text-muted">{streak ? "Keep going! You're building expertise." : "Log study time today to start a streak."}</p>
                </div>
              </div>
            </section>

            <section aria-label="Role-based learning" className="rounded-xl border border-line bg-panel p-4 shadow-[0_4px_14px_rgba(13,34,64,0.05)]">
              <h2 className="mb-2 text-base font-bold text-ink">Role-Based Learning</h2>
              <ul>
                {ROLES.map(({ icon: Icon, title, detail, tone, prompt }) => (
                  <li key={title} className="border-b border-line last:border-b-0">
                    <button type="button" onClick={() => askAbout(prompt)} className="flex w-full items-center gap-3 py-2.5 text-left hover:bg-soft">
                      <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg ${tone}`}><Icon size={17} /></span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-sm font-semibold text-ink">{title}</span>
                        <span className="block text-[11px] text-muted">{detail}</span>
                      </span>
                      <ArrowRight size={14} className="text-accent-ink" />
                    </button>
                  </li>
                ))}
              </ul>
            </section>

            <section aria-label="Topics to explore" className="rounded-xl border border-line bg-panel p-4 shadow-[0_4px_14px_rgba(13,34,64,0.05)]">
              <h2 className="mb-2 flex items-center gap-1.5 text-base font-bold text-ink"><TrendingUp size={16} className="text-accent-ink" /> Topics to Explore</h2>
              {topics.length === 0 ? <p className="text-xs text-muted">No topics are set up yet.</p> : (
                <ol>
                  {topics.slice(0, 5).map((t, index) => (
                    <li key={t.id} className="border-b border-line last:border-b-0">
                      <button type="button" onClick={() => showTopic(t.topic)} aria-label={`${t.topic} — ${t.standards_summary || "explore"}`}
                        className="flex w-full items-center gap-3 py-2 text-left hover:bg-soft">
                        <span className={`grid h-6 w-6 shrink-0 place-items-center rounded-full text-[11px] font-bold text-white ${index === 0 ? "bg-accent" : index < 3 ? "bg-info" : "bg-muted"}`}>{index + 1}</span>
                        <span className="min-w-0 flex-1 truncate text-xs text-ink">{t.topic}{t.standards_summary ? ` · ${t.standards_summary}` : ""}</span>
                        <ArrowRight size={13} className="text-accent-ink" />
                      </button>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </aside>
        </div>

        {/* Learning resources */}
        <section aria-label="Learning resources">
          <h2 className="mb-3 text-lg font-bold text-ink">Learning Resources</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6">
            {resources.map(({ icon: Icon, title, detail, tone, action, href }) => {
              const body = (
                <>
                  <span className={`grid h-11 w-11 shrink-0 place-items-center rounded-lg ${tone}`}><Icon size={20} /></span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-semibold text-ink">{title}</span>
                    <span className="block text-[11px] text-muted">{detail}</span>
                  </span>
                  {(action || href) && <ArrowRight size={14} className="text-accent-ink" />}
                </>
              );
              const style = "flex items-center gap-3 rounded-xl border border-line bg-panel p-3 text-left shadow-[0_4px_14px_rgba(13,34,64,0.04)]";
              if (href) return <Link key={title} href={href} className={`${style} hover:bg-soft`}>{body}</Link>;
              if (action) return <button key={title} type="button" onClick={action} className={`${style} hover:bg-soft`}>{body}</button>;
              return <div key={title} className={`${style} opacity-70`} aria-disabled>{body}</div>;
            })}
          </div>
        </section>

        {/* The practice quiz itself */}
        <div id="practice-quiz" className="scroll-mt-4">
          <PracticeQuiz onLogged={loadCPD} />
        </div>

        {/* My learning: pathways and topic map */}
        <div id="my-learning" className="grid scroll-mt-4 grid-cols-1 gap-4 md:grid-cols-2">
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
                  {/* Progress without a new table: a topic counts as studied
                      once CPD time is logged against it. */}
                  <div className="mt-1.5 flex flex-wrap items-center gap-3">
                    <button onClick={() => askAbout(`Explain ${p.topic} for ${p.body} ${p.qualification}: ${p.learning_outcome}`)}
                      className="inline-flex items-center gap-1 text-xs font-semibold text-info hover:underline">
                      <MessageSquare size={11} /> Ask Kriton
                    </button>
                    {cpdEntries.some((e) => e.topic === p.topic) ? (
                      <Badge tone="ok">Studied ✓</Badge>
                    ) : (
                      <button onClick={() => { setCpdTopic(p.topic); document.getElementById("cpd-minutes")?.focus(); }}
                        className="text-xs font-semibold text-info hover:underline">
                        Log study time
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </Panel>

          <div id="topic-map" className="scroll-mt-4">
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
        </div>

        {/* CPD log: the user's own evidence of learning */}
        <div id="cpd-progress" className="scroll-mt-4">
          <Panel title="CPD / Progress" subtitle="Your recorded study time, the evidence behind your certificates"
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
        </div>

        <p className="flex items-center gap-1.5 text-[11px] text-muted"><Landmark size={12} /> <Briefcase size={12} /> <Users size={12} />
          Learning content and progress come from your own records; nothing on this page is sample data.</p>
      </div>
    </main>
  );
}
